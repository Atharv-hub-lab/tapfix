from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


Direction = Literal["ON", "OFF", "UNKNOWN"]


@dataclass(frozen=True)
class QueryIntent:
    """Structured understanding of a user's troubleshooting request."""

    original_query: str
    normalized_query: str
    direction: Direction
    keywords: tuple[str, ...]


_ON_PATTERNS = (
    r"\bturn\s+on\b",
    r"\benable\b",
    r"\bactivate\b",
    r"\bswitch\s+on\b",
    r"\bstart\b",
    r"\bturn\s+\S+\s+on\b",
    r"\bswitch\s+\S+\s+on\b",
)

_OFF_PATTERNS = (
    r"\bturn\s+off\b",
    r"\bdisable\b",
    r"\bdeactivate\b",
    r"\bswitch\s+off\b",
    r"\bstop\b",
    r"\bturn\s+\S+\s+off\b",
    r"\bswitch\s+\S+\s+off\b",
)


_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "could",
    "do",
    "for",
    "how",
    "i",
    "is",
    "me",
    "my",
    "please",
    "the",
    "to",
    "want",
    "what",
    "with",
    "you",
}


def _normalize(text: str) -> str:
    """Normalize user text without changing its meaning."""

    text = text.lower().strip()

    # Keep alphanumeric characters and spaces.
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # Collapse repeated whitespace.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _resolve_direction(text: str) -> Direction:
    """Resolve an explicit ON/OFF request."""

    on_found = any(re.search(pattern, text) for pattern in _ON_PATTERNS)
    off_found = any(re.search(pattern, text) for pattern in _OFF_PATTERNS)

    # Conflicting instructions must never be guessed.
    if on_found and off_found:
        return "UNKNOWN"

    if on_found:
        return "ON"

    if off_found:
        return "OFF"

    return "UNKNOWN"


def _extract_keywords(normalized_query: str) -> tuple[str, ...]:
    """Extract useful lexical terms for retrieval."""

    words = normalized_query.split()

    keywords: list[str] = []

    for word in words:
        if word in _STOP_WORDS:
            continue

        if word in {
            "turn",
            "enable",
            "disable",
            "activate",
            "deactivate",
            "switch",
            "start",
            "stop",
            "on",
            "off",
        }:
            continue

        if len(word) < 2:
            continue

        if word not in keywords:
            keywords.append(word)

    return tuple(keywords)


def understand_query(query: str) -> QueryIntent:
    """
    Convert a natural-language troubleshooting query
    into deterministic structured intent.
    """

    if not isinstance(query, str):
        raise TypeError("query must be a string")

    if not query.strip():
        raise ValueError("query must not be empty")

    normalized = _normalize(query)

    return QueryIntent(
        original_query=query,
        normalized_query=normalized,
        direction=_resolve_direction(normalized),
        keywords=_extract_keywords(normalized),
    )