"""Per-source extraction workers and aggregation for the research pipeline.

Each worker is independent enough to be reused by:
- the live FastAPI request handler (bounded concurrency)
- scripts/process_batch.py (corpus slices for parallel batch workers)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from dotenv import load_dotenv
from openai import OpenAI

from extraction_cache import PROMPT_VERSION, read_cached_extraction, write_cached_extraction
from intelligence_normalize import normalize_intelligence
from intelligence_prompts import INTELLIGENCE_SYSTEM_PROMPT
from llm import DEFAULT_MODEL, _parse_json_response, validate_api_key
from schemas.technology_intelligence import ResearchFilters, TechnologyIntelligence
from search import _format_single_source_for_llm

load_dotenv()
logger = logging.getLogger(__name__)

SOURCE_EXTRACTION_PROMPT = """Extract structured facts about the target technology from ONE source document.

Rules:
- Return valid JSON only.
- Use null, [], or "Not Reported" when information is absent.
- Never invent numbers or organizations.
- Prefer short strings and lists; no long prose.
- Only include facts explicitly supported by this source.

Return JSON with keys:
technology_overview (partial), metrics, companies, pilot_demonstration_projects,
evidence_sources, missing_fields, warnings
"""


@dataclass
class SourceExtractionOptions:
    technology_name: str
    filters: ResearchFilters = field(default_factory=ResearchFilters)
    model: str = DEFAULT_MODEL
    prompt_version: str = PROMPT_VERSION
    question_set: str = "structured_intelligence"
    use_cache: bool = True


@dataclass
class SourceExtractionResult:
    source_id: str
    source_index: int
    source: dict
    success: bool
    partial: dict | None = None
    error: str | None = None


def source_identifier(source: dict) -> str:
    metadata = source.get("metadata") or {}
    doi = str(metadata.get("doi") or "").strip()
    if doi:
        return f"doi:{doi}"
    url = str(source.get("url") or "").strip().lower()
    if url:
        return f"url:{url}"
    title = str(source.get("title") or "").strip().lower()
    return f"title:{title or 'unknown'}"


def extract_from_source(
    source: dict,
    options: SourceExtractionOptions,
    *,
    source_index: int = 0,
) -> SourceExtractionResult:
    """
    Extract structured partial intelligence from a single source.

    Designed as a reusable worker for web requests and large-scale batch jobs.
    """
    source_id = source_identifier(source)

    if options.use_cache:
        cached = read_cached_extraction(
            source_id=source_id,
            technology_name=options.technology_name,
            model=options.model,
            question_set=options.question_set,
            prompt_version=options.prompt_version,
        )
        if cached is not None:
            return SourceExtractionResult(
                source_id=source_id,
                source_index=source_index,
                source=source,
                success=True,
                partial=cached,
            )

    body = _format_single_source_for_llm(
        source,
        1,
        origin=str(source.get("source_type") or "source"),
    )
    user_prompt = (
        f"Technology: {options.technology_name}\n"
        f"Main category hint: {options.filters.main_category}\n"
        f"CCS subcategory hint: {options.filters.ccs_subcategory}\n\n"
        f"SOURCE:\n{body}"
    )

    try:
        client = OpenAI(api_key=validate_api_key())
        response = client.chat.completions.create(
            model=options.model,
            messages=[
                {"role": "system", "content": SOURCE_EXTRACTION_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        partial = _parse_json_response(raw)

        if options.use_cache:
            write_cached_extraction(
                source_id=source_id,
                technology_name=options.technology_name,
                model=options.model,
                payload=partial,
                question_set=options.question_set,
                prompt_version=options.prompt_version,
            )

        return SourceExtractionResult(
            source_id=source_id,
            source_index=source_index,
            source=source,
            success=True,
            partial=partial,
        )
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        logger.warning("extract_from_source failed for %s: %s", source_id, message)
        return SourceExtractionResult(
            source_id=source_id,
            source_index=source_index,
            source=source,
            success=False,
            error=message,
        )


def _extend_unique_strings(target: list[str], values: object) -> None:
    if not values:
        return
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return
    seen = {item.lower() for item in target}
    for value in values:
        text = str(value).strip()
        if not text or text.lower() in seen or text == "Not Reported":
            continue
        target.append(text)
        seen.add(text.lower())


def _extend_unique_dicts(target: list[dict], values: object, key: str) -> None:
    if not isinstance(values, list):
        return
    seen = {
        str(item.get(key) or "").strip().lower()
        for item in target
        if isinstance(item, dict)
    }
    for item in values:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get(key) or "").strip().lower()
        if not identifier or identifier in seen:
            continue
        target.append(item)
        seen.add(identifier)


def aggregate_source_extractions(
    results: list[SourceExtractionResult],
    *,
    technology_name: str,
    filters: ResearchFilters | None = None,
) -> tuple[TechnologyIntelligence, list[str]]:
    """Merge ordered per-source partials into one TechnologyIntelligence object."""
    filter_model = filters or ResearchFilters()
    merged: dict = {
        "technology_overview": {},
        "metrics": [],
        "companies": [],
        "pilot_demonstration_projects": [],
        "evidence_sources": [],
        "missing_fields": [],
        "warnings": [],
    }

    extraction_errors: list[str] = []

    for result in sorted(results, key=lambda item: item.source_index):
        if not result.success or not result.partial:
            if result.error:
                extraction_errors.append(f"{result.source_id}: {result.error}")
            continue

        partial = result.partial
        overview = partial.get("technology_overview")
        if isinstance(overview, dict):
            for key, value in overview.items():
                if key not in merged["technology_overview"] and value not in (
                    None,
                    "",
                    [],
                    "Not Reported",
                ):
                    merged["technology_overview"][key] = value

        _extend_unique_dicts(merged["metrics"], partial.get("metrics"), "metric_name")
        _extend_unique_dicts(merged["companies"], partial.get("companies"), "name")
        _extend_unique_dicts(
            merged["pilot_demonstration_projects"],
            partial.get("pilot_demonstration_projects"),
            "project_name",
        )
        _extend_unique_dicts(
            merged["evidence_sources"],
            partial.get("evidence_sources"),
            "title",
        )
        _extend_unique_strings(merged["missing_fields"], partial.get("missing_fields"))
        _extend_unique_strings(merged["warnings"], partial.get("warnings"))

    if extraction_errors:
        merged["warnings"].append(
            f"{len(extraction_errors)} source(s) failed extraction; partial results used."
        )

    intelligence = normalize_intelligence(
        merged,
        technology_name=technology_name,
        filter_hints=filter_model.model_dump(),
    )
    return TechnologyIntelligence.model_validate(intelligence.model_dump()), extraction_errors


def consolidate_intelligence_from_partials(
    intelligence: TechnologyIntelligence,
    *,
    technology_name: str,
    filters: ResearchFilters | None = None,
    model: str = DEFAULT_MODEL,
) -> TechnologyIntelligence:
    """
    Optional consolidation pass over merged partials.

    Keeps the live website responsive while improving coherence when many sources
    were processed in parallel.
    """
    filter_model = filters or ResearchFilters()
    user_prompt = (
        f"Technology: {technology_name}\n"
        f"Filters: {json.dumps(filter_model.model_dump())}\n\n"
        f"Merged partial extraction JSON:\n"
        f"{json.dumps(intelligence.model_dump(), indent=2)}\n\n"
        "Return one consolidated JSON object using the same schema. "
        "Resolve duplicates, keep only supported facts, and preserve lists."
    )

    client = OpenAI(api_key=validate_api_key())
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": INTELLIGENCE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or ""
    data = _parse_json_response(raw)
    normalized = normalize_intelligence(
        data,
        technology_name=technology_name,
        filter_hints=filter_model.model_dump(),
    )
    return TechnologyIntelligence.model_validate(normalized.model_dump())
