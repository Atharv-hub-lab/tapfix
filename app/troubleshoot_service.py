from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from app.cache import FastPathCache
from app.catalog import CatalogIndex
from app.llm.orchestrator import build_solution_context
from app.llm.solution_provider import SolutionProvider
from app.llm.trusted_solution import build_trusted_solution
from app.plan import AssembledPlan
from app.retrieval import Retriever


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TroubleshootService:
    retriever: Retriever
    catalog: CatalogIndex
    query_provider: object
    solution_provider: SolutionProvider
    cache: FastPathCache | None = None

    def troubleshoot(
        self,
        query: str,
        k: int = 10,
        siis_response: object | None = None,
    ) -> AssembledPlan:
        cache_key = _build_cache_key(
            query=query,
            siis_response=siis_response,
        )

        if self.cache is not None:
            cached_response = self.cache.get(cache_key)

            if cached_response is not None:
                log.info("CACHE HIT: %s", query)

                return AssembledPlan(
                    ok=True,
                    response=cached_response,
                    goal="",
                    issues=(),
                )

            log.info("CACHE MISS: %s", query)

        solution_context = build_solution_context(
            query=query,
            retriever=self.retriever,
            catalog=self.catalog,
            query_provider=self.query_provider,
            solution_provider=self.solution_provider,
            k=k,
            siis_response=siis_response,
        )

        result = build_trusted_solution(
            solution_context.solution,
            self.catalog,
        )

        if self.cache is not None and result.ok:
            self.cache.put(
                cache_key,
                result.response,
            )

        return result


def _build_cache_key(
    query: str,
    siis_response: object | None,
) -> str:
    normalized_query = " ".join(
        query.strip().lower().split()
    )

    if siis_response is None:
        return normalized_query

    siis_signature = _build_siis_signature(siis_response)

    if not siis_signature:
        return normalized_query

    return f"{normalized_query} || siis:{siis_signature}"


def _build_siis_signature(
    siis_response: object,
) -> str:
    try:
        serialized = json.dumps(
            siis_response,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        serialized = str(siis_response)

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()[:16]