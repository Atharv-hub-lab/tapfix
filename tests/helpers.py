"""Small builders for tests that need tiny synthetic catalogs (no Samsung data needed)."""
from typing import Optional

from app.catalog import DUMMY_URI, CatalogEntry, CatalogIndex
from app.retrieval import Candidate


def make_entry(
    n: int,
    message: str,
    description: Optional[str] = None,
    original_type: Optional[str] = None,
    validation: Optional[dict] = None,
    qna: str = "",
    uri: Optional[str] = None,
    entry_id: Optional[str] = None,
) -> CatalogEntry:
    return CatalogEntry(
        id=entry_id or f"T-{n:04d}",
        uri=uri or f"bixby://masked/act/t{n:09d}",
        description=description or f"Opens {message.lower()} via device Settings on the device.",
        message=message,
        qna_description=qna,
        original_type=original_type,
        control_type=None,
        validation=validation,
    )


def dummy_entry() -> CatalogEntry:
    return CatalogEntry(
        id="T-DUMMY", uri=DUMMY_URI, description="Generic placeholder entry.", message="Placeholder",
        qna_description="", original_type=None, control_type=None, validation=None,
    )


# A small but realistic catalog: toggle pairs, navigation and adjust entries, plus filler topics.
_SPECS = [
    ("Enable Touch sensitivity", "Enables touch sensitivity via device Settings on the device.", "onURL"),
    ("Disable Touch sensitivity", "Disables touch sensitivity via device Settings on the device.", "offURL"),
    ("Enable Bluetooth", "Enables bluetooth via device Settings on the device.", "onURL"),
    ("Disable Bluetooth", "Disables bluetooth via device Settings on the device.", "offURL"),
    ("View Display", "Opens the display settings page in device Settings on the device.", "onClickURL"),
    ("Adjust Brightness", "Updates the screen brightness to a specified value via device Settings.", "updateURL"),
    ("View Sound", "Opens the sound settings page in device Settings on the device.", "onClickURL"),
    ("View Battery", "Opens the battery usage page in device Settings on the device.", "onClickURL"),
    ("Enable Wi-Fi calling", "Enables wifi calling via device Settings on the device.", "onURL"),
    ("Disable Wi-Fi calling", "Disables wifi calling via device Settings on the device.", "offURL"),
    ("View Keyboard layout", "Opens the keyboard layout page in device Settings on the device.", "onClickURL"),
    ("View Notification history", "Opens the notification history page in device Settings.", "onClickURL"),
    ("Enable Dark mode", "Enables dark mode via device Settings on the device.", "onURL"),
    ("Disable Dark mode", "Disables dark mode via device Settings on the device.", "offURL"),
    ("View Storage", "Opens the storage usage page in device Settings on the device.", "onClickURL"),
    ("View Accessibility", "Opens the accessibility page in device Settings on the device.", "onClickURL"),
]


def make_catalog(extra=(), specs=None) -> CatalogIndex:
    """Build a CatalogIndex from (message, description, original_type) specs plus `extra` entries."""
    entries = [make_entry(i, m, d, t) for i, (m, d, t) in enumerate(specs or _SPECS, start=1)]
    entries.extend(extra)
    entries.append(dummy_entry())
    return CatalogIndex(entries)


def by_message(catalog: CatalogIndex, message: str) -> CatalogEntry:
    return next(e for e in catalog.entries if e.message == message)


class StaticRetriever:
    """A retriever that returns exactly the candidates it was given (to test hostile results)."""

    def __init__(self, candidates):
        self._candidates = list(candidates)

    def search(self, text, k=10):
        return self._candidates[:k]


def cand(entry, score=20.0, rank=1, terms=()) -> Candidate:
    return Candidate(entry_id=entry.id, uri=entry.uri, score=score, rank=rank, matched_terms=tuple(terms))
