from __future__ import annotations

from typing import Any

from app.llm.provider import LLMProvider
from app.nlp.query import QueryIntent


class FallbackProvider(LLMProvider):
    """Use the primary provider and fall back when it fails."""

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

        # After a primary LLM failure, temporarily use the
        # deterministic fallback instead of repeatedly calling Gemini.
        self._llm_cooldown_until = 0.0
        self._cooldown_seconds = 60.0

    def understand(self, query: str) -> QueryIntent:
        import time

        now = time.monotonic()

        # Skip Gemini while the cooldown is active.
        if now < self._llm_cooldown_until:
            print(
                "[INFO] Primary LLM cooldown active; "
                "using deterministic fallback."
            )

            return self._fallback.understand(query)

        try:
            result = self._primary.understand(query)

            return result

        except Exception as exc:
            print(
                f"[WARN] Primary LLM failed: "
                f"{type(exc).__name__}: {exc}"
            )

            # Start the temporary cooldown.
            self._llm_cooldown_until = (
                time.monotonic() + self._cooldown_seconds
            )

            return self._fallback.understand(query)