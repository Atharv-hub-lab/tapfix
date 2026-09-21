from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any

from app.nlp.query import understand_query


@dataclass(frozen=True)
class CacheEntry:
    response: dict[str, Any]
    normalized_query: str
    direction: str
    keywords: frozenset[str]
    context_signature: str = ""


class FastPathCache:
    """
    Fast-path cache with:

    1. Exact normalized-query lookup.
    2. Paraphrase lookup using deterministic query intent.
    3. SIIS-aware context matching.
    4. LRU eviction.
    5. Thread-safe statistics.
    """

    PARAPHRASE_THRESHOLD = 0.60

    def __init__(self, max_entries: int = 10_000):
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")

        self._max_entries = max_entries
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()

        self._hits = 0
        self._misses = 0
        self._exact_hits = 0
        self._paraphrase_hits = 0

        self._lock = Lock()

    @staticmethod
    def _split_cache_key(
        key: str,
    ) -> tuple[str, str]:
        """
        Split the cache key into:

        query
        SIIS context signature

        Example:

        my phone screen is black || siis:abc123

        becomes:

        query = my phone screen is black
        context = abc123
        """

        marker = " || siis:"

        if marker in key:
            query, context = key.split(marker, 1)
            return query.strip(), context.strip()

        return key.strip(), ""

    @staticmethod
    def _canonicalize_keyword(keyword: str) -> str:
     aliases = {
        "display": "screen",
        "displays": "screen",
        "screens": "screen",

        "totally": "completely",
        "entirely": "completely",
        "fully": "completely",

        "smartphone": "phone",
        "smartphones": "phone",

        "wi": "wifi",
        "fi": "wifi",
        "wireless": "wifi",
    }

     return aliases.get(keyword, keyword)

    def _build_signature(
        self,
        key: str,
    ) -> tuple[str, str, frozenset[str]]:
        """
        Build a cache-specific intent signature.

        Only the actual user query is used for NLP matching.
        The SIIS fingerprint is handled separately.
        """

        query_text, _ = self._split_cache_key(key)

        intent = understand_query(query_text)

        normalized_query = intent.normalized_query.strip().lower()
        direction = intent.direction

        # Recognize additional ON/OFF paraphrases specifically
        # for cache matching.
        if direction == "UNKNOWN":
            on_patterns = (
                r"\bturn\b.*\bon\b",
                r"\bswitch\b.*\bon\b",
                r"\bturned\s+on\b",
                r"\bswitched\s+on\b",
                r"\benabled\b",
                r"\bactivate(?:d)?\b",
            )

            off_patterns = (
                r"\bturn\b.*\boff\b",
                r"\bswitch\b.*\boff\b",
                r"\bturned\s+off\b",
                r"\bswitched\s+off\b",
                r"\bdisabled\b",
                r"\bdeactivate(?:d)?\b",
            )

            on_found = any(
                re.search(pattern, normalized_query)
                for pattern in on_patterns
            )

            off_found = any(
                re.search(pattern, normalized_query)
                for pattern in off_patterns
            )

            if on_found and not off_found:
                direction = "ON"
            elif off_found and not on_found:
                direction = "OFF"

        keywords_list = [
            keyword.strip().lower()
            for keyword in intent.keywords
            if keyword.strip()
        ]

        # The general NLP tokenizer splits "Wi-Fi" into "wi" + "fi".
        # Treat them as the single topic "wifi" for caching.
        if "wi" in keywords_list and "fi" in keywords_list:
            keywords_list = [
                keyword
                for keyword in keywords_list
                if keyword not in {"wi", "fi"}
            ]
            keywords_list.append("wifi")

        # Remove generic action wording.
        action_words = {
            "turn",
            "turned",
            "switch",
            "switched",
            "enable",
            "enabled",
            "activate",
            "activated",
            "disable",
            "disabled",
            "deactivate",
            "deactivated",
            "on",
            "off",
            "start",
            "started",
            "stop",
            "stopped",
            "make",
            "sure",
            "need",
            "needs",
            "be",
        }

        # Remove conversational/filler words that should not distinguish
        # paraphrases of the same troubleshooting intent.
        filler_words = {
            "my",
            "please",
            "will",
            "would",
            "can",
            "could",
            "the",
            "a",
            "an",
            "not",
        }

        keywords_list = [
            keyword
            for keyword in keywords_list
            if keyword not in action_words and keyword not in filler_words
        ]

        # Canonicalize common paraphrases.
        keywords_list = [
            self._canonicalize_keyword(keyword)
            for keyword in keywords_list
        ]

        # Samsung is usually brand context rather than the actual
        # troubleshooting intent, so don't let it reduce similarity.
        keywords_list = [
            keyword
            for keyword in keywords_list
            if keyword not in {"samsung"}
        ]

        keywords = frozenset(keywords_list)

        return normalized_query, direction, keywords

    @staticmethod
    def _similarity(
        query_direction: str,
        query_keywords: frozenset[str],
        entry_direction: str,
        entry_keywords: frozenset[str],
    ) -> float:
        """
        Calculate a conservative keyword similarity score.
        """

        # Only reject when BOTH directions are known and conflict.
        if (
            query_direction != "UNKNOWN"
            and entry_direction != "UNKNOWN"
            and query_direction != entry_direction
        ):
            return 0.0

        if not query_keywords or not entry_keywords:
            return 0.0

        intersection = query_keywords & entry_keywords
        union = query_keywords | entry_keywords

        return len(intersection) / len(union)

    def get(self, key: str) -> dict[str, Any] | None:
        normalized_key = key.strip().lower()

        if not normalized_key:
            return None

        query_text, context_signature = self._split_cache_key(
            normalized_key
        )

        # ---------------------------------------------------------
        # FAST PATH: exact lookup
        # ---------------------------------------------------------
        with self._lock:
            entry = self._entries.get(normalized_key)

            if entry is not None:
                self._hits += 1
                self._exact_hits += 1
                self._entries.move_to_end(normalized_key)
                return entry.response

        # ---------------------------------------------------------
        # PARAPHRASE PATH
        # ---------------------------------------------------------
        normalized_query, direction, keywords = self._build_signature(
            normalized_key
        )

        with self._lock:
            best_key: str | None = None
            best_score = 0.0

            for cache_key, entry in self._entries.items():

                # Never reuse an answer generated from different
                # SIIS troubleshooting evidence.
                if entry.context_signature != context_signature:
                    continue

                score = self._similarity(
                    query_direction=direction,
                    query_keywords=keywords,
                    entry_direction=entry.direction,
                    entry_keywords=entry.keywords,
                )

                if score > best_score:
                    best_score = score
                    best_key = cache_key

            if (
                best_key is not None
                and best_score >= self.PARAPHRASE_THRESHOLD
            ):
                matched_entry = self._entries[best_key]

                self._hits += 1
                self._paraphrase_hits += 1

                self._entries.move_to_end(best_key)

                return matched_entry.response

            self._misses += 1
            return None

    def put(
        self,
        key: str,
        response: dict[str, Any],
    ) -> None:
        normalized_key = key.strip().lower()

        if not normalized_key:
            return

        query_text, context_signature = self._split_cache_key(
            normalized_key
        )

        normalized_query, direction, keywords = self._build_signature(
            normalized_key
        )

        with self._lock:
            self._entries[normalized_key] = CacheEntry(
                response=response,
                normalized_query=normalized_query,
                direction=direction,
                keywords=keywords,
                context_signature=context_signature,
            )

            self._entries.move_to_end(normalized_key)

            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0
            self._exact_hits = 0
            self._paraphrase_hits = 0

    @property
    def hits(self) -> int:
        with self._lock:
            return self._hits

    @property
    def misses(self) -> int:
        with self._lock:
            return self._misses

    @property
    def hit_rate(self) -> float:
        with self._lock:
            total = self._hits + self._misses

            if total == 0:
                return 0.0

            return self._hits / total

    def stats(self) -> dict[str, float | int]:
        with self._lock:
            total = self._hits + self._misses

            return {
                "entries": len(self._entries),
                "hits": self._hits,
                "misses": self._misses,
                "exact_hits": self._exact_hits,
                "paraphrase_hits": self._paraphrase_hits,
                "hit_rate": (
                    self._hits / total
                    if total > 0
                    else 0.0
                ),
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)