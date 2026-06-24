"""Lightweight LLM helpers for offline pipeline stages (no backend retrieval stack)."""

from __future__ import annotations

import json
import os
import re

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


class InvalidJSONError(Exception):
    """Raised when an LLM response cannot be parsed as JSON."""


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if the model wraps JSON in them."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced {...} substring, if any."""
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _parse_json_response(raw: str) -> dict:
    """
    Parse JSON from an LLM response.

    Handles plain JSON, ```json fences, and extra prose before/after the object.
    """
    cleaned = _strip_code_fences(raw)
    candidates = [cleaned]
    extracted = _extract_json_object(cleaned)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    preview = cleaned[:500]
    message = str(last_error) if last_error else "no JSON object found"
    raise InvalidJSONError(f"OpenAI returned invalid JSON: {message}\nResponse preview: {preview}")
