"""Open-ended SCM discovery: aggregation and promotion recommendations."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Any

from pipeline.scm.config import get_promotion_thresholds
from pipeline.scm.extraction import ScmDiscoveryRow
from pipeline.scm.schema import NA, RECOMMENDED_ACTIONS, encode_list_field

logger = logging.getLogger(__name__)


def discovery_row_to_evidence_bridge(row: ScmDiscoveryRow) -> dict[str, str]:
    """Map a discovery row into evidence-shaped fields for combined exports."""
    from pipeline.scm.schema import empty_evidence_row

    evidence = empty_evidence_row()
    evidence.update(
        {
            "record_id": row.discovery_record_id,
            "category_id": "scm",
            "category": "Supplementary Cementitious Materials",
            "seed_category": row.matched_seed_category
            if row.seed_category_match == "true"
            else NA,
            "raw_material_name": row.raw_material_name,
            "canonical_material_name": row.proposed_canonical_name,
            "alternative_names": row.alternative_names,
            "material_origin": row.raw_material_origin,
            "material_family": row.raw_material_family,
            "processing_method": row.processing_method,
            "reactivity_mechanism": row.reactivity_mechanism,
            "replacement_percentage": row.replacement_percentage,
            "replacement_basis": row.replacement_basis,
            "company_or_organization": row.company_or_organization,
            "project_name": row.project_name,
            "deployment_stage": row.deployment_stage,
            "source_type": row.source_type,
            "source_id": row.source_id,
            "source_title": row.source_title,
            "source_url_or_citation": row.source_url_or_citation,
            "evidence_text": row.supporting_evidence,
            "confidence": row.classification_confidence,
            "notes": row.notes,
            "pipeline_branch": "open_discovery",
        },
    )
    return evidence


def aggregate_discovery_candidates(
    rows: list[ScmDiscoveryRow],
    *,
    normalization_by_raw: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate source-level discovery rows by proposed canonical / category."""
    buckets: dict[str, list[ScmDiscoveryRow]] = defaultdict(list)
    for row in rows:
        raw = row.raw_material_name
        norm = (normalization_by_raw or {}).get(raw, {})
        canonical = (
            norm.get("final_canonical_name")
            or row.proposed_canonical_name
            or row.raw_material_name
            or NA
        )
        category = row.proposed_category_label if row.proposed_category_label != NA else canonical
        key = f"{category}||{canonical}".lower()
        buckets[key].append(row)

    aggregated: list[dict[str, Any]] = []
    for key, group in buckets.items():
        category_label, canonical = key.split("||", 1)
        aliases = Counter()
        origins = Counter()
        processing = Counter()
        mechanisms = Counter()
        orgs: set[str] = set()
        sources: set[str] = set()
        lit_sources: set[str] = set()
        web_sources: set[str] = set()
        seed_overlap: set[str] = set()
        example_ids: list[str] = []

        for row in group:
            if row.raw_material_name != NA:
                aliases[row.raw_material_name] += 1
            if row.raw_material_origin != NA:
                origins[row.raw_material_origin] += 1
            if row.processing_method != NA:
                processing[row.processing_method] += 1
            if row.reactivity_mechanism != NA:
                mechanisms[row.reactivity_mechanism] += 1
            if row.company_or_organization != NA:
                orgs.add(row.company_or_organization.lower())
            if row.source_id != NA:
                sources.add(row.source_id)
                if row.source_type == "Literature":
                    lit_sources.add(row.source_id)
                elif row.source_type == "Web":
                    web_sources.add(row.source_id)
            if row.seed_category_match == "true" and row.matched_seed_category != NA:
                seed_overlap.add(row.matched_seed_category)
            if len(example_ids) < 5 and row.source_id != NA:
                example_ids.append(row.source_id)

        # Prefer display-cased labels from first row
        proposed_category = group[0].proposed_category_label
        if proposed_category == NA:
            proposed_category = group[0].proposed_canonical_name
        if proposed_category == NA:
            proposed_category = group[0].raw_material_name

        canonical_names = sorted(
            {
                (
                    (normalization_by_raw or {}).get(r.raw_material_name, {}).get(
                        "final_canonical_name",
                    )
                    or r.proposed_canonical_name
                    or r.raw_material_name
                )
                for r in group
                if (r.raw_material_name != NA or r.proposed_canonical_name != NA)
            },
        )

        aggregated.append(
            {
                "proposed_category": proposed_category,
                "canonical_material_names": canonical_names,
                "total_record_count": len(group),
                "unique_source_count": len(sources),
                "literature_source_count": len(lit_sources),
                "web_source_count": len(web_sources),
                "unique_organization_count": len(orgs),
                "common_aliases": [name for name, _ in aliases.most_common(10)],
                "common_origins": [name for name, _ in origins.most_common(5)],
                "common_processing_methods": [name for name, _ in processing.most_common(5)],
                "common_reactivity_mechanisms": [name for name, _ in mechanisms.most_common(5)],
                "example_source_ids": example_ids,
                "seed_category_overlap": sorted(seed_overlap) or [NA],
                "_bucket_key": key,
            },
        )
    return aggregated


