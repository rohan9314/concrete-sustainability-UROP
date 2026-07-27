"""Conservative merge and deduplication for SCM evidence rows."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass

from pipeline.scm.config import CATEGORY_ID, CATEGORY_LABEL
from pipeline.scm.extraction import ScmEvidenceRow
from pipeline.scm.schema import FORBIDDEN_CATEGORY_VALUES, NA

logger = logging.getLogger(__name__)

DESCRIPTIVE_FILL_FIELDS: tuple[str, ...] = (
    "company_or_organization",
    "project_year",
    "project_location",
    "deployment_stage",
    "material_origin",
    "origin_industry",
    "processing_method",
    "reactivity_mechanism",
    "material_availability",
    "notes",
)


@dataclass
class MergeStats:
    literature_input: int = 0
    web_input: int = 0
    discovery_input: int = 0
    exact_duplicates_removed: int = 0
    complementary_fields_filled: int = 0
    merged_output: int = 0


class NonScmRecordError(ValueError):
    """Raised when a carbon-capture or other non-SCM record appears in SCM merge."""


def assert_scm_records(rows: list[ScmEvidenceRow]) -> None:
    """Fail loudly if any carbon-capture / foreign-category record is present."""
    for row in rows:
        category = (row.category or "").strip()
        category_id = getattr(row, "category_id", "") or ""
        lowered = category.lower()
        if lowered in FORBIDDEN_CATEGORY_VALUES or category_id.lower() in {"carbon_capture", "ccs"}:
            raise NonScmRecordError(
                f"SCM merge rejected non-SCM record {row.record_id!r} "
                f"(category={category!r}, category_id={category_id!r}). "
                "Carbon-capture outputs must not be read or merged by SCM commands.",
            )
        if category not in {CATEGORY_LABEL, NA, ""} and "supplementary" not in lowered:
            if any(token in lowered for token in ("carbon capture", "ccs", "amine", "oxyfuel")):
                raise NonScmRecordError(
                    f"SCM merge rejected foreign-category record {row.record_id!r} "
                    f"(category={category!r}).",
                )


def _normalize_key_part(value: str) -> str:
    if not value or value == NA:
        return ""
    return value.strip().lower()


def exact_row_key(row: ScmEvidenceRow) -> tuple[str, ...]:
    canonical = row.to_evidence_dict()
    return tuple(canonical[field] for field in canonical) + (row.source_origin,)


def evidence_context_key(row: ScmEvidenceRow) -> tuple[str, ...]:
    """Strong agreement key — do not merge on name/company/source alone."""
    return (
        _normalize_key_part(row.seed_category),
        _normalize_key_part(row.raw_material_name),
        _normalize_key_part(row.canonical_material_name),
        _normalize_key_part(row.company_or_organization),
        _normalize_key_part(row.project_name),
        _normalize_key_part(row.replacement_percentage),
        _normalize_key_part(row.replacement_basis),
        _normalize_key_part(row.strength_test_age),
        _normalize_key_part(row.lifecycle_boundary),
        _normalize_key_part(row.binder_system),
        _normalize_key_part(row.source_id),
        _normalize_key_part(row.source_type),
        _normalize_key_part(row.pipeline_branch),
    )


def _copy_row(row: ScmEvidenceRow) -> ScmEvidenceRow:
    return deepcopy(row)


def _fill_na_descriptive(target: ScmEvidenceRow, source: ScmEvidenceRow) -> int:
    filled = 0
    for field in DESCRIPTIVE_FILL_FIELDS:
        target_value = getattr(target, field)
        source_value = getattr(source, field)
        if target_value == NA and source_value != NA:
            setattr(target, field, source_value)
            filled += 1
    return filled


def conservative_merge_rows(
    literature_rows: list[ScmEvidenceRow],
    web_rows: list[ScmEvidenceRow],
    discovery_rows: list[ScmEvidenceRow] | None = None,
) -> tuple[list[ScmEvidenceRow], MergeStats]:
    """
    Conservative merge:
    - Reject any carbon-capture / non-SCM records
    - Remove exact duplicate rows only
    - Keep conflicting measurements / conditions as separate rows
    - Fill NA descriptive fields only when evidence context strongly agrees
    - Never overwrite non-NA values
    """
    discovery_rows = discovery_rows or []
    assert_scm_records([*literature_rows, *web_rows, *discovery_rows])

    stats = MergeStats(
        literature_input=len(literature_rows),
        web_input=len(web_rows),
        discovery_input=len(discovery_rows),
    )
    combined = [*literature_rows, *web_rows, *discovery_rows]

    seen: set[tuple[str, ...]] = set()
    deduped: list[ScmEvidenceRow] = []
    for row in combined:
        if not getattr(row, "category_id", None) or row.category_id in {NA, ""}:
            row.category_id = CATEGORY_ID
        if row.category in {NA, ""}:
            row.category = CATEGORY_LABEL
        key = exact_row_key(row)
        if key in seen:
            stats.exact_duplicates_removed += 1
            continue
        seen.add(key)
        deduped.append(_copy_row(row))

    by_context: dict[tuple[str, ...], list[ScmEvidenceRow]] = {}
    for row in deduped:
        by_context.setdefault(evidence_context_key(row), []).append(row)

    merged: list[ScmEvidenceRow] = []
    for row in deduped:
        enriched = _copy_row(row)
        siblings = by_context.get(evidence_context_key(row), [])
        for sibling in siblings:
            if sibling.record_id == row.record_id:
                continue
            stats.complementary_fields_filled += _fill_na_descriptive(enriched, sibling)
        merged.append(enriched)

    assert_scm_records(merged)
    stats.merged_output = len(merged)
    logger.info(
        "SCM conservative merge: lit=%s web=%s discovery=%s -> %s "
        "(removed %s exact duplicates, filled %s fields)",
        stats.literature_input,
        stats.web_input,
        stats.discovery_input,
        stats.merged_output,
        stats.exact_duplicates_removed,
        stats.complementary_fields_filled,
    )
    return merged, stats
