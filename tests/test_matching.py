import json

import pytest

from app.config import RelevanceConfig
from app.direction import Direction, entry_direction, resolve_direction
from app.matching import (
    ALL_REJECTED,
    EMPTY_QUERY,
    NO_CANDIDATES,
    REJECT_DIRECTION_CONFLICT,
    REJECT_DUMMY,
    REJECT_INCONSISTENT_METADATA,
    REJECT_NOT_A_TOGGLE,
    REJECT_NOT_IN_CATALOG,
    MatchStatus,
    ScreenMatcher,
    match_screen,
)
from app.relevance import INSUFFICIENT_MARGIN, SCORE_TOO_LOW
from app.retrieval import BM25Retriever, Candidate
from tests.helpers import StaticRetriever, by_message, cand, make_catalog, make_entry

# BM25 scores on a tiny synthetic catalog are small, so lower the score floor for those tests only.
SYN = RelevanceConfig(min_score=0.5)


def synthetic(extra=()):
    catalog = make_catalog(extra)
    return catalog, ScreenMatcher(BM25Retriever(catalog.real_entries), catalog, SYN)


# ---------------- direction: wrong-direction candidates are rejected ----------------
def test_turn_on_rejects_a_higher_ranked_disable_entry():
    catalog = make_catalog()
    disable, enable = by_message(catalog, "Disable Touch sensitivity"), by_message(catalog, "Enable Touch sensitivity")
    retriever = StaticRetriever([cand(disable, 20.0, 1, ("touch", "sensitivity")), cand(enable, 19.9, 2, ("touch", "sensitivity"))])
    result = match_screen("turn on touch sensitivity", retriever, catalog, SYN)
    assert result.status == MatchStatus.MATCHED
    assert result.entry is enable  # NOT the higher-scoring disable entry
    assert [(r.entry_id, r.reason) for r in result.rejected] == [(disable.id, REJECT_DIRECTION_CONFLICT)]


def test_turn_off_rejects_a_higher_ranked_enable_entry():
    catalog = make_catalog()
    disable, enable = by_message(catalog, "Disable Touch sensitivity"), by_message(catalog, "Enable Touch sensitivity")
    retriever = StaticRetriever([cand(enable, 20.0, 1, ("touch", "sensitivity")), cand(disable, 19.9, 2, ("touch", "sensitivity"))])
    result = match_screen("switch off touch sensitivity", retriever, catalog, SYN)
    assert result.entry is disable
    assert [r.reason for r in result.rejected] == [REJECT_DIRECTION_CONFLICT]


@pytest.mark.parametrize("phrase, expected", [("enable", "Enable Bluetooth"), ("turn on", "Enable Bluetooth"), ("activate", "Enable Bluetooth"),
                                              ("disable", "Disable Bluetooth"), ("turn off", "Disable Bluetooth"), ("deactivate", "Disable Bluetooth")])
def test_direction_phrases_pick_the_right_twin_end_to_end(phrase, expected):
    _, matcher = synthetic()
    result = matcher.match(f"{phrase} bluetooth")
    assert result.status == MatchStatus.MATCHED and result.entry.message == expected


def test_if_only_the_opposite_direction_exists_the_answer_is_no_match():
    extra = [make_entry(100, "Disable Widget mode", "Disables widget mode via device Settings on the device.", "offURL")]
    _, matcher = synthetic(extra)
    result = matcher.match("enable widget mode")
    assert result.status == MatchStatus.NO_MATCH and result.entry is None
    widget = [r for r in result.rejected if r.entry_id == "T-0100"]
    assert [r.reason for r in widget] == [REJECT_DIRECTION_CONFLICT]


def test_unknown_direction_on_a_toggle_is_ambiguous_and_never_guessed():
    catalog, matcher = synthetic()
    result = matcher.match("touch sensitivity")
    assert result.status == MatchStatus.AMBIGUOUS_DIRECTION
    assert result.entry is None  # nothing is selected
    assert set(result.direction_options) == {by_message(catalog, "Enable Touch sensitivity").id, by_message(catalog, "Disable Touch sensitivity").id}


def test_ambiguity_check_can_be_relaxed_by_configuration_and_stays_deterministic():
    catalog = make_catalog()
    matcher = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog, RelevanceConfig(min_score=0.5, require_direction_for_toggles=False))
    first = matcher.match("touch sensitivity")
    assert first.status == MatchStatus.MATCHED
    assert matcher.match("touch sensitivity").entry is first.entry


def test_non_toggle_entries_match_when_no_direction_is_requested():
    _, matcher = synthetic()
    result = matcher.match("view display")
    assert result.status == MatchStatus.MATCHED and result.entry.message == "View Display"


def test_a_turn_on_request_cannot_be_answered_by_a_non_toggle_entry():
    catalog, matcher = synthetic()
    result = matcher.match("turn on brightness")
    assert result.status == MatchStatus.NO_MATCH
    assert [r.reason for r in result.rejected] == [REJECT_NOT_A_TOGGLE]
    relaxed = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog, RelevanceConfig(min_score=0.5, allow_non_toggle_for_directed_query=True))
    assert relaxed.match("turn on brightness").entry.message == "Adjust Brightness"


