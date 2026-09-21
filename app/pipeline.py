from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.llm.provider import LLMProvider
from app.nlp.pipeline import EnrichedQuery, enrich_query
from app.retrieval import Candidate, Retriever


@dataclass(frozen=True)
class RetrievalResult:
    query: EnrichedQuery
    candidates: List[Candidate]


def retrieve_for_query(
    query: str,
    retriever: Retriever,
    k: int = 10,
    provider: LLMProvider | None = None,
) -> RetrievalResult:
    enriched = enrich_query(
        query,
        provider=provider,
    )

    candidates = retriever.search(
        enriched.retrieval_query,
        k=k,
    )

    return RetrievalResult(
        query=enriched,
        candidates=candidates,
    )