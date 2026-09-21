from types import SimpleNamespace

from app.config import RelevanceConfig
from app.relevance import (
    INSUFFICIENT_MARGIN,
    LOW_LABEL_COVERAGE,
    LOW_QUERY_COVERAGE,
    SCORE_TOO_LOW,
    TOO_FEW_MATCHED_TERMS,
    LabelStats,
    evaluate_relevance,
    label_terms,
)
from app.retrieval import Candidate

CFG = RelevanceConfig()


def entry(message, description=""):
    return SimpleNamespace(message=message, description=description)


def candidate(score=20.0, terms=()):
    return Candidate(entry_id="E1", uri="bixby://masked/act/e1", score=score, rank=1, matched_terms=tuple(terms))


def test_strong_match_passes_and_reports_all_signals():
    decision = evaluate_relevance(
        "touch sensitivity", candidate(15.0, ("touch", "sensitivity")), entry("Disable Touch sensitivity"), 5.0, CFG
    )
    assert decision.passed and decision.reason == "ok"
    s = decision.signals
    assert (s.top_score, s.matched_terms, s.query_coverage, s.label_coverage) == (15.0, 2, 1.0, 1.0)
    assert s.margin_ratio == round((15.0 - 5.0) / 15.0, 4)


def test_label_terms_ignore_catalog_verbs_but_fall_back_to_description():
    assert label_terms(entry("Enable Touch sensitivity"), CFG) == {"touch", "sensitivity"}
    assert label_terms(entry("View", "Opens the display page"), CFG) == {"open", "display", "page"}


def test_score_below_floor_fails():
    decision = evaluate_relevance("touch sensitivity", candidate(1.0, ("touch", "sensitivity")), entry("Touch sensitivity"), None, CFG)
    assert (decision.passed, decision.reason) == (False, SCORE_TOO_LOW)


def test_single_shared_word_is_not_enough():
    decision = evaluate_relevance("touch pizza", candidate(9.0, ("touch",)), entry("Touch sensitivity"), None, CFG)
    assert (decision.passed, decision.reason) == (False, TOO_FEW_MATCHED_TERMS)


def test_label_words_missing_from_query_fails():
    # the query only shares a generic word with a long label
    decision = evaluate_relevance(
        "double screen", candidate(9.0, ("double", "screen")), entry("Double tap to turn on screen"), None, CFG
    )
    assert (decision.passed, decision.reason) == (False, LOW_LABEL_COVERAGE)


def test_very_wordy_query_with_little_overlap_fails_query_coverage():
    query = "touch sensitivity " + " ".join(f"filler{i}" for i in range(30))
    decision = evaluate_relevance(query, candidate(12.0, ("touch", "sensitivity")), entry("Touch sensitivity"), None, CFG)
    assert (decision.passed, decision.reason) == (False, LOW_QUERY_COVERAGE)


def test_near_tie_with_a_different_setting_fails_margin():
    decision = evaluate_relevance("touch sensitivity", candidate(15.0, ("touch", "sensitivity")), entry("Touch sensitivity"), 14.9, CFG)
    assert (decision.passed, decision.reason) == (False, INSUFFICIENT_MARGIN)


def test_no_rival_means_no_margin_problem():
    decision = evaluate_relevance("touch sensitivity", candidate(15.0, ("touch", "sensitivity")), entry("Touch sensitivity"), None, CFG)
    assert decision.passed and decision.signals.margin_ratio is None


def test_thresholds_are_configurable_not_hard_coded():
    args = ("touch sensitivity", candidate(15.0, ("touch", "sensitivity")), entry("Touch sensitivity"), 14.0)
    assert evaluate_relevance(*args, RelevanceConfig(min_margin_ratio=0.02)).passed
    assert evaluate_relevance(*args, RelevanceConfig(min_margin_ratio=0.20)).reason == INSUFFICIENT_MARGIN
    assert evaluate_relevance(*args, RelevanceConfig(min_score=50.0)).reason == SCORE_TOO_LOW


def test_rare_label_words_count_for_more_than_common_ones():
    labels = [entry("Double tap to turn on screen"), entry("Screen timeout"), entry("Screen lock"), entry("Screen saver"), entry("Screen mirroring")]
    stats = LabelStats(labels, CFG)
    assert stats.weight("double") > stats.weight("screen")  # "screen" appears in every label
    top = entry("Double tap to turn on screen")
    common_only = evaluate_relevance("screen turn", candidate(9.0, ("screen", "turn")), top, None, CFG, stats)
    rare_included = evaluate_relevance("double tap", candidate(9.0, ("double", "tap")), top, None, CFG, stats)
    assert rare_included.signals.label_coverage > common_only.signals.label_coverage


def test_config_can_be_overridden_from_the_environment(monkeypatch):
    monkeypatch.setenv("TAPFIX_REL_MIN_SCORE", "7.5")
    monkeypatch.setenv("TAPFIX_REL_REQUIRE_DIRECTION_FOR_TOGGLES", "false")
    monkeypatch.setenv("TAPFIX_REL_LABEL_IGNORED_TERMS", "Enable, Disable")
    config = RelevanceConfig.from_env()
    assert config.min_score == 7.5
    assert config.require_direction_for_toggles is False
    assert config.label_ignored_terms == ("enable", "disable")
    assert config.min_margin_ratio == RelevanceConfig().min_margin_ratio  # untouched values keep defaults
