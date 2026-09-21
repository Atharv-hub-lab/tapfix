"""Loading Samsung's SIIS reference articles and the sample queries.

Note (found in the starter data): `siis_response` is an OBJECT {title, content},
while the guide's API example shows a raw string. `siis_text()` accepts both.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


class ArticleError(Exception):
    """siis_responses.json / input.txt is missing or malformed."""


@dataclass(frozen=True)
class SiisRecord:
    id: str
    original_query: str
    title: str
    content: str


def load_siis_records(path: Path) -> List[SiisRecord]:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ArticleError(f"SIIS file not found: {path}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ArticleError(f"SIIS file is not valid JSON: {path} ({exc})") from exc

    items = raw.get("responses") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ArticleError("SIIS file must be an object with a 'responses' list")

    records: List[SiisRecord] = []
    seen_ids = set()
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            raise ArticleError(f"SIIS record #{position} is not an object")
        record_id, query = item.get("id"), item.get("original_query")
        payload = item.get("siis_response")
        if not isinstance(record_id, str) or not isinstance(query, str):
            raise ArticleError(f"SIIS record #{position} needs string 'id' and 'original_query'")
        if record_id in seen_ids:
            raise ArticleError(f"duplicate SIIS record id: {record_id}")
        seen_ids.add(record_id)
        title, content = siis_text(payload)
        if not content.strip():
            raise ArticleError(f"SIIS record {record_id} has empty content")
        records.append(SiisRecord(id=record_id, original_query=query, title=title, content=content))
    return records


def load_queries(path: Path) -> List[str]:
    """One complaint per non-empty line. Lines are returned RAW (no cleaning yet)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ArticleError(f"query file not found: {path}") from exc
    return [line.strip() for line in text.splitlines() if line.strip()]


def siis_text(payload: object) -> Tuple[str, str]:
    """Normalise a siis_response into (title, content).

    Accepts a plain string (guide's example), a dict {title, content} (the
    starter data) or a pydantic object with those attributes (the API model).
    """
    if isinstance(payload, str):
        return "", payload
    if isinstance(payload, dict):
        title, content = payload.get("title", ""), payload.get("content", "")
    else:
        title, content = getattr(payload, "title", ""), getattr(payload, "content", "")
    if not isinstance(title, str) or not isinstance(content, str):
        raise ArticleError("siis_response title/content must be strings")
    return title, content
