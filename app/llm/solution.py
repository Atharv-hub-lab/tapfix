from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SolutionDraft:
    """Untrusted structured output produced by the solution LLM."""

    goal: str
    title: str
    score: float
    action_name: str
    description: str
    category: str
    steps: tuple[str, ...]
    catalog_id: str | None
    