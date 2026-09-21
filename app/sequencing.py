"""Sequencing: put a plan's actions in a safe, deterministic order.

The rule (deliberately minimal, and based only on what Samsung's guide states):

  1. `critical` actions (factory reset, restart, firmware update, safe mode ...) go LAST.
  2. Everything else keeps the order it arrived in.
  3. Within each of the two groups, relative order is preserved (stable).

"The order it arrived in" is the source order: the order of Samsung's SIIS article
(after the LLM step in a later milestone), or retrieval-rank order when there is no
source order. Neither the LLM nor Python re-shuffles it, and the same input always gives
the same output.

What this does NOT do: Samsung also describes "Settings toggles -> system optimisations
-> device reboots", but the schema has no field that separates toggles from system
optimisations, so we do not invent a rule for it. Whether `manual` actions (physical
steps) should come before `critical` ones is likewise not documented; here they are simply
"non-critical" and keep their source position. We make no claim that this order is optimal.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Sequence

VALID_CATEGORIES = ("auto", "manual", "critical")
CRITICAL = "critical"


class SequencingError(ValueError):
    """An action has a missing or unknown category, so it cannot be ordered safely."""


def _category_of(action: Mapping[str, Any]) -> str:
    category = action.get("category") if isinstance(action, Mapping) else None
    category = getattr(category, "value", category)  # accept the schema's Enum too
    if category not in VALID_CATEGORIES:
        raise SequencingError(f"action has an invalid category: {category!r}")
    return category


def sequence_actions(actions: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Return a NEW list: non-critical actions in source order, then critical ones."""
    categories = [_category_of(a) for a in actions]  # validates every action first
    first = [a for a, c in zip(actions, categories) if c != CRITICAL]
    last = [a for a, c in zip(actions, categories) if c == CRITICAL]
    return first + last


def is_sequenced(categories: Sequence[Any]) -> bool:
    """True if no non-critical action comes after a critical one."""
    seen_critical = False
    for category in categories:
        category = getattr(category, "value", category)
        if category not in VALID_CATEGORIES:
            return False
        if category == CRITICAL:
            seen_critical = True
        elif seen_critical:
            return False
    return True
