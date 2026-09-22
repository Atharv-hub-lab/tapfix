from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod

from app.llm.solution import SolutionDraft


class SolutionProvider(ABC):
    @abstractmethod
    def solve(
        self,
        query: str,
        context: str,
    ) -> SolutionDraft:
        ...


def _extract_sections(
    context: str,
) -> tuple[str, list[dict[str, str]]]:
    """Extract SIIS evidence and catalog candidates from orchestrator context."""

    siis_match = re.search(
        r"SIIS TROUBLESHOOTING EVIDENCE:\s*"
        r"title=(.*?)\n"
        r"content=(.*?)\n\n"
        r"CATALOG CANDIDATES:",
        context,
        flags=re.DOTALL,
    )

    siis_text = ""

    if siis_match:
        siis_text = (
            f"title={siis_match.group(1).strip()}\n"
            f"content={siis_match.group(2).strip()}"
        )

    candidates: list[dict[str, str]] = []

    catalog_marker = "CATALOG CANDIDATES:"

    if catalog_marker in context:
        # SIIS is present.
        # Only parse candidates after the catalog section marker.
        candidate_section = context.split(
            catalog_marker,
            1,
        )[1]
    else:
        # No SIIS was supplied.
        # In this case the entire context is the catalog section.
        candidate_section = context

    pattern = re.compile(
        r"Candidate\s+(\d+):\s*"
        r"id=([^;]+);\s*"
        r"description=([^;]+);\s*"
        r"message=([^;]+);\s*"
        r"qna_description=(.*)"
    )

    for line in candidate_section.splitlines():
        line = line.strip()

        match = pattern.fullmatch(line)

        if not match:
            continue

        candidates.append(
            {
                "number": match.group(1).strip(),
                "id": match.group(2).strip(),
                "description": match.group(3).strip(),
                "message": match.group(4).strip(),
                "qna_description": match.group(5).strip(),
            }
        )

    return siis_text, candidates


def _words(text: str) -> set[str]:
    text = re.sub(
        r"\bwi[\s-]?fi\b",
        "wifi",
        text,
        flags=re.IGNORECASE,
    )

    return {
        word.lower()
        for word in re.findall(r"[A-Za-z0-9]+", text)
        if len(word) >= 4
    }


def _select_siis_supported_candidate(
    siis_text: str,
    candidates: list[dict[str, str]],
) -> dict[str, str] | None:
    if not siis_text.strip():
        return None

    title_text = ""
    content_text = siis_text

    for line in siis_text.splitlines():
        stripped = line.strip()

        if stripped.startswith("title="):
            title_text = stripped[len("title="):].strip()

        elif stripped.startswith("content="):
            content_text = stripped[len("content="):].strip()

    if not title_text:
        return None

    title_words = _words(title_text)

    generic_words = {
        "device",
        "phone",
        "phones",
        "tablet",
        "tablets",
        "screen",
        "screens",
        "settings",
        "setting",
        "display",
        "mode",
        "page",
        "pages",
        "open",
        "opens",
        "access",
        "user",
        "users",
        "samsung",
        "mobile",
        "system",
        "option",
        "options",
        "section",
        "sections",
        "menu",
        "menus",
        "problem",
        "issue",
        "issues",
        "check",
        "checking",
        "information",
        "details",
    }

    title_specific_words = title_words - generic_words

    if not title_specific_words:
        return None

    best_candidate: dict[str, str] | None = None
    best_score = 0

    for candidate in candidates:
        catalog_text = " ".join(
            (
                candidate["description"],
                candidate["message"],
                candidate["qna_description"],
            )
        )

        candidate_words = _words(catalog_text)
        candidate_specific_words = candidate_words - generic_words

        title_overlap = (
            title_specific_words
            & candidate_specific_words
        )

        # Require at least two meaningful title matches.
        if len(title_overlap) < 2:
            continue

        score = len(title_overlap)

        content_words = (
            _words(content_text)
            - generic_words
        )

        content_overlap = (
            content_words
            & candidate_specific_words
        )

        score += min(
            len(content_overlap),
            2,
        )

        if score > best_score:
            best_score = score
            best_candidate = candidate

    return best_candidate


