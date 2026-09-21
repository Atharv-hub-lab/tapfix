"""Direction: does some text ask to turn a setting ON or OFF?

Why this exists: the catalog stores separate "Enable X" and "Disable X" entries whose
text differs by one word, and it says "Enables/Disables", never "turn on/off". So a
text retriever alone can return the WRONG direction for "turn on X" (found in Step 2).
This module is deterministic and fails closed: when the direction is not clear the
answer is UNKNOWN, never a guess.

Intended input: an INSTRUCTION or intent ("Turn on Adaptive brightness"), which is what
the future LLM stage will produce. It is NOT designed for raw complaints: "my screen
turns off by itself" describes a symptom, not a request, and would be misread as OFF.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Tuple

from app.retrieval import tokenize


class Direction(str, Enum):
    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


_ON_VERBS = frozenset(
    "enable enables enabled enabling activate activates activated activating".split()
)
_OFF_VERBS = frozenset(
    "disable disables disabled disabling deactivate deactivates deactivated deactivating".split()
)
_PHRASAL_VERBS = frozenset(
    "turn turns turned turning switch switches switched switching toggle toggles toggled toggling".split()
)
# Words that make a direction phrase unreliable ("do not turn on"): result becomes UNKNOWN.
_NEGATIONS = frozenset(
    "not never without dont don't doesnt doesn't didnt didn't cant can't cannot wont won't no stop avoid".split()
)
# "switch to the tab on ..." is not "switch on": prepositions cannot sit between verb and on/off.
_BLOCKERS = frozenset(
    "to into from in at by of for with between back up down over around through".split()
)

_WORD_RE = re.compile(r"[a-z']+")
_CLAUSE_SPLIT_RE = re.compile(r"[.;:,!?\n()]+|\b(?:and|then|but|or)\b")
_MAX_FILLER_WORDS = 3  # "turn adaptive brightness on" has 2
# "turn it off and on", "off then back on", "on or off": both directions are named -> UNKNOWN
_ONOFF_PAIR_RE = re.compile(r"\b(?:on|off)\s+(?:and|or|then)\s+(?:back\s+)?(?:on|off)\b")


@dataclass(frozen=True)
class DirectionSignal:
    direction: Direction
    evidence: Tuple[str, ...] = ()  # the phrases that were found, for explainability
    note: str = ""  # why UNKNOWN, when it is UNKNOWN


def _scan_clause(tokens: List[str]) -> List[Tuple[Direction, str, Tuple[int, ...], bool]]:
    """Find direction phrases in one clause: (direction, phrase, token positions, negated)."""
    hits: List[Tuple[Direction, str, Tuple[int, ...], bool]] = []
    for i, word in enumerate(tokens):
        direction = None
        phrase, used = word, (i,)
        if word in _ON_VERBS:
            direction = Direction.ON
        elif word in _OFF_VERBS:
            direction = Direction.OFF
        elif word in _PHRASAL_VERBS:
            for j in range(i + 1, min(len(tokens), i + 2 + _MAX_FILLER_WORDS)):
                nxt = tokens[j]
                if nxt in ("on", "off"):
                    direction = Direction.ON if nxt == "on" else Direction.OFF
                    phrase, used = " ".join(tokens[i : j + 1]), (i, j)
                    break
                if nxt in _BLOCKERS or nxt in _PHRASAL_VERBS or nxt in _ON_VERBS or nxt in _OFF_VERBS:
                    break
        if direction is None:
            continue
        if i > 0 and tokens[i - 1] == "to":
            # "double tap to turn off screen": part of a setting's NAME (or a purpose clause);
            # we cannot tell, so it is neither a direction nor removed from the topic.
            continue
        negated = any(prev in _NEGATIONS for prev in tokens[max(0, i - 3) : i])
        hits.append((direction, phrase, used, negated))
    return hits


def _clauses(text: str) -> List[List[str]]:
    cleaned = text.lower().replace("\u2019", "'")
    return [_WORD_RE.findall(clause or "") for clause in _CLAUSE_SPLIT_RE.split(cleaned)]


def explain_direction(text: Any) -> DirectionSignal:
    """Resolve direction with the evidence. Anything unclear is UNKNOWN."""
    if not isinstance(text, str) or not text.strip():
        return DirectionSignal(Direction.UNKNOWN, note="empty text")
    if _ONOFF_PAIR_RE.search(text.lower()):
        return DirectionSignal(Direction.UNKNOWN, note="conflicting directions")
    found: List[Tuple[Direction, str]] = []
    for tokens in _clauses(text):
        for direction, phrase, _, negated in _scan_clause(tokens):
            if negated:
                return DirectionSignal(Direction.UNKNOWN, (phrase,), "negated direction")
            found.append((direction, phrase))

    directions = {d for d, _ in found}
    evidence = tuple(p for _, p in found)
    if not directions:
        return DirectionSignal(Direction.UNKNOWN, note="no direction words")
    if len(directions) > 1:
        return DirectionSignal(Direction.UNKNOWN, evidence, "conflicting directions")
    return DirectionSignal(directions.pop(), evidence)


def strip_direction_words(text: Any) -> str:
    """The text without its ON/OFF words ("turn off touch sensitivity" -> "touch sensitivity").

    Direction is handled by its own filter, so those words should not also steer retrieval
    toward entries that merely contain the phrase "turn off" in their topic.
    """
    if not isinstance(text, str):
        return ""
    kept: List[str] = []
    for tokens in _clauses(text):
        drop = {pos for _, _, used, _ in _scan_clause(tokens) for pos in used}
        kept.extend(tok for i, tok in enumerate(tokens) if i not in drop)
    return " ".join(kept)


def resolve_direction(text: Any) -> Direction:
    return explain_direction(text).direction


# ---------------------------------------------------------------------------
# Direction of a CATALOG ENTRY, taken from catalog metadata (never guessed from prose)
# ---------------------------------------------------------------------------
def entry_direction(entry: Any) -> Direction:
    """ON/OFF for toggle entries, UNKNOWN for everything else.

    - originalType 'onURL' -> ON, 'offURL' -> OFF (Samsung's own metadata).
    - 'onClickURL' ("View X") and 'updateURL' ("Adjust X") open or adjust a screen; they
      are not toggles, so their direction is UNKNOWN ("not applicable").
    - Catalog quirk: 2 entries (DL-0294/0295) have originalType null but a validation key
      of exactly 'offURL'/'onURL'; that catalog field is used for them.
    """
    original_type = getattr(entry, "original_type", None)
    if original_type == "onURL":
        return Direction.ON
    if original_type == "offURL":
        return Direction.OFF
    if original_type is None:
        validation = getattr(entry, "validation", None)
        key = validation.get("key") if isinstance(validation, dict) else None
        if key == "onURL":
            return Direction.ON
        if key == "offURL":
            return Direction.OFF
    return Direction.UNKNOWN


def directions_conflict(wanted: Direction, entry_dir: Direction) -> bool:
    """True only when BOTH are known and they are opposite. UNKNOWN never conflicts."""
    return {wanted, entry_dir} == {Direction.ON, Direction.OFF}


_DIRECTION_TOKENS = frozenset({"enable", "disable"})


def direction_twin_key(entry: Any) -> Tuple[str, ...]:
    """Identifies "the same setting", ignoring enable/disable.

    Two entries with the same key are the ON and OFF versions of one setting (137 of the
    138 ON entries in Samsung's catalog have such a twin).
    """
    return tuple(sorted(t for t in tokenize(entry.search_text) if t not in _DIRECTION_TOKENS))
