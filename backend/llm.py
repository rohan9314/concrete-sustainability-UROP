"""OpenAI client for structured information extraction."""

import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from prompts import SYSTEM_PROMPT, build_extraction_prompt
from schema import RetrievalSummary, TechnologyEvaluation

load_dotenv()

# Paste your OpenAI API key in the .env file as OPENAI_API_KEY=your_key_here
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DEFAULT_MODEL = "gpt-4o-mini"


class MissingAPIKeyError(Exception):
    """Raised when OpenAI API key is not configured."""


class InvalidJSONError(Exception):
    """Raised when the LLM response cannot be parsed as JSON."""


class SchemaValidationError(Exception):
    """Raised when LLM output fails Pydantic validation."""


def validate_api_key() -> str:
    """Ensure OpenAI API key is present and not a placeholder."""
    if not OPENAI_API_KEY or OPENAI_API_KEY == "YOUR_OPENAI_TOKEN_HERE":
        raise MissingAPIKeyError(
            "OPENAI_API_KEY is missing or still set to the placeholder. "
            "Paste your OpenAI API key in research_agent/.env as "
            "OPENAI_API_KEY=your_key_here"
        )
    return OPENAI_API_KEY


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if the model wraps JSON in them."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json_response(raw: str) -> dict:
    """Parse JSON from the LLM response, with error handling."""
    cleaned = _strip_code_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise InvalidJSONError(
            f"OpenAI returned invalid JSON: {exc}\nResponse preview: {cleaned[:500]}"
        ) from exc


def _normalize_answers(
    data: dict,
    questions: list[str],
    technology_name: str,
    questions_file: str,
    retrieval_summary: RetrievalSummary,
) -> dict:
    """Ensure one answer per configured question, filling gaps when the LLM omits any."""
    raw_answers = data.get("answers") or []
    if not isinstance(raw_answers, list):
        raw_answers = []

    by_question: dict[str, dict] = {}
    unmatched: list[dict] = []

    for item in raw_answers:
        if not isinstance(item, dict):
            continue
        question_text = (item.get("question") or "").strip()
        if question_text and question_text not in by_question:
            by_question[question_text] = item
        else:
            unmatched.append(item)

    normalized_answers: list[dict] = []
    used_unmatched = 0

    for expected_question in questions:
        if expected_question in by_question:
            item = by_question[expected_question]
            item.setdefault("source_type_used", [])
            normalized_answers.append(item)
            continue

        if used_unmatched < len(unmatched):
            item = unmatched[used_unmatched]
            used_unmatched += 1
            item["question"] = expected_question
            item.setdefault("source_type_used", [])
            normalized_answers.append(item)
            continue

        normalized_answers.append(
            {
                "question": expected_question,
                "answer": "Not Found",
                "confidence": "Low",
                "source_type_used": [],
                "sources": [],
            }
        )

    technology = (data.get("technology") or technology_name).strip() or technology_name

    return {
        "technology": technology,
        "questions_file": questions_file,
        "executive_summary": "",
        "answers": normalized_answers,
        "retrieval_summary": retrieval_summary.model_dump(),
    }


def extract_technology_info(
    technology_name: str,
    all_sources: list[dict],
    questions: list[str],
    questions_file: str = "",
    retrieval_summary: RetrievalSummary | None = None,
    model: str = DEFAULT_MODEL,
) -> TechnologyEvaluation:
    """
    Send combined sources to OpenAI and return a validated TechnologyEvaluation.

    Raises MissingAPIKeyError, InvalidJSONError, or SchemaValidationError on failure.
    """
    api_key = validate_api_key()
    client = OpenAI(api_key=api_key)

    internet_count = sum(
        1 for source in all_sources if source.get("source_type") == "internet"
    )
    paper_count = sum(
        1 for source in all_sources if source.get("source_type") == "scientific_paper"
    )

    source_content = _format_sources_for_llm(all_sources)
    user_prompt = build_extraction_prompt(
        technology_name,
        source_content,
        questions,
        internet_count=internet_count,
        paper_count=paper_count,
    )

    summary = retrieval_summary or RetrievalSummary(
        internet_sources_found=internet_count,
        scientific_paper_sources_found=paper_count,
        edison_enabled=paper_count > 0,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        raise InvalidJSONError(f"OpenAI API call failed: {exc}") from exc

    raw_content = response.choices[0].message.content or ""
    if not raw_content.strip():
        raise InvalidJSONError("OpenAI returned an empty response.")

    data = _parse_json_response(raw_content)
    data = _normalize_answers(data, questions, technology_name, questions_file, summary)

    try:
        return TechnologyEvaluation.model_validate(data)
    except ValidationError as exc:
        raise SchemaValidationError(
            f"LLM output failed schema validation: {exc}"
        ) from exc


def _format_sources_for_llm(sources: list[dict]) -> str:
    """Format standardized sources for the LLM prompt."""
    from search import format_sources_for_llm

    return format_sources_for_llm(sources)
