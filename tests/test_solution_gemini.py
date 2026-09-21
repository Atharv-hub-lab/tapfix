import json

import pytest

from app.llm.solution_gemini import GeminiSolutionProvider


class FakeResponse:
    def __init__(self, payload):
        self.text = json.dumps(payload)


class FakeModels:
    def __init__(self, response):
        self.response = response
        self.last_model = None
        self.last_contents = None
        self.last_config = None

    def generate_content(self, *, model, contents, config):
        self.last_model = model
        self.last_contents = contents
        self.last_config = config
        return self.response


class FakeClient:
    def __init__(self, response):
        self.models = FakeModels(response)


def valid_payload():
    return {
        "goal": "Turn on Wi-Fi",
        "title": "Wi-Fi",
        "score": 0.95,
        "action_name": "Enable Wi-Fi",
        "description": "Enable Wi-Fi from Settings.",
        "category": "auto",
        "steps": [
            "Open Wi-Fi settings.",
            "Turn on Wi-Fi.",
        ],
        "catalog_id": "DL-TEST",
    }


def test_solution_provider_parses_valid_response():
    client = FakeClient(FakeResponse(valid_payload()))

    provider = GeminiSolutionProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    result = provider.solve(
        query="My Wi-Fi will not turn on",
        context="Candidate: DL-TEST - Wi-Fi settings",
    )

    assert result.goal == "Turn on Wi-Fi"
    assert result.title == "Wi-Fi"
    assert result.score == 0.95
    assert result.catalog_id == "DL-TEST"
    assert result.steps == (
        "Open Wi-Fi settings.",
        "Turn on Wi-Fi.",
    )


def test_solution_provider_passes_query_and_context_to_gemini():
    client = FakeClient(FakeResponse(valid_payload()))

    provider = GeminiSolutionProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    provider.solve(
        query="My Wi-Fi will not turn on",
        context="Candidate: DL-TEST - Wi-Fi settings",
    )

    assert "My Wi-Fi will not turn on" in client.models.last_contents
    assert "DL-TEST" in client.models.last_contents


def test_solution_provider_rejects_blank_query():
    client = FakeClient(FakeResponse(valid_payload()))

    provider = GeminiSolutionProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    with pytest.raises(ValueError):
        provider.solve(
            query="",
            context="Candidate: DL-TEST",
        )


def test_solution_provider_rejects_blank_context():
    client = FakeClient(FakeResponse(valid_payload()))

    provider = GeminiSolutionProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    with pytest.raises(ValueError):
        provider.solve(
            query="My Wi-Fi will not turn on",
            context="",
        )


def test_solution_provider_rejects_invalid_llm_json():
    class InvalidResponse:
        text = "this is not json"

    client = FakeClient(InvalidResponse())

    provider = GeminiSolutionProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    with pytest.raises(RuntimeError):
        provider.solve(
            query="My Wi-Fi will not turn on",
            context="Candidate: DL-TEST",
        )


def test_solution_provider_rejects_invalid_solution_payload():
    payload = valid_payload()
    payload["deeplink"] = "bixby://fake"

    client = FakeClient(FakeResponse(payload))

    provider = GeminiSolutionProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    with pytest.raises(RuntimeError):
        provider.solve(
            query="My Wi-Fi will not turn on",
            context="Candidate: DL-TEST",
        )


def test_solution_provider_wraps_gemini_errors():
    class FailingModels:
        def generate_content(self, **kwargs):
            raise RuntimeError("temporary Gemini failure")

    class FailingClient:
        models = FailingModels()

    provider = GeminiSolutionProvider(
        api_key="test-key",
        model="test-model",
        client=FailingClient(),
    )

    with pytest.raises(RuntimeError, match="Gemini solution request failed"):
        provider.solve(
            query="My Wi-Fi will not turn on",
            context="Candidate: DL-TEST",
        )