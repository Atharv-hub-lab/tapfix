"""Retrieval: find candidate catalog entries for a piece of text.

Step 2 ships a keyword retriever (BM25, written here in plain Python). The
`Retriever` interface is deliberately tiny so that embeddings can be added next
and the two fused into a hybrid retriever WITHOUT touching the rest of the app.

Design notes
- BM25 uses an inverted index (term -> postings), so a query only touches the
  entries that share a word with it. This is what lets the same code scale from
  577 entries to 10,000+.
- Retrieval only ever searches catalog text (description + message +
  qna_description). It never sees, or matches on, the masked URI.
- Results are deterministic: ties are broken by catalog order.
- This module imports nothing from the rest of the app at runtime, so it is
  easy to test on its own.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Protocol, Sequence, Tuple

if TYPE_CHECKING:  # only for type hints; avoids a runtime import
    from app.catalog import CatalogEntry


_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Small on purpose. NOTE: "on", "off" and "not" are NOT stop words: they carry the
# enable/disable direction that the on/off resolver needs later.
STOPWORDS = frozenset(
    "a an the to of in for and or is are it this that your you my me i with by at as "
    "from be can will when how what do does if then so".split()
)


# Common technical terms that users may type with spaces or punctuation.
# These are normalized before BM25 tokenization.
#
# Examples:
#   Wi-Fi -> wifi
#   Wi Fi -> wifi
#   wifi  -> wifi
_COMPOUND_TERM_REPLACEMENTS = (
    (re.compile(r"\bwi[\s-]*fi\b", re.IGNORECASE), "wifi"),
)


def normalize_retrieval_text(text: str) -> str:
    """Normalize common technical terms without changing general tokenization."""
    normalized = text or ""

    for pattern, replacement in _COMPOUND_TERM_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)

    return normalized


def _stem(word: str) -> str:
    """Tiny plural stripper so 'enables' == 'enable' and 'settings' == 'setting'."""
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> List[str]:
    """Lower-case, split into words/numbers, drop stop words, strip plurals."""
    words = _TOKEN_RE.findall((text or "").lower())
    return [_stem(w) for w in words if w not in STOPWORDS]


@dataclass(frozen=True)
class Candidate:
    """One retrieved catalog entry, with enough detail to explain WHY it matched."""

    entry_id: str
    uri: str
    score: float
    rank: int  # 1 = best
    matched_terms: Tuple[str, ...] = ()


class Retriever(Protocol):
    def search(self, text: str, k: int = 10) -> List[Candidate]:
        """Return up to k candidates, best first."""
        ...


class BM25Retriever:
    """Okapi BM25 over each entry's `search_text`."""

    def __init__(
        self,
        entries: Sequence["CatalogEntry"],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self._entries = list(entries)
        self._k1, self._b = k1, b
        self._doc_len: List[int] = []
        self._postings: Dict[str, List[Tuple[int, int]]] = defaultdict(list)

        for doc_id, entry in enumerate(self._entries):
            tokens = tokenize(normalize_retrieval_text(entry.search_text))
            self._doc_len.append(len(tokens))

            for term, tf in Counter(tokens).items():
                self._postings[term].append((doc_id, tf))

        n_docs = len(self._entries)

        self._avg_len = (
            sum(self._doc_len) / n_docs
            if n_docs
            else 0.0
        )

        # idf, always positive:
        # ln(1 + (N - df + 0.5) / (df + 0.5))
        self._idf: Dict[str, float] = {
            term: math.log(
                1 + (n_docs - len(posts) + 0.5) / (len(posts) + 0.5)
            )
            for term, posts in self._postings.items()
        }

    def __len__(self) -> int:
        return len(self._entries)

    def search(self, text: str, k: int = 10) -> List[Candidate]:
        if k <= 0 or not self._entries:
            return []

        query_terms = sorted(
            set(tokenize(normalize_retrieval_text(text)))
        )

        scores: Dict[int, float] = defaultdict(float)
        matched: Dict[int, List[str]] = defaultdict(list)

        for term in query_terms:
            posts = self._postings.get(term)

            if not posts:
                continue

            idf = self._idf[term]

            for doc_id, tf in posts:
                length_norm = (
                    1
                    - self._b
                    + self._b
                    * (self._doc_len[doc_id] / self._avg_len)
                )

                scores[doc_id] += (
                    idf
                    * (tf * (self._k1 + 1))
                    / (tf + self._k1 * length_norm)
                )

                matched[doc_id].append(term)

        # Best score first; ties broken by catalog order,
        # so results are deterministic.
        ranked = sorted(
            scores.items(),
            key=lambda item: (-item[1], item[0]),
        )[:k]

        return [
            Candidate(
                entry_id=self._entries[doc_id].id,
                uri=self._entries[doc_id].uri,
                score=round(score, 6),
                rank=position,
                matched_terms=tuple(matched[doc_id]),
            )
            for position, (doc_id, score) in enumerate(ranked, start=1)
        ]