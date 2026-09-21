import pytest

from app.llm.solution_parsing import parse_solution_draft


def valid_payload():
    return {
        "goal": "Turn on Wi-Fi",
        "title": "Wi-Fi",
        "score": 0.95,
        "action_name": "Enable Wi-Fi",
        "description": "It will enable Wi-Fi.",
        "category": "auto",
        "steps": [
            "Open Wi-Fi settings.",
            "Turn on Wi-Fi.",
        ],
        "catalog_id": "DL-TEST",
    }


def test_valid_solution_payload_is_parsed():
    result = parse_solution_draft(valid_payload())

    assert result.goal == "Turn on Wi-Fi"
    assert result.score == 0.95
    assert result.steps == (
        "Open Wi-Fi settings.",
        "Turn on Wi-Fi.",
    )
    assert result.catalog_id == "DL-TEST"


def test_missing_field_is_rejected():
    payload = valid_payload()
    del payload["steps"]

    with pytest.raises(ValueError):
        parse_solution_draft(payload)


def test_extra_field_is_rejected():
    payload = valid_payload()
    payload["deeplink"] = "bixby://evil"

    with pytest.raises(ValueError):
        parse_solution_draft(payload)


def test_invalid_score_is_rejected():
    payload = valid_payload()
    payload["score"] = 1.5

    with pytest.raises(ValueError):
        parse_solution_draft(payload)


def test_empty_steps_are_rejected():
    payload = valid_payload()
    payload["steps"] = []

    with pytest.raises(ValueError):
        parse_solution_draft(payload)


def test_catalog_id_can_be_null():
    payload = valid_payload()
    payload["catalog_id"] = None

    result = parse_solution_draft(payload)

    assert result.catalog_id is None