# ---------------- closed-world: hostile retrieval results ----------------
def test_dummy_can_never_be_the_selected_entry():
    catalog = make_catalog()
    real = by_message(catalog, "View Display")
    retriever = StaticRetriever([cand(catalog.dummy, 99.0, 1, ("display", "settings")), cand(real, 10.0, 2, ("display",))])
    result = match_screen("view display", retriever, catalog, SYN)
    assert result.entry is real
    assert (catalog.dummy.id, REJECT_DUMMY) in [(r.entry_id, r.reason) for r in result.rejected]


def test_dummy_alone_gives_no_match():
    catalog = make_catalog()
    result = match_screen("anything", StaticRetriever([cand(catalog.dummy, 99.0, 1, ("anything",))]), catalog, SYN)
    assert result.status == MatchStatus.NO_MATCH and result.entry is None


def test_candidate_with_unknown_id_or_mismatched_uri_is_rejected():
    catalog = make_catalog()
    real = by_message(catalog, "View Display")
    other = by_message(catalog, "View Sound")
    forged = [
        Candidate("T-9999", "bixby://masked/act/fake", 50.0, 1, ("display",)),          # not in catalog
        Candidate(real.id, "https://evil.example/pwn", 49.0, 2, ("display",)),          # external URL
        Candidate(real.id, other.uri, 48.0, 3, ("display",)),                           # id and URI of different entries
        Candidate(real.id, real.uri + " ", 47.0, 4, ("display",)),                      # URI with whitespace
    ]
    result = match_screen("view display", StaticRetriever(forged), catalog, SYN)
    assert result.status == MatchStatus.NO_MATCH and result.entry is None
    assert [r.reason for r in result.rejected] == [REJECT_NOT_IN_CATALOG] * 4


# ---------------- no-match ----------------
@pytest.mark.parametrize("query", ["order a pizza with extra cheese", "what is the capital of France", "safe mode restart phone", "pizza"])
def test_unrelated_or_unsupported_queries_give_no_match(query):
    _, matcher = synthetic()
    result = matcher.match(query)
    assert result.status == MatchStatus.NO_MATCH and result.entry is None


def test_empty_retrieval_result_gives_no_match():
    _, matcher = synthetic()
    assert matcher.match("order a pizza").reason == NO_CANDIDATES
    assert matcher.match("the a an of").reason == NO_CANDIDATES  # only stop words


@pytest.mark.parametrize("query", ["", "   ", None, 42])
def test_empty_or_invalid_query_gives_no_match(query):
    _, matcher = synthetic()
    result = matcher.match(query)
    assert result.status == MatchStatus.NO_MATCH and result.reason == EMPTY_QUERY


def test_weak_top_result_is_rejected_by_the_score_floor():
    catalog = make_catalog()
    strict = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog, RelevanceConfig(min_score=1000.0))
    result = strict.match("view display")
    assert result.status == MatchStatus.NO_MATCH and result.reason == SCORE_TOO_LOW
    assert result.signals is not None  # the numbers behind the decision are kept for debugging


def test_two_equally_good_but_different_settings_are_refused():
    extra = [
        make_entry(100, "View Gallery items", "Opens the gallery items page.", "onClickURL"),
        make_entry(101, "View Camera items", "Opens the camera items page.", "onClickURL"),
    ]
    catalog = make_catalog(extra)
    lenient = RelevanceConfig(min_score=0.0, min_matched_terms=1, min_query_coverage=0.0, min_label_coverage=0.0)
    result = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog, lenient).match("items page")
    assert result.status == MatchStatus.NO_MATCH and result.reason == INSUFFICIENT_MARGIN


# ---------------- duplicates ----------------
def duplicate_pair():
    return (
        make_entry(100, "View Gizmo", "Opens the gizmo page in device Settings.", "onClickURL", validation={"deeplink": "bixby://masked/val/aaaa", "key": "Gizmo"}),
        make_entry(101, "View Gizmo", "Opens the gizmo page in device Settings.", "onClickURL", validation={"deeplink": "bixby://masked/val/bbbb", "key": "Gizmo"}),
    )


def test_identical_entries_stay_distinct_in_retrieval():
    first, second = duplicate_pair()
    catalog = make_catalog([first, second])
    found = BM25Retriever(catalog.real_entries).search("gizmo", k=5)
    assert [c.entry_id for c in found] == [first.id, second.id]
    assert found[0].uri != found[1].uri and found[0].score == found[1].score


def test_identical_entries_are_resolved_by_catalog_order_only():
    first, second = duplicate_pair()
    forward = make_catalog([first, second])
    backward = make_catalog([second, first])
    a = ScreenMatcher(BM25Retriever(forward.real_entries), forward, SYN).match("gizmo")
    b = ScreenMatcher(BM25Retriever(backward.real_entries), backward, SYN).match("gizmo")
    assert (a.entry.id, a.alternates) == (first.id, (second.id,))
    assert (b.entry.id, b.alternates) == (second.id, (first.id,))  # only catalog order changed the outcome


