from app.catalog import CatalogIndex
from app.config import Settings
from app.pipeline import retrieve_for_query
from app.retrieval import BM25Retriever


def _make_retriever():
    settings = Settings.from_env()
    catalog = CatalogIndex.from_file(settings.deeplinks_path)
    return BM25Retriever(catalog.real_entries)


def test_pipeline_enriches_query():
    retriever = _make_retriever()

    result = retrieve_for_query(
        "Please turn on Wi-Fi",
        retriever,
    )

    assert result.query.intent.direction == "ON"
    assert result.query.retrieval_query == "please turn on wi fi"


def test_pipeline_returns_candidates():
    retriever = _make_retriever()

    result = retrieve_for_query(
        "Wi-Fi",
        retriever,
        k=5,
    )

    assert result.candidates
    assert len(result.candidates) <= 5


def test_pipeline_candidate_ids_are_present():
    retriever = _make_retriever()

    result = retrieve_for_query(
        "Bluetooth",
        retriever,
        k=5,
    )

    assert all(candidate.entry_id for candidate in result.candidates)


def test_pipeline_is_deterministic():
    retriever = _make_retriever()

    first = retrieve_for_query("Wi-Fi", retriever, k=5)
    second = retrieve_for_query("Wi-Fi", retriever, k=5)

    assert first == second