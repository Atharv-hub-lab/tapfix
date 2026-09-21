from __future__ import annotations

from dataclasses import dataclass

from app.llm.provider import DeterministicProvider, LLMProvider
from app.nlp.query import QueryIntent


@dataclass(frozen=True)
class EnrichedQuery:
    intent: QueryIntent
    retrieval_query: str


def enrich_query(
    query: str,
    provider: LLMProvider | None = None,
) -> EnrichedQuery:
    """
    Enrich a user query using the selected query-understanding provider.

    If no provider is supplied, the deterministic provider is used.
    """

    active_provider = provider or DeterministicProvider()

    intent = active_provider.understand(query)

    retrieval_query = intent.normalized_query

    return EnrichedQuery(
        intent=intent,
        retrieval_query=retrieval_query,
    )