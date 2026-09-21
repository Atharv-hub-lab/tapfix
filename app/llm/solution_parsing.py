from __future__ import annotations

from typing import Any, Mapping

from app.llm.solution import SolutionDraft


_REQUIRED_FIELDS = {
    "goal",
    "title",
    "score",
    "action_name",
    "description",
    "category",
    "steps",
    "catalog_id",
}

_ALLOWED_CATEGORIES = {
    "auto",
    "manual",
}


def parse_solution_draft(payload: Any) -> SolutionDraft:
    """
    Validate an untrusted Stage-2 LLM response and convert it
    into a SolutionDraft.

    The LLM output is never trusted directly.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("Solution LLM response must be a JSON object")

    fields = set(payload.keys())

    missing = _REQUIRED_FIELDS - fields
    extra = fields - _REQUIRED_FIELDS

    if missing:
        raise ValueError(
            f"Solution LLM response is missing fields: {sorted(missing)}"
        )

    if extra:
        raise ValueError(
            f"Solution LLM response contains unexpected fields: {sorted(extra)}"
        )

    goal = payload["goal"]
    title = payload["title"]
    score = payload["score"]
    action_name = payload["action_name"]
    description = payload["description"]
    category = payload["category"]
    steps = payload["steps"]
    catalog_id = payload["catalog_id"]

    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("goal must be a non-blank string")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-blank string")

    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ValueError("score must be a number")

    if not 0.0 <= float(score) <= 1.0:
        raise ValueError("score must be between 0 and 1")

    if not isinstance(action_name, str) or not action_name.strip():
        raise ValueError("action_name must be a non-blank string")

    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-blank string")

    if not isinstance(category, str) or category not in _ALLOWED_CATEGORIES:
        raise ValueError(
            f"category must be one of: {sorted(_ALLOWED_CATEGORIES)}"
        )

    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")

    if any(not isinstance(step, str) or not step.strip() for step in steps):
        raise ValueError("every step must be a non-blank string")

    if catalog_id is not None:
        if not isinstance(catalog_id, str) or not catalog_id.strip():
            raise ValueError(
                "catalog_id must be a non-blank string or null"
            )

    return SolutionDraft(
        goal=goal.strip(),
        title=title.strip(),
        score=float(score),
        action_name=action_name.strip(),
        description=description.strip(),
        category=category,
        steps=tuple(step.strip() for step in steps),
        catalog_id=catalog_id.strip() if catalog_id is not None else None,
    )