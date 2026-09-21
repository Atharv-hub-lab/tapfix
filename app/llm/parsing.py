from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.nlp.query import QueryIntent


_REQUIRED_FIELDS = {
    "original_query",
    "normalized_query",
    "direction",
    "keywords",
}

_ALLOWED_DIRECTIONS = {"ON", "OFF", "UNKNOWN"}


def parse_query_intent(payload: Any) -> QueryIntent:
    """
    Validate an untrusted structured LLM response and convert it
    into the application's trusted QueryIntent representation.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("LLM response must be a JSON object")

    keys = set(payload.keys())

    missing = _REQUIRED_FIELDS - keys
    if missing:
        raise ValueError(
            f"LLM response is missing required fields: {sorted(missing)}"
        )

    extra = keys - _REQUIRED_FIELDS
    if extra:
        raise ValueError(
            f"LLM response contains unsupported fields: {sorted(extra)}"
        )

    original_query = payload["original_query"]
    normalized_query = payload["normalized_query"]
    direction = payload["direction"]
    keywords = payload["keywords"]

    if not isinstance(original_query, str):
        raise ValueError("original_query must be a string")

    if not original_query.strip():
        raise ValueError("original_query must not be blank")

    if not isinstance(normalized_query, str):
        raise ValueError("normalized_query must be a string")

    if not normalized_query.strip():
        raise ValueError("normalized_query must not be blank")

    if not isinstance(direction, str):
        raise ValueError("direction must be a string")

    if direction not in _ALLOWED_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(_ALLOWED_DIRECTIONS)}"
        )

    if not isinstance(keywords, (list, tuple)):
        raise ValueError("keywords must be a list or tuple")

    cleaned_keywords: list[str] = []

    for keyword in keywords:
        if not isinstance(keyword, str):
            raise ValueError("every keyword must be a string")

        keyword = keyword.strip()

        if not keyword:
            raise ValueError("keywords must not contain blank values")

        cleaned_keywords.append(keyword)

    return QueryIntent(
        original_query=original_query.strip(),
        normalized_query=normalized_query.strip(),
        direction=direction,
        keywords=tuple(cleaned_keywords),
    )