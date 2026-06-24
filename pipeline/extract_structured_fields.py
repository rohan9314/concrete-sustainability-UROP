"""Stage 4: LLM structured extraction on screened, ranked sources (Stage 2)."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv

from openai_flex import call_openai_flex  # noqa: E402
from llm import DEFAULT_MODEL, _parse_json_response  # noqa: E402
from pipeline.config import get_extraction_concurrency
from pipeline.schema import (
    DEPLOYMENT_STAGES,
    NOT_REPORTED,
    PERFORMANCE_METRIC_TAGS,
    TECHNOLOGY_CATEGORIES,
    ProjectRef,
    RankedPaper,
    RelevantSource,
    TechnologyRecord,
    finalize_record,
)

load_dotenv()
logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = "technology_record_v1"

EXTRACTION_SYSTEM_PROMPT = f"""You extract structured technology intelligence from ONE scientific paper about cement/concrete decarbonization.

Rules:
- Return valid JSON only.
- Use predefined categories and deployment stages only.
- Use "Not Reported" when evidence is insufficient. Never guess.
- performance_metrics must use only these tags: {json.dumps(PERFORMANCE_METRIC_TAGS)}
- technology_category must be one of: {json.dumps(TECHNOLOGY_CATEGORIES)}
- deployment_stage must be one of: {json.dumps(DEPLOYMENT_STAGES)}
- confidence_by_field values must be High, Medium, Low, or Not Reported.
- Include source_provenance mapping field names to ["{NOT_REPORTED}"] or paper id list.
- pilot_projects and demonstration_projects are lists of objects with name, description, source_ids.

Return JSON matching the TechnologyRecord schema fields (without record_id, missing_fields, coverage_score).
"""


@dataclass
class ExtractionOptions:
    technology_hint: str = ""
    model: str = DEFAULT_MODEL
    prompt_version: str = EXTRACTION_PROMPT_VERSION
    use_cache: bool = True


@dataclass
class ExtractionResult:
    paper_id: str
    success: bool
    record: TechnologyRecord | None = None
    error: str | None = None


def _paper_to_prompt(paper: RankedPaper) -> str:
    authors = ", ".join(paper.authors[:8]) if paper.authors else "Not Reported"
    parts = [
        f"Paper ID: {paper.paper_id}",
        f"Title: {paper.title}",
        f"Authors: {authors}",
        f"Year: {paper.year}",
        f"DOI: {paper.doi or 'Not Reported'}",
        f"URL: {paper.url or 'Not Reported'}",
        "",
        f"Abstract:\n{paper.abstract or 'Not Reported'}",
    ]
    if paper.text and paper.text.strip() and paper.text.strip() != paper.abstract.strip():
        parts.extend(["", f"Full text (post-screening only):\n{paper.text}"])
    return "\n".join(parts)


def extract_technology_record(
    source: RankedPaper,
    options: ExtractionOptions | None = None,
) -> ExtractionResult:
    """
    Extract a TechnologyRecord from one ranked paper.

    Reusable by the offline pipeline, run_batch.py shards, and distributed workers.
    """
    opts = options or ExtractionOptions()
    user_prompt = (
        f"Technology hint: {opts.technology_hint or 'infer from paper'}\n\n"
        f"SOURCE:\n{_paper_to_prompt(source)}"
    )

    try:
        raw = call_openai_flex(
            model=opts.model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        data = _parse_json_response(raw)

        if not data.get("technology_name") or data.get("technology_name") == NOT_REPORTED:
            data["technology_name"] = opts.technology_hint or source.title[:120] or "Unknown"

        data.setdefault("relevant_sources", [])
        if not data["relevant_sources"]:
            data["relevant_sources"] = [
                {
                    "paper_id": source.paper_id,
                    "title": source.title,
                    "url": source.url,
                    "doi": source.doi,
                    "year": source.year,
                    "snippet": source.snippet,
                },
            ]

        record = TechnologyRecord.model_validate(data)
        record = finalize_record(record)
        return ExtractionResult(paper_id=source.paper_id, success=True, record=record)
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        logger.warning("extract_technology_record failed for %s: %s", source.paper_id, message)
        return ExtractionResult(paper_id=source.paper_id, success=False, error=message)


def extract_technology_records_parallel(
    papers: list[RankedPaper],
    *,
    options: ExtractionOptions | None = None,
    concurrency: int | None = None,
) -> list[ExtractionResult]:
    """Run bounded parallel extraction; failures are captured per paper."""
    from concurrency import run_parallel_ordered  # noqa: E402

    opts = options or ExtractionOptions()
    limit = concurrency or get_extraction_concurrency()

    def worker(paper: RankedPaper) -> ExtractionResult:
        return extract_technology_record(paper, opts)

    parallel = run_parallel_ordered(
        papers,
        worker,
        concurrency=limit,
        label="technology_record_extraction",
    )

    results: list[ExtractionResult] = []
    for item in parallel:
        if item.success and item.value is not None:
            results.append(item.value)
        else:
            paper = papers[item.index]
            results.append(
                ExtractionResult(
                    paper_id=paper.paper_id,
                    success=False,
                    error=item.error or "Extraction failed",
                ),
            )
    return results
