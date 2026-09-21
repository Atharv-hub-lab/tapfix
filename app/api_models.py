"""API request models. Every request is validated before any processing.

Response models are added in a later step, once the pipeline exists and the
open question about where `fallback` metadata goes has been settled.
"""
from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, Field, field_validator

from app.config import MAX_QUERY_CHARS, MAX_SIIS_CHARS


class SiisArticle(BaseModel):
    """The object form of siis_response found in Samsung's starter data."""

    title: str = Field(default="", max_length=1_000)
    content: str = Field(min_length=1, max_length=MAX_SIIS_CHARS)


class TroubleshootRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    # Accept BOTH forms: raw text (the guide's example) or {title, content}
    # (what the starter data actually contains).
    siis_response: Optional[Union[str, SiisArticle]] = None

    @field_validator("query")
    @classmethod
    def _query_must_have_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value

    @field_validator("siis_response")
    @classmethod
    def _limit_and_clean_siis(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if len(value) > MAX_SIIS_CHARS:
                raise ValueError(f"siis_response is longer than {MAX_SIIS_CHARS} characters")
            # An empty string is treated the same as "omitted".
            return value or None
        return value
