"""Literature and web extraction for SCM seed categories and discovery."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, fields
from typing import Any

from pipeline.concurrency import run_parallel_ordered
from pipeline.config import get_extraction_concurrency
from pipeline.llm_utils import DEFAULT_MODEL, InvalidJSONError, _parse_json_response
from pipeline.openai_client import call_openai
from pipeline.schema import RankedPaper
from pipeline.scm.prompts import (
    DISCOVERY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_discovery_extraction_prompt,
    build_literature_extraction_prompt,
    build_web_extraction_prompt,
)
from pipeline.scm.schema import (
    DISCOVERY_FIELDS,
    EVIDENCE_FIELDS,
    NA,
    ValidationStats,
    empty_discovery_row,
    empty_evidence_row,
    validate_and_normalize_discovery_row,
    validate_and_normalize_evidence_row,
)
from pipeline.scm.seed_categories import ScmSeedCategory

logger = logging.getLogger(__name__)


@dataclass
class ScmEvidenceRow:
    """One SCM evidence-level output row plus pipeline metadata."""

    record_id: str = NA
    category_id: str = "scm"
    category: str = NA
    seed_category: str = NA
    raw_material_name: str = NA
    canonical_material_name: str = NA
    alternative_names: str = NA
    material_origin: str = NA
    origin_industry: str = NA
    material_family: str = NA
    processing_method: str = NA
    reactivity_mechanism: str = NA
    application: str = NA
    binder_system: str = NA
    constituent_materials: str = NA
    replacement_percentage: str = NA
    replacement_basis: str = NA
    strength_result: str = NA
    strength_test_age: str = NA
    strength_comparison_baseline: str = NA
    carbon_reduction_value: str = NA
    carbon_reduction_unit: str = NA
    carbon_reduction_basis: str = NA
    lifecycle_boundary: str = NA
    energy_impact: str = NA
    cost_impact: str = NA
    material_availability: str = NA
    company_or_organization: str = NA
    project_name: str = NA
    deployment_stage: str = NA
    project_year: str = NA
    project_location: str = NA
    production_scale: str = NA
    source_type: str = NA
    source_id: str = NA
    source_title: str = NA
    source_url_or_citation: str = NA
    evidence_text: str = NA
    confidence: str = NA
    notes: str = NA
    pipeline_branch: str = NA
    source_origin: str = NA
    rank_score: float = 0.0
    extraction_error: str = ""

    def to_evidence_dict(self) -> dict[str, str]:
        return {name: str(getattr(self, name)) for name in EVIDENCE_FIELDS}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScmEvidenceRow":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class ScmDiscoveryRow:
    discovery_record_id: str = NA
    source_id: str = NA
    source_type: str = NA
    source_title: str = NA
    source_url_or_citation: str = NA
    raw_material_name: str = NA
    alternative_names: str = NA
    raw_material_origin: str = NA
    raw_material_family: str = NA
    processing_method: str = NA
    reactivity_mechanism: str = NA
    cement_or_clinker_replacement_role: str = NA
    replacement_percentage: str = NA
    replacement_basis: str = NA
    strength_evidence_present: str = NA
    environmental_evidence_present: str = NA
    cost_evidence_present: str = NA
    energy_evidence_present: str = NA
    company_or_organization: str = NA
    project_name: str = NA
    deployment_stage: str = NA
    seed_category_match: str = NA
    matched_seed_category: str = NA
    proposed_canonical_name: str = NA
    proposed_category_label: str = NA
    classification_confidence: str = NA
    supporting_evidence: str = NA
    notes: str = NA
    source_origin: str = NA
    rank_score: float = 0.0
    extraction_error: str = ""

    def to_discovery_dict(self) -> dict[str, str]:
        return {name: str(getattr(self, name)) for name in DISCOVERY_FIELDS}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScmDiscoveryRow":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


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
        "paper_id": paper.paper_id,
        "metadata": {
            "authors": paper.authors,
            "year": paper.year,
            "doi": paper.doi,
        },
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


def _call_llm(*, system: str, prompt: str, model: str = DEFAULT_MODEL) -> dict:
    raw = call_openai(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return _parse_json_response(raw)


def _records_from_payload(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    records = payload.get("records")
    if isinstance(records, list):
        return [r for r in records if isinstance(r, dict)]
    if any(key in payload for key in EVIDENCE_FIELDS) or any(
        key in payload for key in DISCOVERY_FIELDS
    ):
        return [payload]
    return []


def _evidence_rows_from_payload(
    *,
    payload: dict,
    category: ScmSeedCategory,
    source_origin: str,
    paper: RankedPaper | None,
    source: dict | None,
    stats: ValidationStats,
) -> list[ScmEvidenceRow]:
    raw_records = _records_from_payload(payload)
    if not raw_records:
        fallback = empty_evidence_row()
        fallback["source_type"] = "Literature" if source_origin == "literature" else "Web"
        fallback["category"] = category.category
        fallback["seed_category"] = category.slug
        fallback["pipeline_branch"] = "seed_category"
        if paper is not None:
            fallback["source_title"] = paper.title
            fallback["source_id"] = paper.paper_id
            fallback["source_url_or_citation"] = paper.url or (
                f"https://doi.org/{paper.doi}" if paper.doi else NA
            )
        elif source is not None:
            fallback["source_title"] = str(source.get("title") or NA)
            fallback["source_url_or_citation"] = str(source.get("url") or NA)
            fallback["source_id"] = str(source.get("url") or source.get("title") or NA)
        raw_records = [fallback]

    rows: list[ScmEvidenceRow] = []
    source_key = (
        paper.paper_id
        if paper is not None
        else str((source or {}).get("url") or (source or {}).get("title") or uuid.uuid4().hex[:8])
    )
    for index, raw in enumerate(raw_records):
        raw.setdefault("category", category.category)
        raw.setdefault("seed_category", category.slug)
        raw.setdefault("pipeline_branch", "seed_category")
        raw.setdefault(
            "source_type",
            "Literature" if source_origin == "literature" else "Web",
        )
        if paper is not None:
            raw.setdefault("source_title", paper.title)
            raw.setdefault("source_id", paper.paper_id)
            raw.setdefault(
                "source_url_or_citation",
                paper.url or (f"https://doi.org/{paper.doi}" if paper.doi else NA),
            )
        elif source is not None:
            raw.setdefault("source_title", source.get("title") or NA)
            raw.setdefault("source_url_or_citation", source.get("url") or NA)
            raw.setdefault("source_id", source.get("url") or source.get("title") or NA)

        canonical = validate_and_normalize_evidence_row(raw, stats=stats)
        record_id = canonical.get("record_id")
        if record_id in {NA, ""}:
            record_id = f"{category.slug}:{source_key}:{index}"
        canonical["record_id"] = record_id
        rows.append(
            ScmEvidenceRow.from_dict(
                {
                    **canonical,
                    "source_origin": source_origin,
                    "rank_score": float(paper.rank_score) if paper is not None else 0.0,
                },
            ),
        )
    return rows


def extract_literature_paper(
    paper: RankedPaper,
    category: ScmSeedCategory,
    *,
    stats: ValidationStats | None = None,
    model: str = DEFAULT_MODEL,
) -> list[ScmEvidenceRow]:
    local_stats = stats or ValidationStats()
    source = ranked_paper_to_source(paper)
    prompt = build_literature_extraction_prompt(
        seed_category_name=category.display_name,
        seed_category_slug=category.slug,
        source_content=format_literature_source_for_llm(source),
        is_ternary=category.is_binder_system,
    )
    try:
        payload = _call_llm(system=SYSTEM_PROMPT, prompt=prompt, model=model)
        return _evidence_rows_from_payload(
            payload=payload,
            category=category,
            source_origin="literature",
            paper=paper,
            source=None,
            stats=local_stats,
        )
    except (InvalidJSONError, Exception) as exc:
        logger.warning("SCM literature extraction failed for %s: %s", paper.paper_id, exc)
        row = empty_evidence_row()
        row.update(
            {
                "record_id": f"{category.slug}:{paper.paper_id}:0",
                "category": category.category,
                "seed_category": category.slug,
                "pipeline_branch": "seed_category",
                "source_type": "Literature",
                "source_id": paper.paper_id,
                "source_title": paper.title,
                "source_url_or_citation": paper.url
                or (f"https://doi.org/{paper.doi}" if paper.doi else NA),
                "notes": f"extraction_error: {exc}",
            },
        )
        canonical = validate_and_normalize_evidence_row(row, stats=local_stats)
        return [
            ScmEvidenceRow.from_dict(
                {
                    **canonical,
                    "source_origin": "literature",
                    "rank_score": float(paper.rank_score),
                    "extraction_error": str(exc),
                },
            ),
        ]


def extract_web_source(
    source: dict,
    category: ScmSeedCategory,
    *,
    stats: ValidationStats | None = None,
    model: str = DEFAULT_MODEL,
) -> list[ScmEvidenceRow]:
    local_stats = stats or ValidationStats()
    prompt = build_web_extraction_prompt(
        seed_category_name=category.display_name,
        seed_category_slug=category.slug,
        source_content=format_web_source_for_llm(source),
        is_ternary=category.is_binder_system,
    )
    try:
        payload = _call_llm(system=SYSTEM_PROMPT, prompt=prompt, model=model)
        return _evidence_rows_from_payload(
            payload=payload,
            category=category,
            source_origin="web",
            paper=None,
            source=source,
            stats=local_stats,
        )
    except (InvalidJSONError, Exception) as exc:
        logger.warning("SCM web extraction failed for %s: %s", source.get("url"), exc)
        row = empty_evidence_row()
        row.update(
            {
                "record_id": f"{category.slug}:web:{uuid.uuid4().hex[:8]}:0",
                "category": category.category,
                "seed_category": category.slug,
                "pipeline_branch": "seed_category",
                "source_type": "Web",
                "source_title": str(source.get("title") or NA),
                "source_url_or_citation": str(source.get("url") or NA),
                "source_id": str(source.get("url") or NA),
                "notes": f"extraction_error: {exc}",
            },
        )
        canonical = validate_and_normalize_evidence_row(row, stats=local_stats)
        return [
            ScmEvidenceRow.from_dict(
                {
                    **canonical,
                    "source_origin": "web",
                    "extraction_error": str(exc),
                },
            ),
        ]


def extract_literature_papers_parallel(
    papers: list[RankedPaper],
    category: ScmSeedCategory,
    *,
    concurrency: int | None = None,
    stats: ValidationStats | None = None,
) -> list[ScmEvidenceRow]:
    local_stats = stats or ValidationStats()
    workers = concurrency or get_extraction_concurrency()

    def _one(paper: RankedPaper) -> list[ScmEvidenceRow]:
        return extract_literature_paper(paper, category, stats=local_stats)

    parallel = run_parallel_ordered(
        papers,
        _one,
        concurrency=workers,
        label=f"{category.slug}:lit",
    )
    rows: list[ScmEvidenceRow] = []
    for item in parallel:
        if item.success and item.value is not None:
            rows.extend(item.value)
        elif item.item is not None:
            paper = item.item
            fallback = empty_evidence_row()
            fallback.update(
                {
                    "record_id": f"{category.slug}:{paper.paper_id}:0",
                    "category": category.category,
                    "seed_category": category.slug,
                    "pipeline_branch": "seed_category",
                    "source_type": "Literature",
                    "source_id": paper.paper_id,
                    "source_title": paper.title,
                    "notes": f"extraction_error: {item.error or 'worker failed'}",
                },
            )
            canonical = validate_and_normalize_evidence_row(fallback, stats=local_stats)
            rows.append(
                ScmEvidenceRow.from_dict(
                    {
                        **canonical,
                        "source_origin": "literature",
                        "rank_score": float(paper.rank_score),
                        "extraction_error": item.error or "worker failed",
                    },
                ),
            )
    return rows


def extract_web_sources_parallel(
    sources: list[dict],
    category: ScmSeedCategory,
    *,
    concurrency: int | None = None,
    stats: ValidationStats | None = None,
) -> list[ScmEvidenceRow]:
    if not sources:
        return []
    local_stats = stats or ValidationStats()
    workers = concurrency or get_extraction_concurrency()

    def _one(source: dict) -> list[ScmEvidenceRow]:
        return extract_web_source(source, category, stats=local_stats)

    parallel = run_parallel_ordered(
        sources,
        _one,
        concurrency=workers,
        label=f"{category.slug}:web",
    )
    rows: list[ScmEvidenceRow] = []
    for item in parallel:
        if item.success and item.value is not None:
            rows.extend(item.value)
    return rows


def extract_discovery_from_source(
    *,
    source_content: str,
    source_type: str,
    source_id: str,
    source_title: str,
    source_url: str,
    source_origin: str,
    stats: ValidationStats | None = None,
    model: str = DEFAULT_MODEL,
) -> list[ScmDiscoveryRow]:
    local_stats = stats or ValidationStats()
    prompt = build_discovery_extraction_prompt(
        source_content=source_content,
        source_type=source_type,
    )
    try:
        payload = _call_llm(system=DISCOVERY_SYSTEM_PROMPT, prompt=prompt, model=model)
        raw_records = _records_from_payload(payload)
    except (InvalidJSONError, Exception) as exc:
        logger.warning("SCM discovery extraction failed for %s: %s", source_id, exc)
        raw_records = []
        err_row = empty_discovery_row()
        err_row.update(
            {
                "discovery_record_id": f"discovery:{source_id}:0",
                "source_id": source_id,
                "source_type": source_type,
                "source_title": source_title,
                "source_url_or_citation": source_url or NA,
                "notes": f"extraction_error: {exc}",
                "seed_category_match": "false",
                "matched_seed_category": NA,
            },
        )
        canonical = validate_and_normalize_discovery_row(err_row, stats=local_stats)
        return [
            ScmDiscoveryRow.from_dict(
                {
                    **canonical,
                    "source_origin": source_origin,
                    "extraction_error": str(exc),
                },
            ),
        ]

    if not raw_records:
        return []

    rows: list[ScmDiscoveryRow] = []
    for index, raw in enumerate(raw_records):
        raw.setdefault("source_id", source_id)
        raw.setdefault("source_type", source_type)
        raw.setdefault("source_title", source_title)
        raw.setdefault("source_url_or_citation", source_url or NA)
        # Never force unknown materials into seed categories.
        if str(raw.get("seed_category_match", "")).lower() in {"", "na", "n.a.", "none"}:
            raw["seed_category_match"] = "false"
            raw["matched_seed_category"] = NA
        canonical = validate_and_normalize_discovery_row(raw, stats=local_stats)
        discovery_id = canonical.get("discovery_record_id")
        if discovery_id in {NA, ""}:
            discovery_id = f"discovery:{source_id}:{index}"
            canonical["discovery_record_id"] = discovery_id
        rows.append(ScmDiscoveryRow.from_dict({**canonical, "source_origin": source_origin}))
    return rows


def extract_discovery_papers_parallel(
    papers: list[RankedPaper],
    *,
    concurrency: int | None = None,
    stats: ValidationStats | None = None,
) -> list[ScmDiscoveryRow]:
    local_stats = stats or ValidationStats()
    workers = concurrency or get_extraction_concurrency()

    def _one(paper: RankedPaper) -> list[ScmDiscoveryRow]:
        source = ranked_paper_to_source(paper)
        return extract_discovery_from_source(
            source_content=format_literature_source_for_llm(source),
            source_type="Literature",
            source_id=paper.paper_id,
            source_title=paper.title,
            source_url=source.get("url") or "",
            source_origin="literature",
            stats=local_stats,
        )

    parallel = run_parallel_ordered(
        papers,
        _one,
        concurrency=workers,
        label="scm-discovery:lit",
    )
    rows: list[ScmDiscoveryRow] = []
    for item in parallel:
        if item.success and item.value is not None:
            rows.extend(item.value)
    return rows