def recommend_action(
    candidate: dict[str, Any],
    *,
    thresholds: dict[str, int] | None = None,
    llm_recommendation: str | None = None,
    llm_reason: str | None = None,
    classification_coherence: str = NA,
) -> tuple[str, str]:
    """Recommend promotion action. Never auto-creates pipeline modules."""
    thresholds = thresholds or get_promotion_thresholds()
    records = int(candidate.get("total_record_count") or 0)
    sources = int(candidate.get("unique_source_count") or 0)
    orgs = int(candidate.get("unique_organization_count") or 0)
    lit = int(candidate.get("literature_source_count") or 0)
    overlap = candidate.get("seed_category_overlap") or []
    if isinstance(overlap, str):
        overlap = [overlap]
    overlap_clean = [x for x in overlap if x and x != NA]

    if llm_recommendation and llm_recommendation in RECOMMENDED_ACTIONS:
        # Still gate CREATE_DEDICATED_PIPELINE on multi-threshold evidence.
        if llm_recommendation == "CREATE_DEDICATED_PIPELINE":
            meets = (
                records >= thresholds["min_strongly_relevant_records"]
                and sources >= thresholds["min_unique_sources"]
                and orgs >= thresholds["min_independent_organizations"]
                and lit >= thresholds["min_literature_sources"]
            )
            if not meets:
                return (
                    "INSUFFICIENT_EVIDENCE",
                    llm_reason
                    or (
                        "LLM suggested dedicated pipeline but configurable thresholds "
                        "were not all met"
                    ),
                )
        return llm_recommendation, llm_reason or "LLM corpus-level recommendation"

    if overlap_clean and records >= 3:
        return (
            "MERGE_WITH_SEED_CATEGORY",
            f"Overlaps seed category/ies {', '.join(overlap_clean)}",
        )

    meets_all = (
        records >= thresholds["min_strongly_relevant_records"]
        and sources >= thresholds["min_unique_sources"]
        and orgs >= thresholds["min_independent_organizations"]
        and lit >= thresholds["min_literature_sources"]
    )
    if meets_all and classification_coherence in {"High", "Medium"}:
        return (
            "CREATE_DEDICATED_PIPELINE",
            "Meets all configurable promotion thresholds with coherent definition",
        )

    if records < 3 or sources < 2:
        return "INSUFFICIENT_EVIDENCE", "Too few records or sources"

    if records >= 5 and sources >= 3:
        return (
            "RETAIN_AS_BROAD_DISCOVERY_CATEGORY",
            "Repeatedly observed but below dedicated-pipeline thresholds",
        )

    return "MANUAL_REVIEW", "Borderline evidence; human review recommended"


def build_discovered_category_rows(
    aggregated: list[dict[str, Any]],
    *,
    llm_groupings: list[dict[str, Any]] | None = None,
    thresholds: dict[str, int] | None = None,
) -> list[dict[str, str]]:
    thresholds = thresholds or get_promotion_thresholds()
    llm_by_category = {
        str(item.get("proposed_category") or "").strip().lower(): item
        for item in (llm_groupings or [])
        if isinstance(item, dict)
    }

    rows: list[dict[str, str]] = []
    for candidate in aggregated:
        label = str(candidate.get("proposed_category") or NA)
        llm = llm_by_category.get(label.lower(), {})
        coherence = str(llm.get("classification_coherence") or NA)
        action, reason = recommend_action(
            candidate,
            thresholds=thresholds,
            llm_recommendation=str(llm.get("recommended_action") or "") or None,
            llm_reason=str(llm.get("recommendation_reason") or "") or None,
            classification_coherence=coherence,
        )
        seed_overlap = candidate.get("seed_category_overlap") or [NA]
        rows.append(
            {
                "proposed_category": label,
                "canonical_material_names": encode_list_field(
                    llm.get("canonical_material_names")
                    or candidate.get("canonical_material_names"),
                ),
                "total_record_count": str(candidate.get("total_record_count", 0)),
                "unique_source_count": str(candidate.get("unique_source_count", 0)),
                "literature_source_count": str(candidate.get("literature_source_count", 0)),
                "web_source_count": str(candidate.get("web_source_count", 0)),
                "unique_organization_count": str(
                    candidate.get("unique_organization_count", 0),
                ),
                "common_aliases": encode_list_field(
                    llm.get("common_aliases") or candidate.get("common_aliases"),
                ),
                "common_origins": encode_list_field(candidate.get("common_origins")),
                "common_processing_methods": encode_list_field(
                    candidate.get("common_processing_methods"),
                ),
                "common_reactivity_mechanisms": encode_list_field(
                    candidate.get("common_reactivity_mechanisms"),
                ),
                "example_source_ids": encode_list_field(candidate.get("example_source_ids")),
                "seed_category_overlap": encode_list_field(
                    llm.get("seed_category_overlap") or seed_overlap,
                ),
                "classification_coherence": coherence if coherence != "" else NA,
                "recommended_action": action,
                "recommendation_reason": reason,
            },
        )
    return rows


def aggregated_for_llm_prompt(aggregated: list[dict[str, Any]], *, limit: int = 50) -> str:
    """Serialize aggregated candidates for corpus-level clustering prompt."""
    slim = []
    for item in sorted(
        aggregated,
        key=lambda row: int(row.get("total_record_count") or 0),
        reverse=True,
    )[:limit]:
        slim.append(
            {
                "proposed_category": item.get("proposed_category"),
                "canonical_material_names": item.get("canonical_material_names"),
                "total_record_count": item.get("total_record_count"),
                "unique_source_count": item.get("unique_source_count"),
                "literature_source_count": item.get("literature_source_count"),
                "web_source_count": item.get("web_source_count"),
                "unique_organization_count": item.get("unique_organization_count"),
                "common_aliases": item.get("common_aliases"),
                "example_source_ids": item.get("example_source_ids"),
                "seed_category_overlap": item.get("seed_category_overlap"),
            },
        )
    return json.dumps(slim, indent=2, ensure_ascii=False)
