import time
from dataclasses import dataclass

from app.articles import load_queries
from app.retrieval import BM25Retriever, tokenize

DUMMY_URI = "bixby://dummy_positive"


@dataclass
class Doc:
    """Minimal stand-in for a catalog entry (the retriever only needs these fields)."""

    id: str
    uri: str
    search_text: str


def docs(*texts):
    return [Doc(id=f"D{i}", uri=f"bixby://masked/act/{i:010d}", search_text=t) for i, t in enumerate(texts)]


# ---------------- tokenizer ----------------
def test_tokenize_lowercases_drops_stopwords_and_strips_plurals():
    assert tokenize("Enables the Data Backups to your Cloud") == ["enable", "data", "backup", "cloud"]


def test_tokenize_keeps_direction_words():
    tokens = tokenize("Turn ON, then turn OFF. Do not enable")
    assert "on" in tokens and "off" in tokens and "not" in tokens


def test_tokenize_handles_empty_and_symbols():
    assert tokenize("") == []
    assert tokenize("  !!! ??? ") == []
    assert tokenize(None) == []


# ---------------- BM25 behaviour (small synthetic corpora) ----------------
def test_best_matching_entry_ranks_first():
    retriever = BM25Retriever(docs("Adjust screen brightness level", "Change the ringtone volume", "Enable auto rotate screen"))
    top = retriever.search("brightness of the screen", k=3)
    assert top[0].entry_id == "D0"


def test_ties_are_broken_by_catalog_order():
    retriever = BM25Retriever(docs("Disable dwell action", "Disable dwell action", "Something else entirely"))
    top = retriever.search("dwell action", k=5)
    assert [c.entry_id for c in top] == ["D0", "D1"]
    assert top[0].score == top[1].score


def test_results_are_deterministic():
    retriever = BM25Retriever(docs("screen brightness", "screen timeout", "brightness level"))
    first = retriever.search("screen brightness", k=3)
    assert retriever.search("screen brightness", k=3) == first
    assert retriever.search("screen brightness", k=3) == first


def test_k_limits_results_and_nonpositive_k_returns_nothing():
    retriever = BM25Retriever(docs(*[f"screen setting {i}" for i in range(20)]))
    assert len(retriever.search("screen", k=5)) == 5
    assert retriever.search("screen", k=0) == []
    assert retriever.search("screen", k=-3) == []


def test_empty_or_unmatched_queries_return_nothing():
    retriever = BM25Retriever(docs("Adjust screen brightness"))
    for query in ("", "   ", "the a an", "zzzz qqqq"):
        assert retriever.search(query) == []
    assert BM25Retriever([]).search("screen") == []


def test_ranks_are_sequential_and_explain_the_match():
    retriever = BM25Retriever(docs("brightness level", "screen brightness", "screen timeout"))
    top = retriever.search("screen brightness", k=3)
    assert [c.rank for c in top] == [1, 2, 3]
    assert top[0].entry_id == "D1"
    assert top[0].matched_terms == ("brightness", "screen")
    assert top[0].score >= top[1].score >= top[2].score


def test_masked_uris_are_never_searchable():
    entries = docs("Adjust screen brightness")
    entries[0].uri = "bixby://masked/act/abcdef1234"
    assert BM25Retriever(entries).search("abcdef1234") == []


def test_scales_to_ten_thousand_plus_entries():
    words = [f"word{i}" for i in range(500)]
    entries = docs(*[" ".join(words[(i * 7 + j) % 500] for j in range(30)) for i in range(12_000)])
    retriever = BM25Retriever(entries)
    start = time.perf_counter()
    top = retriever.search("word3 word10 word250", k=10)
    elapsed = time.perf_counter() - start
    assert len(top) == 10
    assert elapsed < 1.0  # generous bound; a single search is normally a few milliseconds
    scores = [c.score for c in top]
    assert scores == sorted(scores, reverse=True)


# ---------------- against the real Samsung catalog ----------------
def _retriever(catalog):
    return BM25Retriever(catalog.real_entries)  # the dummy is never searched


def test_retrieval_only_returns_real_catalog_entries(catalog, settings):
    retriever = _retriever(catalog)
    queries = load_queries(settings.input_path) + ["bixby settings", "turn on", "dummy positive"]
    for query in queries:
        for candidate in retriever.search(query, k=10):
            assert catalog.is_real_uri(candidate.uri)
            assert candidate.uri != DUMMY_URI


def test_samsung_sample_deeplink_is_in_top_3(catalog, sample_output):
    action = sample_output["response"]["contexts"][0]["actions"][0]
    group = action["stepGroups"][0]
    target = group["actionableDeeplink"]["deeplink"]
    query = action["actionName"] + " " + " ".join(group["steps"])
    assert target in [c.uri for c in _retriever(catalog).search(query, k=3)]


def test_explicit_enable_or_disable_steers_the_result(catalog):
    retriever = _retriever(catalog)
    on = retriever.search("enable back up data samsung cloud", k=1)[0]
    off = retriever.search("disable back up data samsung cloud", k=1)[0]
    assert catalog.get(on.uri).original_type == "onURL"
    assert catalog.get(off.uri).original_type == "offURL"


def test_uri_hash_tokens_never_match_anything(catalog):
    retriever = _retriever(catalog)
    for entry in catalog.real_entries:
        hash_part = entry.uri.rsplit("/", 1)[-1].lower()
        for candidate in retriever.search(entry.uri, k=10):
            assert hash_part not in candidate.matched_terms


def test_real_search_is_deterministic(catalog):
    retriever = _retriever(catalog)
    query = "turn off adaptive brightness"
    assert retriever.search(query, k=10) == retriever.search(query, k=10)
