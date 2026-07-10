"""Canonical schema, validation, and normalization for carbon capture extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

NA = "N.A."

CONFIDENCE_LEVELS = ("High", "Medium", "Low", NA)
DEPLOYMENT_STAGES = ("Laboratory", "Pilot", "Demonstration", "Commercial", NA)
SOURCE_TYPES = ("Literature", "Web", NA)
METRIC_DIMENSIONS = ("CO2 Reduction", "Energy", "Cost", "Other", NA)

CANONICAL_FIELDS: tuple[str, ...] = (
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
)

LEGACY_FIELD_MAP: dict[str, str] = {
    "company": "company_or_organization",
    "organization": "company_or_organization",
    "solution_or_technology_type": "technology_type",
    "technology_name": "technology_type",
    "solution": "technology_type",
    "project": "project_name",
    "year": "project_year",
    "location": "project_location",
    "value": "metric_value",
    "unit": "metric_unit",
    "boundary": "metric_boundary",
    "source": "source_type",
    "title": "source_title",
    "url_citation": "source_url_or_citation",
    "url": "source_url_or_citation",
    "citation": "source_url_or_citation",
    "cost": "cost_impact",
    "paper_title": "source_title",
    "paper_url": "source_url_or_citation",
    "paper_doi": "source_url_or_citation",
    "evidence": "source_url_or_citation",
    "source_url": "source_url_or_citation",
}

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
        "not reported.",
        "not found.",
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

METRIC_DIMENSION_ALIASES: dict[str, str] = {
    "co2": "CO2 Reduction",
    "co2 reduction": "CO2 Reduction",
    "ghg": "CO2 Reduction",
    "energy": "Energy",
    "cost": "Cost",
    "economic": "Cost",
    "other": "Other",
}


@dataclass
class ValidationStats:
    records_processed: int = 0
    invalid_confidence_corrected: int = 0
    invalid_deployment_stage_corrected: int = 0
    invalid_source_type_corrected: int = 0
    invalid_metric_dimension_corrected: int = 0
    invalid_project_year_corrected: int = 0
    missing_metric_name_inferred: int = 0
    metric_value_unit_split: int = 0
    missing_values_normalized: int = 0
    duplicate_columns_removed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: ValidationStats) -> None:
        self.records_processed += other.records_processed
        self.invalid_confidence_corrected += other.invalid_confidence_corrected
        self.invalid_deployment_stage_corrected += other.invalid_deployment_stage_corrected
        self.invalid_source_type_corrected += other.invalid_source_type_corrected
        self.invalid_metric_dimension_corrected += other.invalid_metric_dimension_corrected
        self.invalid_project_year_corrected += other.invalid_project_year_corrected
        self.missing_metric_name_inferred += other.missing_metric_name_inferred
        self.metric_value_unit_split += other.metric_value_unit_split
        self.missing_values_normalized += other.missing_values_normalized
        self.duplicate_columns_removed.extend(other.duplicate_columns_removed)
        self.warnings.extend(other.warnings)


def is_missing(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text.lower() in MISSING_VALUE_TOKENS


def normalize_missing(value: object) -> str:
    if is_missing(value):
        return NA
    return str(value).strip()


def _first_allowed_token(text: str, allowed: tuple[str, ...]) -> str | None:
    for option in allowed:
        if option == NA:
            continue
        if re.search(rf"\b{re.escape(option)}\b", text, re.I):
            return option
    return None


def normalize_confidence(value: object, stats: ValidationStats | None = None) -> str:
    if is_missing(value):
        return NA
    text = str(value).strip()
    if text in CONFIDENCE_LEVELS:
        return text
    lowered = text.lower()
    if lowered in CONFIDENCE_ALIASES:
        if stats:
            stats.invalid_confidence_corrected += 1
        return CONFIDENCE_ALIASES[lowered]
    token = _first_allowed_token(text, CONFIDENCE_LEVELS)
    if token:
        if stats and token != text:
            stats.invalid_confidence_corrected += 1
        return token
    if stats:
        stats.invalid_confidence_corrected += 1
        stats.warnings.append(f"Invalid confidence value normalized to {NA}: {text[:80]!r}")
    return NA


def normalize_deployment_stage(value: object, stats: ValidationStats | None = None) -> str:
    if is_missing(value):
        return NA
    text = str(value).strip()
    if text in DEPLOYMENT_STAGES:
        return text
    if FUTURE_PROJECTION_PATTERN.search(text):
        if stats:
            stats.invalid_deployment_stage_corrected += 1
            stats.warnings.append(
                f"Future projection ignored for deployment_stage: {text[:80]!r}",
            )
        return NA
    for pattern, stage in DEPLOYMENT_STAGE_PATTERNS:
        if pattern.search(text):
            if stats and stage != text:
                stats.invalid_deployment_stage_corrected += 1
            return stage
    token = _first_allowed_token(text, DEPLOYMENT_STAGES)
    if token:
        if stats and token != text:
            stats.invalid_deployment_stage_corrected += 1
        return token
    if stats:
        stats.invalid_deployment_stage_corrected += 1
        stats.warnings.append(f"Invalid deployment_stage normalized to {NA}: {text[:80]!r}")
    return NA


def normalize_source_type(value: object, stats: ValidationStats | None = None) -> str:
    if is_missing(value):
        return NA
    text = str(value).strip()
    lowered = text.lower()
    if text in SOURCE_TYPES:
        return text
    if lowered in {"literature", "scientific_paper", "paper", "journal", "peer-reviewed"}:
        if stats and text != "Literature":
            stats.invalid_source_type_corrected += 1
        return "Literature"
    if lowered in {"web", "internet", "website", "online"}:
        if stats and text != "Web":
            stats.invalid_source_type_corrected += 1
        return "Web"
    if stats:
        stats.invalid_source_type_corrected += 1
        stats.warnings.append(f"Invalid source_type normalized to {NA}: {text[:80]!r}")
    return NA


def normalize_metric_dimension(value: object, stats: ValidationStats | None = None) -> str:
    if is_missing(value):
        return NA
    text = str(value).strip()
    if text in METRIC_DIMENSIONS:
        return text
    lowered = text.lower()
    if lowered in METRIC_DIMENSION_ALIASES:
        if stats and text != METRIC_DIMENSION_ALIASES[lowered]:
            stats.invalid_metric_dimension_corrected += 1
        return METRIC_DIMENSION_ALIASES[lowered]
    for option in METRIC_DIMENSIONS:
        if option != NA and option.lower() == lowered:
            return option
    if stats:
        stats.invalid_metric_dimension_corrected += 1
        stats.warnings.append(f"Invalid metric_dimension normalized to {NA}: {text[:80]!r}")
    return NA


def normalize_project_year(value: object, stats: ValidationStats | None = None) -> str:
    if is_missing(value):
        return NA
    text = str(value).strip()
    if re.fullmatch(r"20\d{2}|19\d{2}", text):
        return text
    match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if match:
        year = match.group(1)
        if stats and year != text:
            stats.invalid_project_year_corrected += 1
        return year
    if stats:
        stats.invalid_project_year_corrected += 1
        stats.warnings.append(f"Invalid project_year normalized to {NA}: {text[:80]!r}")
    return NA


def _concise_field(value: object, *, max_words: int = 12) -> str:
    text = normalize_missing(value)
    if text == NA:
        return NA
    text = re.sub(r"\s+", " ", text).strip()
    # Strip trailing explanatory clauses for short categorical fields.
    text = re.split(r"[.;]\s+", text, maxsplit=1)[0].strip()
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])
    return text or NA


def _concise_phrase_list(value: object) -> str:
    text = normalize_missing(value)
    if text == NA:
        return NA
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 120:
        text = text[:120].rsplit(",", 1)[0]
    return text


def _concise_metric_value(value: object) -> str:
    text = normalize_missing(value)
    if text == NA:
        return NA
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return match.group(0) if match else text[:40]


def _concise_metric_with_unit(value: object) -> str:
    text = normalize_missing(value)
    if text == NA:
        return NA
    text = re.sub(r"\s+", " ", text).strip()
    return text[:60]


METRIC_NAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"total investment|investment cost", re.I), "total investment"),
    (re.compile(r"\bcapex\b", re.I), "CAPEX"),
    (re.compile(r"\bopex\b|operating cost", re.I), "OPEX"),
    (re.compile(r"cost of capture", re.I), "cost of capture"),
    (re.compile(r"energy penalty|regeneration energy", re.I), "energy penalty"),
    (re.compile(r"co2 capture rate|capture rate", re.I), "CO2 capture rate"),
    (re.compile(r"co2 captured per year", re.I), "CO2 captured per year"),
    (re.compile(r"project budget", re.I), "project budget"),
    (re.compile(r"ghg emissions reduction|greenhouse gas emissions reduction", re.I), "GHG emissions reduction"),
)

TRAILING_UNIT_PATTERN = re.compile(
    r"\s+(GJ/tCO2|kWh/tCO2|RMB|USD|EUR|DKK|GBP|CNY|\$|€|%|tCO2|tonnes?)\s*$",
    re.I,
)

DEFAULT_METRIC_NAME_BY_DIMENSION: dict[str, str] = {
    "Cost": "total investment",
    "Energy": "energy penalty",
    "CO2 Reduction": "CO2 capture rate",
    "Other": "project budget",
}


def _normalize_metric_value_text(value: object) -> str:
    text = normalize_missing(value)
    if text == NA:
        return NA
    text = re.sub(r"\s+", " ", text).strip()
    return text[:60]


def _split_metric_value_and_unit(value: str, unit: str) -> tuple[str, str]:
    if value == NA:
        return NA, unit if unit != NA else NA
    text = value.strip()
    if unit != NA:
        return _normalize_metric_value_text(text), _concise_field(unit, max_words=4)

    match = TRAILING_UNIT_PATTERN.search(text)
    if match:
        unit_text = match.group(1).strip()
        value_text = text[: match.start()].strip()
        return _normalize_metric_value_text(value_text), _concise_field(unit_text, max_words=4)

    return _normalize_metric_value_text(text), NA


def _infer_metric_name(row: dict[str, str]) -> str:
    existing = row.get("metric_name", NA)
    if existing != NA:
        return _concise_field(existing)

    if row.get("metric_value", NA) == NA:
        return NA

    text_blob = " ".join(
        [
            row.get("cost_impact", ""),
            row.get("energy_impact", ""),
            row.get("co2_reduction", ""),
            row.get("metric_boundary", ""),
            row.get("notes", ""),
        ],
    )
    for pattern, name in METRIC_NAME_PATTERNS:
        if pattern.search(text_blob):
            return name

    dimension = row.get("metric_dimension", NA)
    return DEFAULT_METRIC_NAME_BY_DIMENSION.get(dimension, NA)


def _sync_summary_and_metric_fields(row: dict[str, str]) -> dict[str, str]:
    """Keep summary impact fields and metric triplet aligned without merging prose."""
    dimension = row.get("metric_dimension", NA)
    value = row.get("metric_value", NA)
    unit = row.get("metric_unit", NA)
    if value == NA:
        return row

    combined = f"{value} {unit}".strip() if unit != NA else value
    if dimension == "CO2 Reduction" and row.get("co2_reduction", NA) == NA:
        row["co2_reduction"] = _concise_metric_with_unit(combined)
    elif dimension == "Energy" and row.get("energy_impact", NA) == NA:
        row["energy_impact"] = _concise_metric_with_unit(combined)
    elif dimension == "Cost" and row.get("cost_impact", NA) == NA:
        row["cost_impact"] = _concise_metric_with_unit(combined)

    if row.get("metric_value", NA) == NA:
        for field, dimension_name in (
            ("co2_reduction", "CO2 Reduction"),
            ("energy_impact", "Energy"),
            ("cost_impact", "Cost"),
        ):
            summary = row.get(field, NA)
            if summary == NA:
                continue
            row["metric_dimension"] = dimension_name
            row["metric_value"], row["metric_unit"] = _split_metric_value_and_unit(summary, NA)
            break

    return row


def _finalize_metric_fields(row: dict[str, str], stats: ValidationStats | None = None) -> dict[str, str]:
    value, unit = _split_metric_value_and_unit(row.get("metric_value", NA), row.get("metric_unit", NA))
    if (
        stats
        and row.get("metric_value", NA) != NA
        and (value != row.get("metric_value", NA) or unit != row.get("metric_unit", NA))
    ):
        stats.metric_value_unit_split += 1
    row["metric_value"] = value
    row["metric_unit"] = unit

    inferred_name = _infer_metric_name(row)
    if row.get("metric_name", NA) == NA and inferred_name != NA:
        row["metric_name"] = inferred_name
        if stats:
            stats.missing_metric_name_inferred += 1

    row = _sync_summary_and_metric_fields(row)
    return row


def map_legacy_keys(raw: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for key, value in raw.items():
        canonical_key = LEGACY_FIELD_MAP.get(key, key)
        if canonical_key in mapped and not is_missing(mapped[canonical_key]):
            continue
        mapped[canonical_key] = value
    return mapped


def detect_duplicate_columns(keys: list[str]) -> list[str]:
    canonical_present = {key for key in keys if key in CANONICAL_FIELDS}
    duplicates: list[str] = []
    duplicate_pairs = (
        ("deployment_stage", "current deployment stage"),
        ("co2_reduction", "co2 reduction"),
        ("cost_impact", "cost impact"),
        ("energy_impact", "energy impact"),
        ("technology_type", "technology type"),
        ("company_or_organization", "company"),
        ("project_year", "year"),
        ("project_location", "location"),
        ("metric_value", "value"),
        ("metric_unit", "unit"),
        ("metric_boundary", "boundary"),
        ("metric_name", "metric name"),
        ("source_type", "source"),
        ("source_title", "title"),
        ("source_url_or_citation", "url"),
        ("source_url_or_citation", "citation"),
    )
    lowered = {key.lower(): key for key in keys}
    for canonical, fragment in duplicate_pairs:
        if canonical not in canonical_present:
            continue
        for key in keys:
            if key == canonical:
                continue
            if fragment in key.lower() and len(key) > len(canonical) + 5:
                duplicates.append(key)
    for legacy, canonical in LEGACY_FIELD_MAP.items():
        if legacy in keys and canonical in keys:
            duplicates.append(legacy)
    return sorted(set(duplicates))


def empty_canonical_row() -> dict[str, str]:
    return {field: NA for field in CANONICAL_FIELDS}


def validate_and_normalize_row(
    raw: dict[str, Any],
    *,
    stats: ValidationStats | None = None,
) -> dict[str, str]:
    """Normalize one canonical output row."""
    local_stats = stats or ValidationStats()
    mapped = map_legacy_keys(raw)
    row = empty_canonical_row()

    for field in CANONICAL_FIELDS:
        value = mapped.get(field)
        if is_missing(value):
            row[field] = NA
            if value is not None and str(value).strip():
                local_stats.missing_values_normalized += 1
            continue
        if field == "confidence":
            row[field] = normalize_confidence(value, local_stats)
        elif field == "deployment_stage":
            row[field] = normalize_deployment_stage(value, local_stats)
        elif field == "source_type":
            row[field] = normalize_source_type(value, local_stats)
        elif field == "metric_dimension":
            row[field] = normalize_metric_dimension(value, local_stats)
        elif field == "project_year":
            row[field] = normalize_project_year(value, local_stats)
        elif field in {"metric_value"}:
            row[field] = _normalize_metric_value_text(value)
        elif field in {"metric_unit"}:
            row[field] = _concise_field(value, max_words=4)
        elif field in {"co2_reduction", "energy_impact", "cost_impact"}:
            row[field] = _concise_metric_with_unit(value)
        elif field == "primary_barriers":
            row[field] = _concise_phrase_list(value)
        elif field in {
            "technology_type",
            "company_or_organization",
            "project_name",
            "project_location",
            "metric_name",
            "metric_boundary",
            "source_title",
        }:
            row[field] = _concise_field(value)
        elif field == "notes":
            row[field] = normalize_missing(value) if not is_missing(value) else NA
        else:
            row[field] = normalize_missing(value)

    local_stats.records_processed += 1
    row = _finalize_metric_fields(row, local_stats)
    if row.get("metric_value", NA) != NA and row.get("metric_name", NA) == NA:
        local_stats.warnings.append(
            "metric_value present without metric_name after normalization",
        )
    return row


PROJECT_IDENTITY_FIELDS: tuple[str, ...] = (
    "category",
    "subcategory",
    "technology_type",
    "company_or_organization",
    "project_name",
    "project_year",
    "project_location",
    "deployment_stage",
    "primary_barriers",
    "source_type",
    "source_title",
    "source_url_or_citation",
    "confidence",
    "notes",
    "co2_reduction",
    "energy_impact",
    "cost_impact",
)


def _metric_has_data(metric: dict[str, Any]) -> bool:
    return any(
        not is_missing(metric.get(field))
        for field in ("metric_dimension", "metric_name", "metric_value", "metric_unit")
    )


def expand_record_to_rows(
    raw_record: dict[str, Any],
    *,
    stats: ValidationStats | None = None,
) -> list[dict[str, str]]:
    """
    Expand one LLM record into canonical rows.

    Each LLM record represents one project or one technology (when no project exists).
    Additional rows are created only for extra metrics on the same project/technology.
    """
    base = map_legacy_keys(raw_record)
    metrics = base.pop("metrics", None)
    if not isinstance(metrics, list):
        metrics = []

    normalized_metrics = [item for item in metrics if isinstance(item, dict) and _metric_has_data(item)]
    if not normalized_metrics:
        return [validate_and_normalize_row(base, stats=stats)]

    project_identity = {field: base.get(field, NA) for field in PROJECT_IDENTITY_FIELDS}
    rows: list[dict[str, str]] = []

    for index, metric in enumerate(normalized_metrics):
        if index == 0:
            merged = {**base, **metric}
        else:
            merged = {**project_identity, **metric}
        row = validate_and_normalize_row(merged, stats=stats)
        rows.append(row)

    return rows


def expand_llm_payload(
    payload: dict[str, Any],
    *,
    stats: ValidationStats | None = None,
) -> list[dict[str, str]]:
    """Expand LLM JSON payload into validated canonical rows."""
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        return []

    rows: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        rows.extend(expand_record_to_rows(record, stats=stats))
    return rows


def strip_non_canonical_keys(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    duplicates = detect_duplicate_columns(list(raw.keys()))
    cleaned = {key: value for key, value in raw.items() if key not in duplicates}
    return cleaned, duplicates
