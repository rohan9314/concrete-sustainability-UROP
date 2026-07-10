"""Conservative merge of literature and web carbon capture extraction rows."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass

from pipeline.carbon_capture_extraction import CarbonCaptureRow
from pipeline.carbon_capture_schema import NA

logger = logging.getLogger(__name__)

DESCRIPTIVE_FILL_FIELDS: tuple[str, ...] = (
    "company_or_organization",
    "project_year",
    "project_location",
    "deployment_stage",
    "technology_type",
    "primary_barriers",
    "notes",
)


@dataclass
class MergeStats:
    literature_input: int = 0
    web_input: int = 0
    exact_duplicates_removed: int = 0
    complementary_fields_filled: int = 0
    merged_output: int = 0


def _normalize_key_part(value: str) -> str:
    if not value or value == NA:
        return ""
    return value.strip().lower()


def project_match_key(row: CarbonCaptureRow) -> tuple[str, str, str, str]:
    return (
        _normalize_key_part(row.subcategory),
        _normalize_key_part(row.technology_type),
        _normalize_key_part(row.company_or_organization),
        _normalize_key_part(row.project_name),
    )


def is_high_confidence_project_match(left: CarbonCaptureRow, right: CarbonCaptureRow) -> bool:
    """True when two rows clearly refer to the same project."""
    if left.project_name == NA or right.project_name == NA:
        return False
    if project_match_key(left) != project_match_key(right):
        return False

    for field in ("project_year", "project_location", "deployment_stage"):
        left_value = getattr(left, field)
        right_value = getattr(right, field)
        if left_value != NA and right_value != NA and left_value != right_value:
            return False
    return True


def exact_row_key(row: CarbonCaptureRow) -> tuple[str, ...]:
    canonical = row.to_canonical_dict()
    return tuple(canonical[field] for field in canonical) + (row.source_origin,)


def _copy_row(row: CarbonCaptureRow) -> CarbonCaptureRow:
    return deepcopy(row)


def _fill_na_descriptive(target: CarbonCaptureRow, source: CarbonCaptureRow) -> int:
    filled = 0
    for field in DESCRIPTIVE_FILL_FIELDS:
        target_value = getattr(target, field)
        source_value = getattr(source, field)
        if target_value == NA and source_value != NA:
            setattr(target, field, source_value)
            filled += 1
    return filled


def conservative_merge_rows(
    literature_rows: list[CarbonCaptureRow],
    web_rows: list[CarbonCaptureRow],
) -> tuple[list[CarbonCaptureRow], MergeStats]:
    """
    Conservative merge:
    - Remove exact duplicate rows
    - Keep metric records separate by source unless exact duplicates
    - Fill N.A. descriptive fields from high-confidence project matches
    - Never overwrite non-N.A. values across sources
    - Preserve separate source-specific rows (source_type stays Literature or Web)
    """
    stats = MergeStats(
        literature_input=len(literature_rows),
        web_input=len(web_rows),
    )
    combined = [*literature_rows, *web_rows]

    seen: set[tuple[str, ...]] = set()
    deduped: list[CarbonCaptureRow] = []
    for row in combined:
        key = exact_row_key(row)
        if key in seen:
            stats.exact_duplicates_removed += 1
            continue
        seen.add(key)
        deduped.append(_copy_row(row))

    by_project: dict[tuple[str, str, str, str], list[CarbonCaptureRow]] = {}
    for row in deduped:
        if row.project_name != NA:
            by_project.setdefault(project_match_key(row), []).append(row)

    merged: list[CarbonCaptureRow] = []
    for row in deduped:
        enriched = _copy_row(row)
        siblings = by_project.get(project_match_key(row), [])
        for sibling in siblings:
            if sibling.record_id == row.record_id:
                continue
            if is_high_confidence_project_match(enriched, sibling):
                stats.complementary_fields_filled += _fill_na_descriptive(enriched, sibling)
        merged.append(enriched)

    stats.merged_output = len(merged)
    logger.info(
        "Conservative merge: literature=%s web=%s -> %s rows "
        "(removed %s exact duplicates, filled %s complementary fields)",
        stats.literature_input,
        stats.web_input,
        stats.merged_output,
        stats.exact_duplicates_removed,
        stats.complementary_fields_filled,
    )
    return merged, stats


def count_project_specific_rows(rows: list[CarbonCaptureRow]) -> int:
    return sum(1 for row in rows if row.project_name != NA)


def count_rows_without_project(rows: list[CarbonCaptureRow]) -> int:
    return sum(1 for row in rows if row.project_name == NA)


# Backward-compatible alias used by older export helpers.
def merge_literature_and_web_rows(
    literature_rows: list[CarbonCaptureRow],
    web_rows: list[CarbonCaptureRow],
    *,
    deduplicate: bool = False,
) -> list[CarbonCaptureRow]:
    if deduplicate:
        merged, _ = conservative_merge_rows(literature_rows, web_rows)
        return merged
    return [*literature_rows, *web_rows]
