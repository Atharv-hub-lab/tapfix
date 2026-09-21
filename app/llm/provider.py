from __future__ import annotations

from abc import ABC, abstractmethod

from app.nlp.query import QueryIntent, understand_query


class LLMProvider(ABC):
    """Interface for query-understanding providers."""

    @abstractmethod
    def understand(self, query: str) -> QueryIntent:
        """Convert a user's troubleshooting query into structured intent."""
        raise NotImplementedError


class DeterministicProvider(LLMProvider):
    """
    Current non-LLM query-understanding implementation.

    This keeps the existing deterministic behavior available as the
    fallback while the real LLM provider is being developed.
    """

    def understand(self, query: str) -> QueryIntent:
        return understand_query(query)