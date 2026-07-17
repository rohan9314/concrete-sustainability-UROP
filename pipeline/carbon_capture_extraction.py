"""Literature and web extraction for carbon capture methodologies."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field

from pipeline.carbon_capture_config import CarbonCaptureMethodology
from pipeline.carbon_capture_prompts import (
    SYSTEM_PROMPT,
    build_literature_extraction_prompt,
    build_web_extraction_prompt,
)
from pipeline.carbon_capture_schema import (
    NA,
    ValidationStats,
    empty_canonical_row,
    expand_llm_payload,
    validate_and_normalize_row,
)
from pipeline.concurrency import run_parallel_ordered
from pipeline.config import get_extraction_concurrency
from pipeline.llm_utils import DEFAULT_MODEL, InvalidJSONError, _parse_json_response
from pipeline.openai_client import call_openai
from pipeline.schema import RankedPaper

logger = logging.getLogger(__name__)


@dataclass
class CarbonCaptureRow:
    """One canonical output row plus pipeline metadata."""

    record_id: str
    result_id: str
    methodology_slug: str
    methodology_display: str
    source_origin: str
    paper_id: str = ""
    rank_score: float = 0.0
    extraction_error: str = ""
    category: str = NA
    subcategory: str = NA
    technology_type: str = NA
    company_or_organization: str = NA
    project_name: str = NA
    project_year: str = NA
    project_location: str = NA
    deployment_stage: str = NA
    metric_dimension: str = NA
    metric_name: str = NA
    metric_value: str = NA
    metric_unit: str = NA
    metric_boundary: str = NA
    co2_reduction: str = NA
    energy_impact: str = NA
    cost_impact: str = NA
    primary_barriers: str = NA
    source_type: str = NA
    source_title: str = NA
    source_url_or_citation: str = NA
    confidence: str = NA
    notes: str = NA

    def to_canonical_dict(self) -> dict[str, str]:
        return {field: str(getattr(self, field)) for field in (
            "category",
            "subcategory",
            "technology_type",
            "company_or_organization",
            "project_name",
            "project_year",
            "project_location",
            "deployment_stage",
            "metric_dimension",
            "metric_name",
            "metric_value",
            "metric_unit",
            "metric_boundary",
            "co2_reduction",
            "energy_impact",
            "cost_impact",
            "primary_barriers",
            "source_type",
            "source_title",
            "source_url_or_citation",
            "confidence",
            "notes",
        )}

    def to_dict(self) -> dict:
        return asdict(self)


def ranked_paper_to_source(paper: RankedPaper) -> dict:
    url = paper.url
    if not url and paper.doi:
        url = f"https://doi.org/{paper.doi}"
    body = paper.text or paper.abstract or paper.snippet
    return {
        "source_type": "Literature",
        "title": paper.title,
        "url": url,
        "snippet": paper.snippet or (paper.abstract[:500] if paper.abstract else ""),
        "full_text": body,
        "metadata": {
            "authors": paper.authors,
            "year": paper.year,
            "journal": "",
            "doi": paper.doi,
        },
        "paper_id": paper.paper_id,
    }


def format_literature_source_for_llm(source: dict) -> str:
    metadata = source.get("metadata") or {}
    body = source.get("full_text") or source.get("snippet") or "No content available."
    meta_lines: list[str] = []
    authors = metadata.get("authors") or []
    if authors:
        meta_lines.append(f"Authors: {', '.join(authors)}")
    if metadata.get("year"):
        meta_lines.append(f"Year: {metadata['year']}")
    if metadata.get("journal"):
        meta_lines.append(f"Journal: {metadata['journal']}")
    if metadata.get("doi"):
        meta_lines.append(f"DOI: {metadata['doi']}")
    if source.get("paper_id"):
        meta_lines.append(f"Paper ID: {source['paper_id']}")

    metadata_block = "\n".join(meta_lines)
    if metadata_block:
        metadata_block = f"{metadata_block}\n"

    return (
        f"Title: {source.get('title', '')}\n"
        f"URL: {source.get('url', '')}\n"
        f"Source Type: Literature\n"
        f"{metadata_block}"
        f"Content:\n{body}\n"
    )


def format_web_source_for_llm(source: dict) -> str:
    body = source.get("full_text") or source.get("snippet") or source.get("content") or ""
    return (
        f"Title: {source.get('title', '')}\n"
        f"URL: {source.get('url', '')}\n"
        f"Source Type: Web\n"
        f"Content:\n{body}\n"
    )


def _call_extraction_llm(*, prompt: str, model: str) -> dict:
    raw = call_openai(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return _parse_json_response(raw)


def _rows_from_payload(
    *,
    payload: dict,
    methodology: CarbonCaptureMethodology,
    source_origin: str,
    result_id: str,
    paper: RankedPaper | None,
    stats: ValidationStats,
) -> list[CarbonCaptureRow]:
    canonical_rows = expand_llm_payload(payload, stats=stats)
    if not canonical_rows:
        fallback = empty_canonical_row()
        fallback["source_type"] = "Literature" if source_origin == "literature" else "Web"
        fallback["category"] = methodology.category
        fallback["subcategory"] = methodology.subcategory
        if paper is not None:
            fallback["source_title"] = paper.title
            fallback["source_url_or_citation"] = paper.url or (
                f"https://doi.org/{paper.doi}" if paper.doi else NA
            )
        canonical_rows = [validate_and_normalize_row(fallback, stats=stats)]

    rows: list[CarbonCaptureRow] = []
    for index, canonical in enumerate(canonical_rows):
        if canonical.get("category") == NA:
            canonical["category"] = methodology.category
        if canonical.get("subcategory") == NA:
            canonical["subcategory"] = methodology.subcategory
        if paper is not None:
            if canonical.get("source_title") == NA:
                canonical["source_title"] = paper.title
            if canonical.get("source_url_or_citation") == NA:
                canonical["source_url_or_citation"] = paper.url or (
                    f"https://doi.org/{paper.doi}" if paper.doi else NA
                )
            if canonical.get("source_type") == NA:
                canonical["source_type"] = "Literature"

        row = CarbonCaptureRow(
            record_id=f"{result_id}:{index}",
            result_id=result_id,
            methodology_slug=methodology.slug,
            methodology_display=methodology.display_name,
            source_origin=source_origin,
            paper_id=paper.paper_id if paper else "",
            rank_score=paper.rank_score if paper else 0.0,
            **canonical,
        )
        rows.append(row)
    return rows


def _error_row(
    *,
    methodology: CarbonCaptureMethodology,
    source_origin: str,
    result_id: str,
    paper: RankedPaper | None,
    message: str,
    source_title: str | None = None,
    source_url: str | None = None,
) -> CarbonCaptureRow:
    if source_title is None:
        source_title = paper.title if paper else NA
    if source_url is None:
        if paper is None:
            source_url = NA
        else:
            source_url = paper.url or (f"https://doi.org/{paper.doi}" if paper.doi else NA)
    row = CarbonCaptureRow(
        record_id=f"{result_id}:0",
        result_id=result_id,
        methodology_slug=methodology.slug,
        methodology_display=methodology.display_name,
        source_origin=source_origin,
        paper_id=paper.paper_id if paper else "",
        rank_score=paper.rank_score if paper else 0.0,
        category=methodology.category,
        subcategory=methodology.subcategory,
        source_type="Literature" if source_origin == "literature" else "Web",
        source_title=source_title,
        source_url_or_citation=source_url,
        confidence=NA,
        extraction_error=message,
    )
    return row


def extract_literature_from_paper(
    paper: RankedPaper,
    methodology: CarbonCaptureMethodology,
    *,
    model: str = DEFAULT_MODEL,
    stats: ValidationStats | None = None,
) -> list[CarbonCaptureRow]:
    """Extract canonical rows from one ranked literature source."""
    local_stats = stats or ValidationStats()
    result_id = f"{methodology.slug}:{paper.paper_id}"
    source = ranked_paper_to_source(paper)
    prompt = build_literature_extraction_prompt(
        methodology_name=methodology.display_name,
        methodology_subcategory=methodology.subcategory,
        source_content=format_literature_source_for_llm(source),
    )
    try:
        payload = _call_extraction_llm(prompt=prompt, model=model)
        return _rows_from_payload(
            payload=payload,
            methodology=methodology,
            source_origin="literature",
            result_id=result_id,
            paper=paper,
            stats=local_stats,
        )
    except (InvalidJSONError, Exception) as exc:
        message = str(exc) or exc.__class__.__name__
        logger.warning(
            "Literature extraction failed for %s (%s): %s",
            paper.paper_id,
            methodology.slug,
            message,
        )
        return [
            _error_row(
                methodology=methodology,
                source_origin="literature",
                result_id=result_id,
                paper=paper,
                message=message,
            ),
        ]


def extract_web_from_source(
    source: dict,
    methodology: CarbonCaptureMethodology,
    *,
    model: str = DEFAULT_MODEL,
    stats: ValidationStats | None = None,
) -> list[CarbonCaptureRow]:
    """Extract canonical rows from one web source."""
    local_stats = stats or ValidationStats()
    url = str(source.get("url") or "").strip()
    result_id = f"{methodology.slug}:web:{uuid.uuid5(uuid.NAMESPACE_URL, url or str(source.get('title'))).hex[:12]}"
    prompt = build_web_extraction_prompt(
        methodology_name=methodology.display_name,
        methodology_subcategory=methodology.subcategory,
        source_content=format_web_source_for_llm(source),
    )
    try:
        payload = _call_extraction_llm(prompt=prompt, model=model)
        return _rows_from_payload(
            payload=payload,
            methodology=methodology,
            source_origin="web",
            result_id=result_id,
            paper=None,
            stats=local_stats,
        )
    except (InvalidJSONError, Exception) as exc:
        message = str(exc) or exc.__class__.__name__
        logger.warning(
            "Web extraction failed for %s (%s): %s",
            url or source.get("title"),
            methodology.slug,
            message,
        )
        return [
            _error_row(
                methodology=methodology,
                source_origin="web",
                result_id=result_id,
                paper=None,
                message=message,
            ),
        ]


from pipeline.carbon_capture_web import discover_web_sources  # noqa: F401 — re-export
def extract_literature_papers_parallel(
    papers: list[RankedPaper],
    methodology: CarbonCaptureMethodology,
    *,
    model: str = DEFAULT_MODEL,
    concurrency: int | None = None,
    stats: ValidationStats | None = None,
) -> list[CarbonCaptureRow]:
    """Extract canonical rows from ranked literature papers in parallel."""
    local_stats = stats or ValidationStats()
    limit = concurrency or get_extraction_concurrency()

    def worker(paper: RankedPaper) -> list[CarbonCaptureRow]:
        return extract_literature_from_paper(
            paper,
            methodology,
            model=model,
            stats=local_stats,
        )

    parallel = run_parallel_ordered(papers, worker, concurrency=limit, label=f"{methodology.slug}:lit")
    rows: list[CarbonCaptureRow] = []
    for item in parallel:
        if item.success and item.value is not None:
            rows.extend(item.value)
        elif item.item is not None:
            paper = item.item
            rows.append(
                _error_row(
                    methodology=methodology,
                    source_origin="literature",
                    result_id=f"{methodology.slug}:{paper.paper_id}",
                    paper=paper,
                    message=item.error or "Literature extraction worker failed",
                ),
            )
    return rows


def extract_web_sources_parallel(
    sources: list[dict],
    methodology: CarbonCaptureMethodology,
    *,
    model: str = DEFAULT_MODEL,
    concurrency: int | None = None,
    stats: ValidationStats | None = None,
) -> list[CarbonCaptureRow]:
    """Extract canonical rows from web sources in parallel."""
    if not sources:
        return []

    local_stats = stats or ValidationStats()
    limit = concurrency or get_extraction_concurrency()

    def worker(source: dict) -> list[CarbonCaptureRow]:
        return extract_web_from_source(source, methodology, model=model, stats=local_stats)

    parallel = run_parallel_ordered(sources, worker, concurrency=limit, label=f"{methodology.slug}:web")
    rows: list[CarbonCaptureRow] = []
    for item in parallel:
        if item.success and item.value is not None:
            rows.extend(item.value)
        elif item.item is not None:
            source = item.item
            rows.append(
                _error_row(
                    methodology=methodology,
                    source_origin="web",
                    result_id=f"{methodology.slug}:web:error",
                    paper=None,
                    message=item.error or "Web extraction worker failed",
                    source_title=str(source.get("title") or NA),
                    source_url=str(source.get("url") or NA),
                ),
            )
    return rows
