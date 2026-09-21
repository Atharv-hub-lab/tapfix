from app.llm.fallback import FallbackProvider
from app.llm.provider import LLMProvider
from app.nlp.query import QueryIntent


class WorkingProvider(LLMProvider):
    def understand(self, query: str) -> QueryIntent:
        return QueryIntent(
            original_query=query,
            normalized_query="wifi connection",
            direction="ON",
            keywords=("wifi", "wireless"),
        )


class FailingProvider(LLMProvider):
    def understand(self, query: str) -> QueryIntent:
        raise RuntimeError("temporary Gemini failure")


def test_primary_provider_is_used_when_successful():
    provider = FallbackProvider(
        primary=WorkingProvider(),
        fallback=FailingProvider(),
    )

    result = provider.understand("My Wi-Fi will not turn on")

    assert result.normalized_query == "wifi connection"
    assert result.direction == "ON"
    assert result.keywords == ("wifi", "wireless")


def test_fallback_provider_is_used_when_primary_fails():
    provider = FallbackProvider(
        primary=FailingProvider(),
        fallback=WorkingProvider(),
    )

    result = provider.understand("My Wi-Fi will not turn on")

    assert result.normalized_query == "wifi connection"
    assert result.direction == "ON"
    assert result.keywords == ("wifi", "wireless")