"""Deduplication helpers for Cementitious Materials records."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

from pipeline.cementitious.schema import RECORD_FIELDS, normalize_missing

AUDIT_FIELDS: tuple[str, ...] = (
    "record_id",
    "duplicate_group_id",
    "duplicate_status",
    "duplicate_reason",
    "matched_record_id",
    "canonical_technology_name",
    "source_id",
    "project_name",
)


def _norm(value: object) -> str:
    return normalize_missing(value).casefold().strip()


def exact_duplicate_key(record: dict[str, Any]) -> str:
    parts = [
        _norm(record.get("evidence_origin")),
        _norm(record.get("canonical_technology_name") or record.get("technology_variant")),
        _norm(record.get("source_id")),
        _norm(record.get("source_url") or record.get("normalized_url")),
        _norm(record.get("project_name")),
        _norm(record.get("company_or_organization")),
        _norm(record.get("location")),
        _norm(record.get("project_year") or record.get("publication_year")),
        _norm(record.get("cement_replacement_percentage")),
        _norm(record.get("testing_age_days")),
        _norm(record.get("co2_reduction_value")),
        _norm(record.get("compressive_strength_value")),
        _norm(record.get("sub_subcategory_slug")),
        _norm(record.get("taxonomy_level_3")),
        _norm(record.get("taxonomy_level_4")),
    ]
    blob = "|".join(parts)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def semantic_duplicate_key(record: dict[str, Any]) -> str:
    """Looser key for suspected duplicates (flags only; does not merge)."""
    parts = [
        _norm(record.get("evidence_origin")),
        _norm(record.get("canonical_technology_name") or record.get("raw_technology_name")),
        _norm(record.get("source_id")),
        _norm(record.get("source_url") or record.get("normalized_url")),
        _norm(record.get("project_name")),
        _norm(record.get("company_or_organization")),
        _norm(record.get("sub_subcategory_slug")),
    ]
    blob = "|".join(parts)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def deduplicate_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """
    Remove exact duplicates; flag possible semantic duplicates.

    Does not merge materially different experimental observations.
    """
    kept: list[dict[str, Any]] = []
    audit: list[dict[str, str]] = []
    seen_exact: dict[str, str] = {}
    semantic_groups: dict[str, list[str]] = {}

    for record in records:
        row = dict(record)
        exact = exact_duplicate_key(row)
        if exact in seen_exact:
            row["duplicate_status"] = "Exact Duplicate Removed"
            row["duplicate_group_id"] = exact[:12]
            row["duplicate_reason"] = "Exact match on technology/source/project/metrics key"
            audit.append(
                {
                    "record_id": str(row.get("record_id") or ""),
                    "duplicate_group_id": exact[:12],
                    "duplicate_status": "Exact Duplicate Removed",
                    "duplicate_reason": row["duplicate_reason"],
                    "matched_record_id": seen_exact[exact],
                    "canonical_technology_name": str(row.get("canonical_technology_name") or ""),
                    "source_id": str(row.get("source_id") or ""),
                    "project_name": str(row.get("project_name") or ""),
                }
            )
            continue

        seen_exact[exact] = str(row.get("record_id") or "")
        sem = semantic_duplicate_key(row)
        group = semantic_groups.setdefault(sem, [])
        if group:
            row["duplicate_status"] = "Possible Duplicate"
            row["duplicate_group_id"] = sem
            row["duplicate_reason"] = (
                "Shares normalized technology + source + project + company + sub-subcategory"
            )
            audit.append(
                {
                    "record_id": str(row.get("record_id") or ""),
                    "duplicate_group_id": sem,
                    "duplicate_status": "Possible Duplicate",
                    "duplicate_reason": row["duplicate_reason"],
                    "matched_record_id": group[0],
                    "canonical_technology_name": str(row.get("canonical_technology_name") or ""),
                    "source_id": str(row.get("source_id") or ""),
                    "project_name": str(row.get("project_name") or ""),
                }
            )
        else:
            row["duplicate_status"] = row.get("duplicate_status") or "Unique"
            row["duplicate_group_id"] = row.get("duplicate_group_id") or sem
            row["duplicate_reason"] = row.get("duplicate_reason") or ""
        group.append(str(row.get("record_id") or ""))
        kept.append(row)

    return kept, audit


def write_dedupe_audit(path: Path, audit_rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(AUDIT_FIELDS))
        writer.writeheader()
        for row in audit_rows:
            writer.writerow({k: row.get(k, "") for k in AUDIT_FIELDS})
    return path
