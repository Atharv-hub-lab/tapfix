"""Configuration: file locations, input limits and (later) LLM settings.

Values come from environment variables, optionally loaded from a `.env` file.
Secrets (API keys) live ONLY in `.env`, which is git-ignored.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Dict, Tuple

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Input limits (we validate every request; see api_models.py).
# The longest article in Samsung's starter data is ~9,000 characters and the
# longest query ~250, so these leave generous headroom without allowing abuse.
MAX_QUERY_CHARS = 2_000
MAX_SIIS_CHARS = 50_000


def _env_overrides(cls, prefix: str) -> dict:
    """Read optional overrides such as TAPFIX_REL_MIN_SCORE=4.0 for a config dataclass."""
    found = {}
    for f in fields(cls):
        raw = os.getenv(f"{prefix}{f.name.upper()}")
        if raw is None or raw.strip() == "":
            continue
        default = f.default
        try:
            if isinstance(default, bool):
                found[f.name] = raw.strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(default, int):
                found[f.name] = int(raw)
            elif isinstance(default, float):
                found[f.name] = float(raw)
            elif isinstance(default, tuple):
                found[f.name] = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
            else:
                found[f.name] = raw
        except ValueError as exc:
            raise ValueError(f"bad value for {prefix}{f.name.upper()}: {raw!r}") from exc
    return found


@dataclass(frozen=True)
class RelevanceConfig:
    """Thresholds for the no-match gate (see app/relevance.py).

    IMPORTANT: these are INITIAL ENGINEERING thresholds. They were chosen by looking at a
    handful of examples and are NOT calibrated or optimal. They will be tuned on an
    evaluation dataset later. Override any of them with TAPFIX_REL_<NAME> environment variables.
    """

    min_score: float = 3.0  # BM25 score floor (a sanity floor only; scores are not comparable across queries)
    min_matched_terms: int = 2  # query words the top entry must share (capped by the entry's label length)
    min_query_coverage: float = 0.15  # share of the query's words found in the top entry
    min_label_coverage: float = 0.5  # share of the entry's label words found in the query
    min_margin_ratio: float = 0.02  # top must beat the best DIFFERENT setting by this fraction
    # A toggle (Enable/Disable) needs an explicit direction; otherwise the result is ambiguous.
    require_direction_for_toggles: bool = True
    # If the query says ON or OFF, entries that are not toggles ("View X", "Adjust X") cannot
    # do that, so they are rejected unless this is switched on.
    allow_non_toggle_for_directed_query: bool = False
    # Label words that carry no topic meaning (verbs the catalog puts in front of labels).
    label_ignored_terms: Tuple[str, ...] = ("enable", "disable", "view", "adjust", "check", "increase")

    @classmethod
    def from_env(cls) -> "RelevanceConfig":
        return cls(**_env_overrides(cls, "TAPFIX_REL_"))


@dataclass(frozen=True)
class ValidationConfig:
    """Field rules from Samsung's guide, kept configurable because Samsung's own sample
    output does not follow the guide's description length (it uses 9 and 12 words)."""

    title_min_words: int = 2
    title_max_words: int = 3
    description_min_words: int = 5
    description_max_words: int = 7
    description_prefix: str = "It will"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = PROJECT_ROOT / "data"
    log_level: str = "INFO"
    # LLM settings are read now so .env is set up early; used from Step 4 on.
    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: str = field(default="", repr=False)  # repr=False: never printed
    relevance: RelevanceConfig = field(default_factory=RelevanceConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)

    @property
    def deeplinks_path(self) -> Path:
        return self.data_dir / "deeplinks.json"

    @property
    def siis_path(self) -> Path:
        return self.data_dir / "siis_responses.json"

    @property
    def input_path(self) -> Path:
        return self.data_dir / "input.txt"

    @property
    def sample_output_path(self) -> Path:
        return self.data_dir / "sample_output.json"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env")  # does not override real env vars
        return cls(
            data_dir=Path(os.getenv("TAPFIX_DATA_DIR", str(PROJECT_ROOT / "data"))),
            log_level=os.getenv("TAPFIX_LOG_LEVEL", "INFO").upper(),
            llm_provider=os.getenv("LLM_PROVIDER", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            relevance=RelevanceConfig.from_env(),
        )

    def safe_dict(self) -> Dict[str, str]:
        """Settings for logging: the API key is masked."""
        return {
            "data_dir": str(self.data_dir),
            "log_level": self.log_level,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_api_key": "***set***" if self.llm_api_key else "(not set)",
        }
