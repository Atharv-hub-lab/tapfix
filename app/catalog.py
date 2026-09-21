"""Catalog loading and indexing (the "closed world" for deeplinks).

deeplinks.json is the ONLY source of Settings deeplinks. This module turns that
rule into code: a URI counts as valid only if it EXACTLY matches a catalog entry.
The LLM is never allowed to write a URI; it can only point at catalog entries,
and Python copies the real values from here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from pydantic import ValidationError

from app.schema import Deeplink, ValidationDeepLink

# Samsung's reserved placeholder: used ONLY when a step opens a valid Settings
# screen that has no dedicated catalog entry.
DUMMY_URI = "bixby://dummy_positive"


class CatalogError(Exception):
    """deeplinks.json is missing, malformed or inconsistent."""


@dataclass(frozen=True, eq=False)
class CatalogEntry:
    id: str
    uri: str
    description: str
    message: str
    qna_description: str
    original_type: Optional[str]  # onURL / offURL / onClickURL / updateURL / None
    control_type: Optional[int]
    validation: Optional[dict]  # raw validation object from the catalog

    @property
    def is_dummy(self) -> bool:
        return self.uri == DUMMY_URI

    @property
    def search_text(self) -> str:
        """Text used for retrieval. Deliberately excludes the masked URI."""
        parts = (self.description, self.message, self.qna_description)
        return " ".join(p for p in parts if p)


def _parse_entry(raw: object, position: int) -> CatalogEntry:
    if not isinstance(raw, dict):
        raise CatalogError(f"catalog entry #{position} is not an object")
    for key in ("id", "deeplink", "description"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise CatalogError(f"catalog entry #{position} has a missing or empty '{key}'")
    validation = raw.get("validation")
    if validation is not None and not isinstance(validation, dict):
        raise CatalogError(f"catalog entry {raw['id']}: 'validation' must be an object or null")
    return CatalogEntry(
        id=raw["id"],
        uri=raw["deeplink"],
        description=raw["description"],
        message=raw.get("message") or "",
        qna_description=raw.get("qna_description") or "",
        original_type=raw.get("originalType"),
        control_type=raw.get("control_type"),
        validation=validation,
    )


class CatalogIndex:
    """In-memory index over the catalog with exact-match (closed-world) lookups."""

    def __init__(self, entries: List[CatalogEntry]) -> None:
        self._entries: List[CatalogEntry] = list(entries)
        self._by_uri: Dict[str, CatalogEntry] = {}
        self._by_id: Dict[str, CatalogEntry] = {}
        self._validation: Dict[str, Optional[ValidationDeepLink]] = {}
        self._validation_uris: Set[str] = set()
        dummy: Optional[CatalogEntry] = None

        for entry in self._entries:
            if entry.uri in self._by_uri:
                raise CatalogError(f"duplicate deeplink URI in catalog: {entry.uri}")
            if entry.id in self._by_id:
                raise CatalogError(f"duplicate catalog id: {entry.id}")
            self._by_uri[entry.uri] = entry
            self._by_id[entry.id] = entry
            if entry.is_dummy:
                if dummy is not None:
                    raise CatalogError("catalog contains more than one dummy entry")
                dummy = entry
            model = self._build_validation(entry)
            self._validation[entry.uri] = model
            if model is not None:
                self._validation_uris.add(model.deeplink)

        if dummy is None:
            raise CatalogError(f"catalog has no {DUMMY_URI} entry")
        self._dummy: CatalogEntry = dummy
        self._real: List[CatalogEntry] = [e for e in self._entries if not e.is_dummy]

    @staticmethod
    def _build_validation(entry: CatalogEntry) -> Optional[ValidationDeepLink]:
        if entry.validation is None:
            return None
        try:
            return ValidationDeepLink(**entry.validation)
        except (ValidationError, TypeError) as exc:
            raise CatalogError(f"catalog entry {entry.id}: invalid validation object ({exc})") from exc

    @classmethod
    def from_file(cls, path: Path) -> "CatalogIndex":
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise CatalogError(f"catalog file not found: {path}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CatalogError(f"catalog file is not valid JSON: {path} ({exc})") from exc
        items = raw.get("deeplinks") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            raise CatalogError("catalog must be an object with a 'deeplinks' list")
        declared = raw.get("count")
        if declared is not None and declared != len(items):
            raise CatalogError(f"catalog says count={declared} but has {len(items)} entries")
        return cls([_parse_entry(item, i) for i, item in enumerate(items)])

    # ---- basic access -------------------------------------------------
    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> List[CatalogEntry]:
        return list(self._entries)

    @property
    def real_entries(self) -> List[CatalogEntry]:
        """All entries except the dummy placeholder (these are what retrieval searches)."""
        return list(self._real)

    @property
    def dummy(self) -> CatalogEntry:
        return self._dummy

    def get(self, uri: object) -> Optional[CatalogEntry]:
        """Exact-match lookup. Any change (case, spaces, one character) returns None."""
        return self._by_uri.get(uri) if isinstance(uri, str) else None

    def get_by_id(self, entry_id: object) -> Optional[CatalogEntry]:
        return self._by_id.get(entry_id) if isinstance(entry_id, str) else None

    # ---- closed-world checks ------------------------------------------
    def is_real_uri(self, uri: object) -> bool:
        """True only for a genuine catalog deeplink (the dummy does NOT count)."""
        return isinstance(uri, str) and uri != DUMMY_URI and uri in self._by_uri

    def is_allowed_uri(self, uri: object) -> bool:
        """True for a genuine catalog deeplink OR the reserved dummy placeholder."""
        return isinstance(uri, str) and uri in self._by_uri

    def is_real_validation_uri(self, uri: object) -> bool:
        """True only if `uri` is the validation deeplink of some catalog entry."""
        return isinstance(uri, str) and uri in self._validation_uris

    # ---- building schema objects FROM the catalog (never from the LLM) --
    def to_deeplink(self, entry: CatalogEntry) -> Deeplink:
        """Copy a catalog entry into Samsung's Deeplink model, verbatim."""
        if entry.is_dummy:
            raise ValueError(
                "The dummy entry's placeholder text must not be copied; "
                "write a specific description and message for the screen instead."
            )
        return Deeplink(
            deeplink=entry.uri,
            description=entry.description,
            message=entry.message,
            originalType=entry.original_type,
        )

    def to_validation_deeplink(self, entry: CatalogEntry) -> Optional[ValidationDeepLink]:
        """The entry's validation deeplink (checks the toggle state), or None."""
        return self._validation.get(entry.uri)
