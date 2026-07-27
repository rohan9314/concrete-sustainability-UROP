"""Canonical SCM evidence schema, validation, and normalization."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

NA = "NA"

CONFIDENCE_LEVELS = ("High", "Medium", "Low", NA)
DEPLOYMENT_STAGES = ("Laboratory", "Pilot", "Demonstration", "Commercial", NA)
SOURCE_TYPES = ("Literature", "Web", NA)
PIPELINE_BRANCHES = ("seed_category", "open_discovery")

SEED_CATEGORY_IDS = (
    "slag_cement",
    "coal_fly_ash",
    "harvested_coal_ash",
    "coal_bottom_ash",
    "silica_fume",
    "natural_pozzolans",
    "glass_pozzolan",
    "ternary_blends",
    NA,
)

CATEGORY_ID = "scm"
CATEGORY_LABEL = "Supplementary Cementitious Materials"

# Values that indicate a carbon-capture (or other non-SCM) record leaked in.
FORBIDDEN_CATEGORY_VALUES: frozenset[str] = frozenset(
    {
        "carbon capture",
        "carbon_capture",
        "ccs",
    },
)

EVIDENCE_FIELDS: tuple[str, ...] = (
    "record_id",
    "category_id",
    "category",
    "seed_category",
    "raw_material_name",
    "canonical_material_name",
    "alternative_names",
    "material_origin",
    "origin_industry",
    "material_family",
    "processing_method",
    "reactivity_mechanism",
    "application",
    "binder_system",
    "constituent_materials",
    "replacement_percentage",
    "replacement_basis",
    "strength_result",
    "strength_test_age",
    "strength_comparison_baseline",
    "carbon_reduction_value",
    "carbon_reduction_unit",
    "carbon_reduction_basis",
    "lifecycle_boundary",
    "energy_impact",
    "cost_impact",
    "material_availability",
    "company_or_organization",
    "project_name",
    "deployment_stage",
    "project_year",
    "project_location",
    "production_scale",
    "source_type",
    "source_id",
    "source_title",
    "source_url_or_citation",
    "evidence_text",
    "confidence",
    "notes",
    "pipeline_branch",
)

DISCOVERY_FIELDS: tuple[str, ...] = (
    "discovery_record_id",
    "source_id",
    "source_type",
    "source_title",
    "source_url_or_citation",
    "raw_material_name",
    "alternative_names",
    "raw_material_origin",
    "raw_material_family",
    "processing_method",
    "reactivity_mechanism",
    "cement_or_clinker_replacement_role",
    "replacement_percentage",
    "replacement_basis",
    "strength_evidence_present",
    "environmental_evidence_present",
    "cost_evidence_present",
    "energy_evidence_present",
    "company_or_organization",
    "project_name",
    "deployment_stage",
    "seed_category_match",
    "matched_seed_category",
    "proposed_canonical_name",
    "proposed_category_label",
    "classification_confidence",
    "supporting_evidence",
    "notes",
)

NORMALIZATION_FIELDS: tuple[str, ...] = (
    "raw_material_name",
    "proposed_canonical_name",
    "final_canonical_name",
    "normalization_method",
    "normalization_confidence",
    "manual_override_applied",
)

DISCOVERED_CATEGORY_FIELDS: tuple[str, ...] = (
    "proposed_category",
    "canonical_material_names",
    "total_record_count",
    "unique_source_count",
    "literature_source_count",
    "web_source_count",
    "unique_organization_count",
    "common_aliases",
    "common_origins",
    "common_processing_methods",
    "common_reactivity_mechanisms",
    "example_source_ids",
    "seed_category_overlap",
    "classification_coherence",
    "recommended_action",
    "recommendation_reason",
)

RECOMMENDED_ACTIONS = (
    "MERGE_WITH_SEED_CATEGORY",
    "CREATE_DEDICATED_PIPELINE",
    "RETAIN_AS_BROAD_DISCOVERY_CATEGORY",
    "INSUFFICIENT_EVIDENCE",
    "MANUAL_REVIEW",
)

MISSING_VALUE_TOKENS: frozenset[str] = frozenset(
    {
        "",
        "n/a",
        "na",
        "n.a.",
        "n.a",
        "none",
        "null",
        "not found",
        "not reported",
        "not available",
        "unknown",
        "no data",
        "unavailable",
        "no information found",
    },
)

CONFIDENCE_ALIASES: dict[str, str] = {
    "high": "High",
    "medium": "Medium",
    "med": "Medium",
    "low": "Low",
}

DEPLOYMENT_STAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bcommercial(?:ly)?\b", re.I), "Commercial"),
    (re.compile(r"\bdemonstration\b|\bdemo(?:nstration)?[- ]scale\b", re.I), "Demonstration"),
    (re.compile(r"\bpilot(?:[- ]scale)?\b", re.I), "Pilot"),
    (re.compile(r"\b(lab(?:oratory)?|lab)[- ]scale\b", re.I), "Laboratory"),
    (re.compile(r"\blaboratory\b", re.I), "Laboratory"),
)

FUTURE_PROJECTION_PATTERN = re.compile(
    r"\b(expected|planned|target|projected|by 20\d{2}|future|anticipated)\b",
    re.I,
)


@dataclass
class ValidationStats:
    records_processed: int = 0
    invalid_confidence_corrected: int = 0
    invalid_deployment_stage_corrected: int = 0
    invalid_source_type_corrected: int = 0
    missing_values_normalized: int = 0
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "ValidationStats") -> None:
        self.records_processed += other.records_processed
        self.invalid_confidence_corrected += other.invalid_confidence_corrected
        self.invalid_deployment_stage_corrected += other.invalid_deployment_stage_corrected
        self.invalid_source_type_corrected += other.invalid_source_type_corrected
        self.missing_values_normalized += other.missing_values_normalized
        self.warnings.extend(other.warnings)


def is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    text = str(value).strip().lower()
    return text in MISSING_VALUE_TOKENS


def normalize_missing(value: object) -> str:
    if is_missing(value):
        return NA
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text if text else NA


def encode_list_field(value: object) -> str:
    """Serialize list-like fields as JSON arrays for CSV/JSONL stability."""
    if is_missing(value):
        return NA
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in MISSING_VALUE_TOKENS:
            return NA
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return json.dumps(parsed, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
            return stripped
        # Comma-separated fallback → JSON array
        parts = [part.strip() for part in stripped.split(",") if part.strip()]
        return json.dumps(parts, ensure_ascii=False) if parts else NA
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return normalize_missing(value)


def decode_list_field(value: object) -> list[Any]:
    if is_missing(value):
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return []
    return [part.strip() for part in text.split(",") if part.strip()]


def normalize_confidence(value: object, stats: ValidationStats | None = None) -> str:
    if is_missing(value):
        return NA
    text = str(value).strip()
    if text in CONFIDENCE_LEVELS:
        return text
    aliased = CONFIDENCE_ALIASES.get(text.lower())
    if aliased:
        return aliased
    lowered = text.lower()
    for level in ("High", "Medium", "Low"):
        if level.lower() in lowered and FUTURE_PROJECTION_PATTERN.search(text) is None:
            if stats is not None:
                stats.invalid_confidence_corrected += 1
            return level
    if stats is not None:
        stats.invalid_confidence_corrected += 1
        stats.warnings.append(f"Invalid confidence {value!r} -> NA")
    return NA


def normalize_deployment_stage(value: object, stats: ValidationStats | None = None) -> str:
    if is_missing(value):
        return NA
    text = str(value).strip()
    if text in DEPLOYMENT_STAGES:
        return text
    if FUTURE_PROJECTION_PATTERN.search(text):
        if stats is not None:
            stats.invalid_deployment_stage_corrected += 1
        return NA
    for pattern, stage in DEPLOYMENT_STAGE_PATTERNS:
        if pattern.search(text):
            if stats is not None and text != stage:
                stats.invalid_deployment_stage_corrected += 1
            return stage
    if stats is not None:
        stats.invalid_deployment_stage_corrected += 1
        stats.warnings.append(f"Invalid deployment_stage {value!r} -> NA")
    return NA


def normalize_source_type(value: object, stats: ValidationStats | None = None) -> str:
    if is_missing(value):
        return NA
    text = str(value).strip()
    lowered = text.lower()
    if lowered in {"literature", "paper", "journal"}:
        return "Literature"
    if lowered in {"web", "internet", "webpage", "website"}:
        return "Web"
    if text in SOURCE_TYPES:
        return text
    if stats is not None:
        stats.invalid_source_type_corrected += 1
        stats.warnings.append(f"Invalid source_type {value!r} -> NA")
    return NA


def normalize_boolean(value: object) -> str:
    if is_missing(value):
        return NA
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return "true"
    if text in {"false", "no", "0"}:
        return "false"
    return NA


def normalize_seed_category_id(value: object) -> str:
    if is_missing(value):
        return NA
    text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if text in SEED_CATEGORY_IDS:
        return text
    return NA


def empty_evidence_row() -> dict[str, str]:
    row = {field: NA for field in EVIDENCE_FIELDS}
    row["category_id"] = CATEGORY_ID
    row["category"] = CATEGORY_LABEL
    return row


def empty_discovery_row() -> dict[str, str]:
    return {field: NA for field in DISCOVERY_FIELDS}


def validate_and_normalize_evidence_row(
    row: dict[str, Any],
    *,
    stats: ValidationStats | None = None,
) -> dict[str, str]:
    local = stats or ValidationStats()
    local.records_processed += 1
    out = empty_evidence_row()
    for key, value in row.items():
        if key not in out:
            continue
        if key in {"alternative_names", "constituent_materials"}:
            out[key] = encode_list_field(value)
        else:
            if is_missing(value):
                local.missing_values_normalized += 1
            out[key] = normalize_missing(value)

    out["confidence"] = normalize_confidence(out.get("confidence"), local)
    out["deployment_stage"] = normalize_deployment_stage(out.get("deployment_stage"), local)
    out["source_type"] = normalize_source_type(out.get("source_type"), local)
    out["seed_category"] = normalize_seed_category_id(out.get("seed_category"))
    if out["pipeline_branch"] not in PIPELINE_BRANCHES and out["pipeline_branch"] != NA:
        out["pipeline_branch"] = NA

    # Always stamp SCM category identity.
    out["category_id"] = CATEGORY_ID
    if out.get("category") in {NA, ""} or out.get("category", "").lower() in FORBIDDEN_CATEGORY_VALUES:
        out["category"] = CATEGORY_LABEL

    # Reject empty-string leftovers
    for key, value in list(out.items()):
        if value == "":
            out[key] = NA
            local.missing_values_normalized += 1
            local.warnings.append(f"Empty string replaced with NA for {key}")

    _emit_evidence_warnings(out, local)
    return out


def validate_and_normalize_discovery_row(
    row: dict[str, Any],
    *,
    stats: ValidationStats | None = None,
) -> dict[str, str]:
    local = stats or ValidationStats()
    local.records_processed += 1
    out = empty_discovery_row()
    for key, value in row.items():
        if key not in out:
            continue
        if key == "alternative_names":
            out[key] = encode_list_field(value)
        elif key.startswith(("strength_evidence", "environmental_evidence", "cost_evidence", "energy_evidence")) or key == "seed_category_match":
            out[key] = normalize_boolean(value)
        else:
            out[key] = normalize_missing(value)

    out["deployment_stage"] = normalize_deployment_stage(out.get("deployment_stage"), local)
    out["source_type"] = normalize_source_type(out.get("source_type"), local)
    out["classification_confidence"] = normalize_confidence(
        out.get("classification_confidence"),
        local,
    )
    out["matched_seed_category"] = normalize_seed_category_id(out.get("matched_seed_category"))

    for key, value in list(out.items()):
        if value == "":
            out[key] = NA
            local.missing_values_normalized += 1

    _emit_discovery_warnings(out, local)
    return out


def _parse_float(value: str) -> float | None:
    if value == NA:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _emit_evidence_warnings(row: dict[str, str], stats: ValidationStats) -> None:
    pct = _parse_float(row.get("replacement_percentage", NA))
    if pct is not None and (pct < 0 or pct > 100):
        stats.warnings.append(
            f"{row.get('record_id')}: replacement_percentage out of bounds ({pct})",
        )
    if row.get("carbon_reduction_value", NA) != NA and row.get("carbon_reduction_unit", NA) == NA:
        stats.warnings.append(
            f"{row.get('record_id')}: carbon_reduction_value present but unit missing",
        )
    if row.get("strength_result", NA) != NA and row.get("strength_test_age", NA) == NA:
        stats.warnings.append(
            f"{row.get('record_id')}: strength_result present but test age missing",
        )
    if row.get("seed_category") == "ternary_blends":
        constituents = decode_list_field(row.get("constituent_materials", NA))
        named = [
            item
            for item in constituents
            if isinstance(item, dict)
            and str(item.get("material_name") or "").strip()
            and str(item.get("material_name")).strip().upper() != NA
        ]
        if len(named) < 2:
            stats.warnings.append(
                f"{row.get('record_id')}: ternary blend with fewer than two identified SCM constituents",
            )


def _emit_discovery_warnings(row: dict[str, str], stats: ValidationStats) -> None:
    match = row.get("seed_category_match", NA)
    matched = row.get("matched_seed_category", NA)
    if match == "false" and matched != NA:
        stats.warnings.append(
            f"{row.get('discovery_record_id')}: seed_category_match=false but matched_seed_category populated",
        )
    if match == "true" and matched == NA:
        stats.warnings.append(
            f"{row.get('discovery_record_id')}: seed_category_match=true but matched_seed_category=NA",
        )
