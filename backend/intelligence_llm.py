"""OpenAI extraction for structured technology intelligence."""

from __future__ import annotations

import json

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from intelligence_normalize import normalize_intelligence
from intelligence_prompts import INTELLIGENCE_SYSTEM_PROMPT, build_intelligence_prompt
from llm import (
    DEFAULT_MODEL,
    InvalidJSONError,
    MissingAPIKeyError,
    SchemaValidationError,
    validate_api_key,
    _parse_json_response,
)
from schemas.technology_intelligence import ResearchFilters, TechnologyIntelligence

load_dotenv()


def extract_technology_intelligence(
    technology_name: str,
    all_sources: list[dict],
    *,
    filters: ResearchFilters | dict | None = None,
    model: str = DEFAULT_MODEL,
) -> TechnologyIntelligence:
    """Extract standardized technology intelligence JSON from retrieved sources."""
    api_key = validate_api_key()
    client = OpenAI(api_key=api_key)

    filter_model = (
        filters
        if isinstance(filters, ResearchFilters)
        else ResearchFilters.model_validate(filters or {})
    )

    internet_count = sum(
        1 for source in all_sources if source.get("source_type") == "internet"
    )
    paper_count = sum(
        1 for source in all_sources if source.get("source_type") == "scientific_paper"
    )

    from search import format_sources_for_llm

    source_content = format_sources_for_llm(all_sources)
    user_prompt = build_intelligence_prompt(
        technology_name,
        source_content,
        internet_count=internet_count,
        paper_count=paper_count,
        main_category=filter_model.main_category,
        ccs_subcategory=filter_model.ccs_subcategory,
        company_name=filter_model.company_name,
        project_stage=filter_model.project_stage,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": INTELLIGENCE_SYSTEM_PROMPT},
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
    intelligence = normalize_intelligence(
        data,
        technology_name=technology_name,
        filter_hints=filter_model.model_dump(),
    )

    try:
        return TechnologyIntelligence.model_validate(intelligence.model_dump())
    except ValidationError as exc:
        raise SchemaValidationError(
            f"Intelligence output failed schema validation: {exc}"
        ) from exc


def intelligence_to_summary_context(intelligence: TechnologyIntelligence) -> str:
    """Serialize intelligence for executive summary generation."""
    return json.dumps(intelligence.model_dump(), indent=2)
