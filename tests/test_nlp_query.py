import pytest

from app.nlp.query import understand_query


def test_turn_on_resolves_on():
    result = understand_query("Please turn on Wi-Fi")

    assert result.direction == "ON"
    assert result.normalized_query == "please turn on wi fi"
    assert "wifi" not in result.keywords


def test_enable_resolves_on():
    result = understand_query("Enable Bluetooth")

    assert result.direction == "ON"


def test_activate_resolves_on():
    result = understand_query("Activate mobile data")

    assert result.direction == "ON"


def test_turn_off_resolves_off():
    result = understand_query("Please turn off Wi-Fi")

    assert result.direction == "OFF"


def test_disable_resolves_off():
    result = understand_query("Disable Bluetooth")

    assert result.direction == "OFF"


def test_no_direction_is_unknown():
    result = understand_query("Wi-Fi settings")

    assert result.direction == "UNKNOWN"


def test_conflicting_direction_is_unknown():
    result = understand_query("Turn on and turn off Wi-Fi")

    assert result.direction == "UNKNOWN"


def test_keywords_remove_common_stop_words():
    result = understand_query("Can you enable Bluetooth for me")

    assert "can" not in result.keywords
    assert "you" not in result.keywords
    assert "for" not in result.keywords
    assert "me" not in result.keywords
    assert "bluetooth" in result.keywords


def test_duplicate_keywords_are_removed():
    result = understand_query("Bluetooth Bluetooth settings")

    assert result.keywords.count("bluetooth") == 1


def test_original_query_is_preserved():
    query = "Please ENABLE Bluetooth!"

    result = understand_query(query)

    assert result.original_query == query


def test_empty_query_is_rejected():
    with pytest.raises(ValueError):
        understand_query("")


def test_whitespace_query_is_rejected():
    with pytest.raises(ValueError):
        understand_query("   ")


def test_non_string_query_is_rejected():
    with pytest.raises(TypeError):
        understand_query(None)