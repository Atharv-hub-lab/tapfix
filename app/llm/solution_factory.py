from __future__ import annotations

from app.config import Settings
from app.llm.solution_gemini import GeminiSolutionProvider
from app.llm.solution_provider import (
    DeterministicSolutionProvider,
    FallbackSolutionProvider,
    SolutionProvider,
)


def build_solution_provider(settings: Settings) -> SolutionProvider:
    deterministic = DeterministicSolutionProvider()

    if settings.llm_provider.lower() != "gemini":
        return deterministic

    if not settings.llm_api_key.strip():
        return deterministic

    gemini = GeminiSolutionProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )

    return FallbackSolutionProvider(
        primary=gemini,
        fallback=deterministic,
    )