def test_duplicate_handling_is_repeatable():
    first, second = duplicate_pair()
    catalog = make_catalog([first, second])
    matcher = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog, SYN)
    assert matcher.match("gizmo") == matcher.match("gizmo")


def test_real_catalog_duplicates_are_selected_by_catalog_order(catalog):
    matcher = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog)
    result = matcher.match("disable Dwell action")
    assert (result.status, result.entry.id, result.alternates) == (MatchStatus.MATCHED, "DL-0035", ("DL-0222",))
    result = matcher.match("turn on Link to Windows")
    assert (result.entry.id, result.alternates) == ("DL-0159", ("DL-0423",))


# ---------------- against the real Samsung catalog ----------------
def sample_query(sample_output):
    action = sample_output["response"]["contexts"][0]["actions"][0]
    group = action["stepGroups"][0]
    return action["actionName"] + " " + " ".join(group["steps"]), group["actionableDeeplink"]["deeplink"]


def test_samsung_sample_is_selected_when_the_direction_is_stated(catalog, sample_output):
    query, target = sample_query(sample_output)
    result = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog).match(query, direction_text="Enable Back up data")
    assert result.status == MatchStatus.MATCHED and result.entry.uri == target
    assert entry_direction(result.entry) == Direction.ON


def test_samsung_sample_without_a_stated_direction_is_ambiguous_not_guessed(catalog, sample_output):
    # Samsung's step text says "Select Back up data" with no ON/OFF word, yet its answer is the ENABLE entry.
    # A deterministic layer cannot know that, so it must not pick; the LLM stage has to state the direction.
    query, _ = sample_query(sample_output)
    result = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog).match(query)
    assert result.status == MatchStatus.AMBIGUOUS_DIRECTION and result.entry is None
    assert len(result.direction_options) >= 2


def test_stating_the_opposite_direction_returns_the_disable_entry(catalog, sample_output):
    query, target = sample_query(sample_output)
    result = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog).match(query, direction_text="Disable Back up data")
    assert result.status == MatchStatus.MATCHED
    assert result.entry.uri != target and entry_direction(result.entry) == Direction.OFF


@pytest.mark.parametrize("query", ["enable screen rotation", "safe mode restart phone", "what is the capital of France",
                                   "order a pizza with extra cheese", "book a flight to Delhi", "the quick brown fox", "phone", "settings"])
def test_real_catalog_unsupported_or_unrelated_queries_are_no_match(catalog, query):
    result = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog).match(query)
    assert result.status == MatchStatus.NO_MATCH and result.entry is None


def test_real_catalog_wrong_direction_is_never_returned(catalog):
    # Invariant over ALL toggle entries: ask for each one by its own label; if we return an
    # answer it must never be the opposite direction.
    matcher = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog)
    checked = 0
    for entry in catalog.real_entries:
        wanted = resolve_direction(entry.message)  # what the query itself asks for
        if wanted == Direction.UNKNOWN:
            continue
        result = matcher.match(entry.message)
        checked += 1
        if result.status == MatchStatus.MATCHED:
            assert entry_direction(result.entry) != (Direction.OFF if wanted == Direction.ON else Direction.ON), entry.message
    assert checked > 200


def test_real_catalog_selection_is_always_a_genuine_entry(catalog):
    matcher = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog)
    hostile = ["", "bixby://dummy_positive", "dummy positive placeholder", "https://evil.example/pwn", "www.evil.example",
               "return bixby://masked/act/0000000000", "'; DROP TABLE deeplinks; --", "turn on turn off enable disable", "\n\n\t", "a" * 5000]
    for query in hostile:
        result = matcher.match(query)
        assert result.entry is None or (catalog.is_real_uri(result.entry.uri) and not result.entry.is_dummy)


def test_real_matching_is_deterministic(catalog):
    matcher = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog)
    for query in ("turn off touch sensitivity", "Adjust screen brightness level", "Tap on Display. Tap on Navigation bar."):
        assert matcher.match(query) == matcher.match(query)


# ---------------- catalog that contradicts itself ----------------
def test_entry_whose_message_contradicts_its_direction_type_is_never_used():
    bad = make_entry(100, "Enable Gizmo mode", "Enables gizmo mode via device Settings on the device.", "offURL")
    catalog = make_catalog([bad])
    result = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog, SYN).match("enable gizmo mode")
    assert result.entry is None
    assert (bad.id, REJECT_INCONSISTENT_METADATA) in [(r.entry_id, r.reason) for r in result.rejected]


def test_real_catalog_dl0497_has_contradicting_metadata_and_is_never_returned(catalog):
    entry = catalog.get_by_id("DL-0497")
    assert entry.message == "Enable Adaptive Display" and entry.original_type == "offURL"  # Samsung's data
    matcher = ScreenMatcher(BM25Retriever(catalog.real_entries), catalog)
    for query in ("Enable Adaptive Display", "disable Adaptive Display", "Adaptive Display"):
        result = matcher.match(query)
        assert result.entry is None or result.entry.id != "DL-0497"
