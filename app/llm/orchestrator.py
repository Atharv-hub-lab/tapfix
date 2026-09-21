from __future__ import annotations

from dataclasses import dataclass

from app.catalog import CatalogIndex
from app.llm.provider import LLMProvider
from app.llm.solution import SolutionDraft
from app.llm.solution_provider import SolutionProvider
from app.nlp.pipeline import EnrichedQuery, enrich_query
from app.retrieval import Candidate, Retriever


@dataclass(frozen=True)
class SolutionContext:
    """Everything required to generate a Stage-2 solution."""

    query: EnrichedQuery
    candidates: tuple[Candidate, ...]
    solution: SolutionDraft


def build_solution_context(
    query: str,
    retriever: Retriever,
    catalog: CatalogIndex,
    query_provider: LLMProvider,
    solution_provider: SolutionProvider,
    k: int = 10,
    siis_response: object | None = None,
) -> SolutionContext:
    """
    Run Stage 1 query understanding, retrieve candidates from both
    the user's complaint and the SIIS troubleshooting evidence,
    then generate a Stage-2 solution.

    The solution is still untrusted at this point.
    """

    # ---------------------------------------------------------
    # STAGE 1: Understand the user's query
    # ---------------------------------------------------------
    enriched = enrich_query(
        query,
        provider=query_provider,
    )

    # ---------------------------------------------------------
    # RETRIEVAL PASS 1:
    # Search using the user's normalized complaint.
    # ---------------------------------------------------------
    query_candidates = retriever.search(
        enriched.retrieval_query,
        k=k,
    )

    # ---------------------------------------------------------
    # RETRIEVAL PASS 2:
    # Search using the SIIS troubleshooting evidence.
    #
    # This is important because the user's complaint may be
    # vague, while SIIS can contain the exact troubleshooting
    # language needed to find a relevant catalog action.
    # ---------------------------------------------------------
    siis_candidates = _retrieve_siis_candidates(
        siis_response=siis_response,
        retriever=retriever,
        k=k,
    )

    # ---------------------------------------------------------
    # MERGE BOTH RETRIEVAL RESULTS
    #
    # Query candidates come first.
    # SIIS candidates are added afterwards.
    # Duplicate catalog IDs are removed.
    # ---------------------------------------------------------
    candidates = _merge_candidates(
        primary=query_candidates,
        secondary=siis_candidates,
    )

    # ---------------------------------------------------------
    # Build the context that Stage 2 receives.
    # ---------------------------------------------------------
    candidate_context = _build_candidate_context(
        candidates,
        catalog,
    )

    context = _build_solution_context(
        candidate_context=candidate_context,
        siis_response=siis_response,
    )

    # ---------------------------------------------------------
    # STAGE 2: Generate the troubleshooting solution.
    # ---------------------------------------------------------
    solution = solution_provider.solve(
        query=query,
        context=context,
    )

    return SolutionContext(
        query=enriched,
        candidates=tuple(candidates),
        solution=solution,
    )


def _retrieve_siis_candidates(
    siis_response: object | None,
    retriever: Retriever,
    k: int,
) -> list[Candidate]:
    """
    Retrieve catalog candidates using the SIIS troubleshooting
    evidence.

    SIIS can contain more specific troubleshooting terminology
    than the original customer complaint, so it gets its own
    retrieval pass.
    """

    if siis_response is None:
        return []

    from app.articles import siis_text

    title, content = siis_text(siis_response)

    siis_query = " ".join(
        part.strip()
        for part in (title, content)
        if part and part.strip()
    )

    if not siis_query:
        return []

    return retriever.search(
        siis_query,
        k=k,
    )


def _merge_candidates(
    primary: list[Candidate],
    secondary: list[Candidate],
) -> list[Candidate]:
    """
    Merge two candidate lists while preserving order and
    removing duplicate catalog IDs.

    Candidates from the original user query are kept first.
    SIIS-derived candidates are then added if they are new.
    """

    merged: list[Candidate] = []
    seen_ids: set[str] = set()

    for candidate in [*primary, *secondary]:
        if candidate.entry_id in seen_ids:
            continue

        seen_ids.add(candidate.entry_id)
        merged.append(candidate)

    return merged


def _build_solution_context(
    candidate_context: str,
    siis_response: object | None,
) -> str:
    """
    Combine optional SIIS evidence with the trusted catalog
    candidate context.

    SIIS provides troubleshooting evidence.
    Catalog candidates provide the available Settings actions.
    """

    if siis_response is None:
        return candidate_context

    from app.articles import siis_text

    title, content = siis_text(siis_response)

    if not title.strip() and not content.strip():
        return candidate_context

    siis_section = (
        "SIIS TROUBLESHOOTING EVIDENCE:\n"
        f"title={title}\n"
        f"content={content}\n\n"
    )

    return siis_section + "CATALOG CANDIDATES:\n" + candidate_context


def _build_candidate_context(
    candidates: list[Candidate],
    catalog: CatalogIndex,
) -> str:
    """
    Convert retrieval candidates into compact Stage-2 context.

    Catalog metadata is authoritative.
    The LLM receives no deeplink URI.
    """

    if not candidates:
        return "No matching catalog candidates were found."

    lines: list[str] = []

    for index, candidate in enumerate(candidates, start=1):
        entry = catalog.get_by_id(candidate.entry_id)

        if entry is None:
            continue

        lines.append(
            f"Candidate {index}: "
            f"id={entry.id}; "
            f"description={entry.description}; "
            f"message={entry.message}; "
            f"qna_description={entry.qna_description}"
        )

    if not lines:
        return "No matching catalog candidates were found."

    return "\n".join(lines)