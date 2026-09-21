from app.nlp.pipeline import enrich_query


def test_enrich_query_returns_intent():
    result = enrich_query("Please turn on Wi-Fi")

    assert result.intent.direction == "ON"


def test_enrich_query_normalizes_retrieval_query():
    result = enrich_query("  Turn ON Wi-Fi!!!  ")

    assert result.retrieval_query == "turn on wi fi"


def test_enrich_query_preserves_original_query():
    query = "Please enable Bluetooth"

    result = enrich_query(query)

    assert result.intent.original_query == query


def test_enrich_query_off_direction():
    result = enrich_query("Disable Bluetooth")

    assert result.intent.direction == "OFF"


def test_enrich_query_unknown_direction():
    result = enrich_query("Bluetooth settings")

    assert result.intent.direction == "UNKNOWN"


def test_enrich_query_is_deterministic():
    query = "Turn on Wi-Fi"

    first = enrich_query(query)
    second = enrich_query(query)

    assert first == second