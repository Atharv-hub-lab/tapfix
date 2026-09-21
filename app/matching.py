"""Matching: from a query to ONE trusted catalog entry, or a safe refusal.

Pipeline (all deterministic, no LLM):

  strip direction words -> retrieve -> closed-world filter -> direction filter
           -> group duplicates -> relevance gate -> direction-ambiguity check -> selection

Direction words ("turn off", "enable") are removed from the text used for retrieval and
scoring, because direction has its own filter; left in, they would pull in unrelated
entries whose topic merely contains "turn off screen".

Outcomes
  MATCHED              one catalog entry was selected
  NO_MATCH             nothing relevant enough (the caller returns Samsung's no_match)
  AMBIGUOUS_DIRECTION  a relevant Enable/Disable toggle, but the requested direction is
                       unknown; we refuse to guess ON or OFF

Entries whose own message contradicts their direction metadata are never used (fail closed).

A request to turn something ON/OFF can only be answered by a toggle entry (Enable/Disable):
"View X" and "Adjust X" entries open or adjust a screen and are rejected for such requests.

Fails closed: an unverifiable candidate is dropped, and if nothing survives the result is
NO_MATCH. There is no "fall back to the first catalog item".

Duplicates: 5 pairs of catalog entries have IDENTICAL text and differ only in their
validation deeplink (nothing that expresses user intent). They stay distinct in the
candidate list; the one that comes first in catalog order is selected and the others are
reported in `alternates`. Catalog order is the only deterministic tie-breaker available.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional, Tuple

from app.catalog import CatalogEntry, CatalogIndex
from app.config import RelevanceConfig
from app.direction import (
    Direction,
    direction_twin_key,
    directions_conflict,
    entry_direction,
    resolve_direction,
    strip_direction_words,
)
from app.relevance import LabelStats, RelevanceSignals, evaluate_relevance, label_terms
from app.retrieval import Candidate, Retriever, tokenize


class MatchStatus(str, Enum):
    MATCHED = "matched"
    NO_MATCH = "no_match"
    AMBIGUOUS_DIRECTION = "ambiguous_direction"


# rejection / reason codes produced here (relevance codes live in app/relevance.py)
EMPTY_QUERY = "empty_query"
NO_CANDIDATES = "no_candidates"
ALL_REJECTED = "all_candidates_rejected"
DIRECTION_UNKNOWN_FOR_TOGGLE = "direction_unknown_for_toggle"
REJECT_NOT_IN_CATALOG = "not_in_catalog"
REJECT_DUMMY = "dummy_entry"
REJECT_DIRECTION_CONFLICT = "direction_conflict"
REJECT_NOT_A_TOGGLE = "not_a_toggle"
REJECT_INCONSISTENT_METADATA = "inconsistent_direction_metadata"


@dataclass(frozen=True)
class Rejection:
    entry_id: str
    uri: str
    reason: str


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    reason: str
    entry: Optional[CatalogEntry] = None
    query_direction: Direction = Direction.UNKNOWN
    candidates_considered: int = 0
    rejected: Tuple[Rejection, ...] = ()
    alternates: Tuple[str, ...] = ()  # ids of identical-text duplicates that were NOT selected
    direction_options: Tuple[str, ...] = ()  # ids of the ON/OFF versions (AMBIGUOUS_DIRECTION only)
    signals: Optional[RelevanceSignals] = None


def _text_key(entry: Any) -> Tuple[str, ...]:
    return tuple(tokenize(entry.search_text))


class ScreenMatcher:
    """Holds the retriever, catalog and config (and the label statistics, built once)."""

    def __init__(self, retriever: Retriever, catalog: CatalogIndex, config: Optional[RelevanceConfig] = None) -> None:
        self.retriever = retriever
        self.catalog = catalog
        self.config = config or RelevanceConfig()
        self._stats = LabelStats(catalog.real_entries, self.config)

    def match(self, query: str, *, k: int = 10, direction_text: Optional[str] = None) -> MatchResult:
        return _match(query, self.retriever, self.catalog, self.config, self._stats, k, direction_text)


def match_screen(
    query: str,
    retriever: Retriever,
    catalog: CatalogIndex,
    config: Optional[RelevanceConfig] = None,
    *,
    k: int = 10,
    direction_text: Optional[str] = None,
) -> MatchResult:
    """Convenience wrapper. For repeated use build one ScreenMatcher instead."""
    return ScreenMatcher(retriever, catalog, config).match(query, k=k, direction_text=direction_text)


def _match(
    query: str,
    retriever: Retriever,
    catalog: CatalogIndex,
    config: RelevanceConfig,
    stats: LabelStats,
    k: int,
    direction_text: Optional[str],
) -> MatchResult:
    """Select one catalog entry for `query`, or refuse safely.

    direction_text: the text whose ON/OFF intent should be used (later: the LLM's stated
    intent). Defaults to the query itself.
    """
    if not isinstance(query, str) or not query.strip():
        return MatchResult(MatchStatus.NO_MATCH, EMPTY_QUERY)

    query_direction = resolve_direction(query if direction_text is None else direction_text)
    topic_query = strip_direction_words(query)  # what retrieval and the gate actually see
    raw = retriever.search(topic_query, k=k)
    if not raw:
        return MatchResult(MatchStatus.NO_MATCH, NO_CANDIDATES, query_direction=query_direction)

    # ---- closed-world + direction filtering --------------------------------
    rejected: List[Rejection] = []
    kept: List[Tuple[Candidate, CatalogEntry]] = []
    for cand in raw:
        entry = catalog.get_by_id(cand.entry_id)
        # The candidate's id and uri must BOTH point at the same real catalog entry.
        if entry is None or catalog.get(cand.uri) is not entry:
            rejected.append(Rejection(str(cand.entry_id), str(cand.uri), REJECT_NOT_IN_CATALOG))
        elif entry.is_dummy:
            rejected.append(Rejection(cand.entry_id, cand.uri, REJECT_DUMMY))
        elif directions_conflict(resolve_direction(entry.message), entry_direction(entry)):
            # The catalog contradicts itself (e.g. DL-0497: message "Enable ..." but type offURL).
            # We cannot know which is right, so the entry is never used.
            rejected.append(Rejection(cand.entry_id, cand.uri, REJECT_INCONSISTENT_METADATA))
        elif directions_conflict(query_direction, entry_direction(entry)):
            rejected.append(Rejection(cand.entry_id, cand.uri, REJECT_DIRECTION_CONFLICT))
        elif (
            query_direction != Direction.UNKNOWN
            and entry_direction(entry) == Direction.UNKNOWN
            and not config.allow_non_toggle_for_directed_query
        ):
            rejected.append(Rejection(cand.entry_id, cand.uri, REJECT_NOT_A_TOGGLE))
        else:
            kept.append((cand, entry))

    def result(status: MatchStatus, reason: str, **extra: Any) -> MatchResult:
        return MatchResult(
            status,
            reason,
            query_direction=query_direction,
            candidates_considered=len(raw),
            rejected=tuple(rejected),
            **extra,
        )

    if not kept:
        return result(MatchStatus.NO_MATCH, ALL_REJECTED)

    # ---- group identical-text duplicates (first in rank/catalog order represents the group)
    groups: List[Tuple[Candidate, CatalogEntry, List[str]]] = []
    seen_index = {}
    for cand, entry in kept:
        key = _text_key(entry)
        if key in seen_index:
            groups[seen_index[key]][2].append(entry.id)
        else:
            seen_index[key] = len(groups)
            groups.append((cand, entry, []))

    top_cand, top_entry, duplicate_ids = groups[0]

    # ---- relevance gate ------------------------------------------------------
    # A "rival" must be a DIFFERENT setting. Not rivals: the ON/OFF twin of the top entry, and
    # entries with the same topic words (e.g. "View Adjust Brightness" vs "Adjust Brightness").
    top_key = direction_twin_key(top_entry)
    top_topic = label_terms(top_entry, config)
    rival_score = next(
        (
            cand.score
            for cand, entry, _ in groups[1:]
            if direction_twin_key(entry) != top_key and label_terms(entry, config) != top_topic
        ),
        None,
    )
    decision = evaluate_relevance(topic_query, top_cand, top_entry, rival_score, config, stats)
    if not decision.passed:
        return result(MatchStatus.NO_MATCH, decision.reason, signals=decision.signals)

    # ---- direction ambiguity: never guess ON or OFF -----------------------------
    if (
        config.require_direction_for_toggles
        and query_direction == Direction.UNKNOWN
        and entry_direction(top_entry) != Direction.UNKNOWN
    ):
        options = tuple(
            entry.id
            for _, entry in kept
            if direction_twin_key(entry) == top_key and entry_direction(entry) != Direction.UNKNOWN
        )
        return result(
            MatchStatus.AMBIGUOUS_DIRECTION,
            DIRECTION_UNKNOWN_FOR_TOGGLE,
            direction_options=options,
            signals=decision.signals,
        )

    return result(
        MatchStatus.MATCHED,
        "ok",
        entry=top_entry,
        alternates=tuple(duplicate_ids),
        signals=decision.signals,
    )
