from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from app.llm.parsing import parse_query_intent
from app.llm.provider import LLMProvider
from app.nlp.query import QueryIntent


_QUERY_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "original_query": {
            "type": "string",
            "description": "The user's original troubleshooting query.",
        },
        "normalized_query": {
            "type": "string",
            "description": "A concise technical interpretation of the query.",
        },
        "direction": {
            "type": "string",
            "enum": ["ON", "OFF", "UNKNOWN"],
            "description": "The requested setting direction.",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Useful technical retrieval keywords.",
        },
    },
    "required": [
        "original_query",
        "normalized_query",
        "direction",
        "keywords",
    ],
}


_SYSTEM_INSTRUCTION = """
You are the query-understanding component of TapFix,
a Samsung smart troubleshooting engine.

Your ONLY job is to understand and normalize the user's
troubleshooting complaint.

Return:
- original_query
- normalized_query
- direction
- keywords

Rules:
1. Do not invent Samsung Settings deeplinks.
2. Do not return URLs.
3. Do not return catalog IDs.
4. Do not invent troubleshooting steps.
5. Do not assume ON or OFF when the user's intent is unclear.
6. Preserve the user's actual troubleshooting intent.
7. If the direction is unclear, use UNKNOWN.
8. Keep normalized_query concise and technically useful.
9. Keywords must be useful for catalog retrieval.
"""


class GeminiProvider(LLMProvider):
    """Gemini-backed query-understanding provider."""

    def __init__(
        self,
        api_key: str,
        model: str,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Gemini API key must not be blank")

        if not model.strip():
            raise ValueError("Gemini model must not be blank")

        self._model = model
        self._client = client or genai.Client(api_key=api_key)

    def understand(self, query: str) -> QueryIntent:
        if not query.strip():
            raise ValueError("query must not be blank")

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=query,
               config=types.GenerateContentConfig(
    system_instruction=_SYSTEM_INSTRUCTION,
    response_mime_type="application/json",
    response_schema=_QUERY_INTENT_SCHEMA,
), 
            )
        except Exception as exc:
            raise RuntimeError("Gemini request failed") from exc

        text = getattr(response, "text", None)

        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Gemini returned an empty response")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Gemini returned invalid JSON") from exc

        try:
            return parse_query_intent(payload)
        except ValueError as exc:
            raise RuntimeError("Gemini returned invalid query intent") from exc