from __future__ import annotations

from app.llm.provider import LLMProvider
from app.nlp.query import QueryIntent


class MockLLMProvider(LLMProvider):
    """
    Deterministic provider used by tests.

    No network access, API key, or external service is required.
    """

    def __init__(self, response: QueryIntent):
        self._response = response

    def understand(self, query: str) -> QueryIntent:
        return self._response