def _extract_siis_steps(
    siis_text: str,
) -> tuple[str, ...]:
    content = siis_text

    for line in siis_text.splitlines():
        stripped = line.strip()

        if stripped.startswith("content="):
            content = stripped[len("content="):].strip()

    text = " ".join(content.split())

    if not text:
        return (
            "Follow the troubleshooting guidance provided.",
        )

    sentences = [
        sentence.strip(" .")
        for sentence in re.split(
            r"(?<=[.!?])\s+",
            text,
        )
        if sentence.strip()
    ]

    action_starters = (
        "check ",
        "inspect ",
        "verify ",
        "ensure ",
        "confirm ",
        "try ",
        "restart ",
        "force restart ",
        "charge ",
        "connect ",
        "disconnect ",
        "open ",
        "close ",
        "turn ",
        "switch ",
        "enable ",
        "disable ",
        "remove ",
        "insert ",
        "press ",
        "tap ",
        "select ",
        "go to ",
        "look for ",
        "make sure ",
    )

    steps: list[str] = []

    for sentence in sentences:
        clean_sentence = sentence.strip(" .")

        if not clean_sentence:
            continue

        lower = clean_sentence.lower()

        if lower.startswith(action_starters):
            steps.append(
                clean_sentence + "."
            )

    if steps:
        return tuple(
            dict.fromkeys(steps)
        )

    return (
        "Follow the troubleshooting guidance provided.",
    )


class DeterministicSolutionProvider(SolutionProvider):
    def solve(
        self,
        query: str,
        context: str,
    ) -> SolutionDraft:
        if not query.strip():
            raise ValueError("query must not be blank")

        if not context.strip():
            raise ValueError("context must not be blank")

        siis_text, candidates = _extract_sections(context)

        if not candidates:
            if siis_text.strip():
                steps = _extract_siis_steps(
                    siis_text
                )

                return SolutionDraft(
                    goal=(
                        "Follow these steps to perform this "
                        "Device Troubleshooting"
                    ),
                    title="Device troubleshooting",
                    score=0.75,
                    action_name="Restart Device",
                    description=(
                        "It will guide you through troubleshooting steps."
                    ),
                    category="manual",
                    steps=steps,
                    catalog_id=None,
                )

            raise ValueError(
                "No catalog candidate available"
            )

        if siis_text.strip():
            selected = _select_siis_supported_candidate(
                siis_text,
                candidates,
            )

            if selected is None:
                steps = _extract_siis_steps(
                    siis_text
                )

                return SolutionDraft(
                    goal=(
                        "Follow these steps to perform this "
                        "Device Troubleshooting"
                    ),
                    title="Device troubleshooting",
                    score=0.75,
                    action_name="Restart Device",
                    description=(
                        "It will guide you through troubleshooting steps."
                    ),
                    category="manual",
                    steps=steps,
                    catalog_id=None,
                )
        else:
            selected = candidates[0]

        catalog_id = selected["id"]
        catalog_description = selected["description"]
        message = selected["message"]

        action_name = (
            message
            or catalog_description
        )

        return SolutionDraft(
            goal=(
                "Follow these steps to perform this "
                "Device Troubleshooting"
            ),
            title="Device troubleshooting",
            score=0.75,
            action_name=action_name,
            description=(
                "It will open the relevant Settings screen."
            ),
            category="auto",
            steps=(
                f"Open Settings to {action_name.lower()}.",
            ),
            catalog_id=catalog_id,
        )


class FallbackSolutionProvider(SolutionProvider):
    def __init__(
        self,
        primary: SolutionProvider,
        fallback: SolutionProvider,
    ):
        self._primary = primary
        self._fallback = fallback

        # After a Gemini failure, temporarily use the
        # deterministic fallback instead of repeatedly
        # calling Gemini.
        self._gemini_cooldown_until = 0.0

        # Keep the cooldown short so the system can
        # recover automatically.
        self._cooldown_seconds = 60.0

    def solve(
        self,
        query: str,
        context: str,
    ) -> SolutionDraft:
        now = time.monotonic()

        # Gemini recently failed.
        # Skip another remote request and immediately
        # use the deterministic fallback.
        if now < self._gemini_cooldown_until:
            print(
                "[INFO] Gemini cooldown active; "
                "using deterministic fallback."
            )

            return self._fallback.solve(
                query,
                context,
            )

        try:
            result = self._primary.solve(
                query,
                context,
            )

            print("[DEBUG] Stage 2 Gemini result:")
            print(result)

            return result

        except Exception as exc:
            print(
                f"[WARN] Gemini Stage 2 failed: "
                f"{type(exc).__name__}: {exc}"
            )

            # Start a temporary cooldown after
            # the Gemini failure.
            self._gemini_cooldown_until = (
                time.monotonic()
                + self._cooldown_seconds
            )

            fallback_result = self._fallback.solve(
                query,
                context,
            )

            print(
                "[DEBUG] Stage 2 FALLBACK result:",
                fallback_result,
            )

            return fallback_result  