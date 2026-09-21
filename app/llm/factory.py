from __future__ import annotations

from app.config import Settings
from app.llm.fallback import FallbackProvider
from app.llm.gemini import GeminiProvider
from app.llm.provider import DeterministicProvider, LLMProvider


def build_query_provider(settings: Settings) -> LLMProvider:
    deterministic = DeterministicProvider()

    if settings.llm_provider.lower() != "gemini":
        return deterministic

    if not settings.llm_api_key.strip():
        return deterministic

    gemini = GeminiProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )

    return FallbackProvider(
        primary=gemini,
        fallback=deterministic,
    )