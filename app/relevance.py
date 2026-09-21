"""Relevance gate: is the best retrieved entry actually RELEVANT to the query?

BM25 always returns *something*, even for unrelated queries (Step 2 found that
"safe mode restart" returns unrelated settings). "Top result = answer" is therefore
never assumed. This gate looks at several independent signals and lets a candidate
through only if ALL of them pass. Every threshold lives in RelevanceConfig
(app/config.py) and is an initial engineering value, not a calibrated one.

Signals
- top_score        BM25 score of the best candidate (sanity floor only)
- matched_terms    how many distinct query words the entry shares
- query_coverage   share of the query's words found in the entry
- label_coverage   share of the entry's LABEL words (its short `message`, minus verbs
                   like Enable/View) found in the query, weighted by how RARE each word is
                   across all labels (so "screen" or "turn" count for little, "tap" or
                   "sensitivity" for a lot). Robust to long, wordy queries.
- margin_ratio     how far the best entry is ahead of the best DIFFERENT setting.
                   (ON/OFF twins and identical-text duplicates do not count as rivals.)
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Set

from app.config import RelevanceConfig
from app.retrieval import Candidate, tokenize


@dataclass(frozen=True)
class RelevanceSignals:
    top_score: float
    matched_terms: int
    query_coverage: float
    label_coverage: float
    margin_ratio: Optional[float]  # None = no rival setting among the candidates


@dataclass(frozen=True)
class RelevanceDecision:
    passed: bool
    reason: str  # "ok" or one of the failure codes below
    signals: RelevanceSignals


# failure codes (stable strings: tests and later observability rely on them)
SCORE_TOO_LOW = "score_too_low"
TOO_FEW_MATCHED_TERMS = "too_few_matched_terms"
LOW_LABEL_COVERAGE = "low_label_coverage"
LOW_QUERY_COVERAGE = "low_query_coverage"
INSUFFICIENT_MARGIN = "insufficient_margin"


def label_terms(entry: Any, config: RelevanceConfig) -> Set[str]:
    """The topic words of an entry's label (falls back to its description if the label is empty)."""
    ignored = set(config.label_ignored_terms)
    terms = {t for t in tokenize(getattr(entry, "message", "") or "") if t not in ignored}
    if not terms:
        terms = {t for t in tokenize(getattr(entry, "description", "") or "") if t not in ignored}
    return terms


class LabelStats:
    """How rare each label word is across the whole catalog (built once, reused)."""

    def __init__(self, entries: Iterable[Any], config: RelevanceConfig) -> None:
        self._n = 0
        self._df: Counter = Counter()
        for entry in entries:
            self._n += 1
            self._df.update(label_terms(entry, config))

    def weight(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log(1 + (self._n - df + 0.5) / (df + 0.5))


def _label_coverage(labels: Set[str], query_terms: Set[str], stats: Optional[LabelStats]) -> float:
    if not labels:
        return 0.0
    weight = stats.weight if stats else (lambda _term: 1.0)
    total = sum(weight(t) for t in labels)
    hit = sum(weight(t) for t in labels & query_terms)
    return hit / total if total > 0 else 0.0


def evaluate_relevance(
    query: str,
    top: Candidate,
    top_entry: Any,
    rival_score: Optional[float],
    config: RelevanceConfig,
    stats: Optional[LabelStats] = None,
) -> RelevanceDecision:
    query_terms = set(tokenize(query))
    labels = label_terms(top_entry, config)
    matched = set(top.matched_terms)

    query_coverage = (len(matched & query_terms) / len(query_terms)) if query_terms else 0.0
    label_coverage = _label_coverage(labels, query_terms, stats)
    margin: Optional[float] = None
    if rival_score is not None and top.score > 0:
        margin = (top.score - rival_score) / top.score

    signals = RelevanceSignals(
        top_score=top.score,
        matched_terms=len(matched & query_terms),
        query_coverage=round(query_coverage, 4),
        label_coverage=round(label_coverage, 4),
        margin_ratio=None if margin is None else round(margin, 4),
    )

    required_terms = min(config.min_matched_terms, max(1, len(labels)))
    if top.score < config.min_score:
        reason = SCORE_TOO_LOW
    elif signals.matched_terms < required_terms:
        reason = TOO_FEW_MATCHED_TERMS
    elif label_coverage < config.min_label_coverage:
        reason = LOW_LABEL_COVERAGE
    elif query_coverage < config.min_query_coverage:
        reason = LOW_QUERY_COVERAGE
    elif margin is not None and margin < config.min_margin_ratio:
        reason = INSUFFICIENT_MARGIN
    else:
        reason = "ok"
    return RelevanceDecision(passed=(reason == "ok"), reason=reason, signals=signals)
