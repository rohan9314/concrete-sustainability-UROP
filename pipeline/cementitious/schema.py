"""Canonical Cementitious Materials evidence schema and validators."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from pipeline.cementitious import CATEGORY_DISPLAY, SCHEMA_VERSION, TAXONOMY_VERSION
from pipeline.cementitious.taxonomy import Taxonomy, get_taxonomy

# Blank CSV / null JSON is the missing-value convention for this pipeline.
MISSING = ""

CONFIDENCE_LEVELS = ("High", "Medium", "Low")
CLASSIFICATION_BASIS = ("Explicit", "Strongly Inferred", "Weakly Inferred", "Unresolved")
DUPLICATE_STATUSES = (
    "Unique",
    "Exact Duplicate Removed",
    "Possible Duplicate",
    "Consolidated",
)

RECORD_FIELDS: tuple[str, ...] = (
    # Core identity
    "record_id",
    "category",
    "subcategory",
    "subcategory_slug",
    "sub_subcategory",
    "sub_subcategory_slug",
    "taxonomy_level_0",
    "taxonomy_level_0_slug",
    "taxonomy_level_1",
    "taxonomy_level_1_slug",
    "taxonomy_level_2",
    "taxonomy_level_2_slug",
    "taxonomy_level_3",
    "taxonomy_level_3_slug",
    "taxonomy_level_4",
    "taxonomy_level_4_slug",
    "technology_variant",
    "canonical_technology_name",
    "raw_technology_name",
    "taxonomy_version",
    "taxonomy_confidence",
    "classification_basis",
    "classification_reasoning",
    "alternative_classification",
    # Role and source
    "technology_domain",
    "material_or_process",
    "functional_role",
    "feedstock_or_input",
    "source_industry",
    "production_process",
    "collection_form",
    "recovery_status",
    "processing_status",
    "processing_methods",
    "activation_method",
    "activator_type",
    # Study and project
    "company_or_organization",
    "project_name",
    "deployment_stage",
    "location",
    "country",
    "project_year",
    "study_type",
    "material_source_location",
    # Performance
    "cement_replacement_percentage",
    "cement_replacement_min_percentage",
    "cement_replacement_max_percentage",
    "clinker_reduction_percentage",
    "optimum_replacement_percentage",
    "replacement_basis",
    "control_mix_description",
    "water_binder_ratio",
    "binder_content",
    "curing_conditions",
    "testing_age_days",
    "compressive_strength_value",
    "compressive_strength_unit",
    "compressive_strength_change_percentage",
    "strength_activity_index",
    "durability_impact",
    "workability_impact",
    # Carbon, energy, cost
    "co2_reduction_value",
    "co2_reduction_unit",
    "co2_reduction_percentage",
    "lifecycle_boundary",
    "functional_unit",
    "embodied_carbon_value",
    "embodied_carbon_unit",
    "carbon_capture_rate",
    "carbon_capture_capacity",
    "carbon_capture_capacity_unit",
    "co2_purity_percentage",
    "energy_impact",
    "energy_penalty_value",
    "energy_penalty_unit",
    "process_temperature",
    "process_temperature_unit",
    "cost_impact",
    "cost_value",
    "cost_unit",
    # Blend fields
    "binder_components_json",
    "binder_component_1",
    "binder_component_1_fraction",
    "binder_component_2",
    "binder_component_2_fraction",
    "binder_component_3",
    "binder_component_3_fraction",
    "binder_component_4",
    "binder_component_4_fraction",
    # Evidence / provenance
    "evidence_origin",
    "source_id",
    "source_type",
    "source_title",
    "authors",
    "publication_year",
    "journal_or_site",
    "doi",
    "source_url",
    "normalized_url",
    "final_resolved_url",
    "domain",
    "web_source_id",
    "query_ids",
    "query_texts",
    "retrieval_timestamp",
    "content_source",
    "organization_or_publisher",
    "citation",
    "evidence_text",
    "evidence_page_or_section",
    "extraction_confidence",
    "notes",
    # Cross-origin linking
    "evidence_group_id",
    "related_record_ids",
    "same_project_candidate",
    "same_technology_candidate",
    # Dedup
    "duplicate_group_id",
    "duplicate_status",
    "duplicate_reason",
)

CITATION_FIELDS: tuple[str, ...] = (
    "record_id",
    "category",
    "subcategory",
    "subcategory_slug",
    "sub_subcategory",
    "sub_subcategory_slug",
    "technology_variant",
    "evidence_origin",
    "source_id",
    "source_type",
    "source_title",
    "authors",
    "publication_year",
    "journal_or_site",
    "doi",
    "source_url",
    "normalized_url",
    "retrieval_timestamp",
    "citation",
    "evidence_text",
    "evidence_page_or_section",
    "extraction_confidence",
)

EVIDENCE_ORIGINS = ("Literature", "Web")
WEB_SOURCE_TYPES = (
    "Company Website",
    "Government Website",
    "Academic Institution",
    "Standards Organization",
    "Industry Association",
    "News",
    "Conference or Project Website",
    "Technical Report",
    "Other Web Source",
    "Academic Literature",
)

PROPOSAL_FIELDS: tuple[str, ...] = (
    "raw_term",
    "proposed_canonical_name",
    "proposed_level",
    "proposed_parent",
    "definition",
    "source_record_id",
    "source_title",
    "evidence_text",
    "reason_existing_taxonomy_is_insufficient",
    "suggested_synonyms",
    "confidence",
    "review_status",
)

FORBIDDEN_MISSING_STRINGS: frozenset[str] = frozenset(
    {
        "n/a",
        "na",
        "n.a.",
        "n.a",
        "unknown",
        "not found",
        "unavailable",
        "not reported",
        "none",
        "null",
        "no data",
    }
)

CONFIDENCE_ALIASES = {
    "high": "High",
    "medium": "Medium",
    "med": "Medium",
    "low": "Low",
}


def is_missing(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return text.casefold() in FORBIDDEN_MISSING_STRINGS


def normalize_missing(value: object) -> str:
    if is_missing(value):
        return MISSING
    return str(value).strip()


def normalize_confidence(value: object) -> str:
    if is_missing(value):
        return MISSING
    text = str(value).strip()
    mapped = CONFIDENCE_ALIASES.get(text.casefold())
    if mapped:
        return mapped
    if text in CONFIDENCE_LEVELS:
        return text
    return MISSING


def empty_record() -> dict[str, str]:
    return {key: MISSING for key in RECORD_FIELDS}


def new_record_id(prefix: str = "cm") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def flatten_binder_components(components: list[dict[str, Any]] | None) -> dict[str, str]:
    out = {
        "binder_components_json": MISSING,
        "binder_component_1": MISSING,
        "binder_component_1_fraction": MISSING,
        "binder_component_2": MISSING,
        "binder_component_2_fraction": MISSING,
        "binder_component_3": MISSING,
        "binder_component_3_fraction": MISSING,
        "binder_component_4": MISSING,
        "binder_component_4_fraction": MISSING,
    }
    if not components:
        return out
    out["binder_components_json"] = json.dumps(components, ensure_ascii=False)
    for idx, component in enumerate(components[:4], start=1):
        name = (
            component.get("canonical_component_name")
            or component.get("component_name")
            or MISSING
        )
        frac = component.get("fraction_percent")
        out[f"binder_component_{idx}"] = normalize_missing(name)
        out[f"binder_component_{idx}_fraction"] = (
            MISSING if frac is None or is_missing(frac) else str(frac)
        )
    return out


def citation_from_record(record: dict[str, Any]) -> dict[str, str]:
    return {key: normalize_missing(record.get(key)) for key in CITATION_FIELDS}


@dataclass
class RecordValidationResult:
    accepted: list[dict[str, str]] = field(default_factory=list)
    invalid_taxonomy: list[dict[str, str]] = field(default_factory=list)
    missing_taxonomy: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def normalize_record(
    raw: dict[str, Any],
    *,
    taxonomy: Taxonomy | None = None,
    fill_defaults: bool = True,
) -> dict[str, str]:
    tax = taxonomy or get_taxonomy()
    record = empty_record()
    for key in RECORD_FIELDS:
        if key in raw:
            record[key] = normalize_missing(raw.get(key))
    if fill_defaults:
        if not record["taxonomy_version"]:
            record["taxonomy_version"] = tax.taxonomy_version or TAXONOMY_VERSION
        if not record["record_id"]:
            record["record_id"] = new_record_id()
        if not record["duplicate_status"]:
            record["duplicate_status"] = "Unique"
        record["taxonomy_confidence"] = normalize_confidence(record.get("taxonomy_confidence"))
        record["extraction_confidence"] = normalize_confidence(
            record.get("extraction_confidence")
        )
        # Resolve display/slug pairs when one side is present
        if record["subcategory_slug"] and not record["subcategory"]:
            node = tax.subcategories.get(record["subcategory_slug"])
            if node:
                record["subcategory"] = node.display_name
        if record["subcategory"] and not record["subcategory_slug"]:
            try:
                record["subcategory_slug"] = tax.resolve_slug(
                    record["subcategory"], level="subcategory"
                )
            except ValueError:
                pass
        if record["sub_subcategory_slug"] and not record["sub_subcategory"]:
            node = tax.sub_subcategories.get(record["sub_subcategory_slug"])
            if node:
                record["sub_subcategory"] = node.display_name
        if record["sub_subcategory"] and not record["sub_subcategory_slug"]:
            try:
                record["sub_subcategory_slug"] = tax.resolve_slug(
                    record["sub_subcategory"], level="sub_subcategory"
                )
            except ValueError:
                pass
        if not record["canonical_technology_name"]:
            record["canonical_technology_name"] = (
                record["technology_variant"] or record["raw_technology_name"]
            )
        from pipeline.cementitious.taxonomy_migration import apply_decarbonization_path

        filled = apply_decarbonization_path(record, runtime=tax)
        for key in RECORD_FIELDS:
            if key.startswith("taxonomy_level_"):
                record[key] = filled.get(key) or record.get(key) or ""
        if not record.get("sub_subcategory_slug") and record.get("taxonomy_level_1"):
            from pipeline.cementitious.decarbonization_taxonomy import (
                get_decarbonization_taxonomy,
            )
            from pipeline.cementitious.paths import is_taxonomy_na
            from pipeline.cementitious.taxonomy_migration import (
                runtime_assignment_for_decarb_node,
            )

            labels = [
                str(record.get(f"taxonomy_level_{i}") or "")
                for i in range(5)
                if str(record.get(f"taxonomy_level_{i}") or "")
                and not is_taxonomy_na(str(record.get(f"taxonomy_level_{i}") or ""))
            ]
            if len(labels) >= 2:
                try:
                    node = get_decarbonization_taxonomy().resolve_path_labels(labels)
                    assignment = runtime_assignment_for_decarb_node(node, runtime=tax)
                    if assignment:
                        for key, value in assignment.items():
                            if not record.get(key):
                                record[key] = value
                except ValueError:
                    pass
        if not record["category"]:
            if record.get("taxonomy_level_1") and record["taxonomy_level_1"] not in {
                "",
                "N.A.",
            }:
                record["category"] = record["taxonomy_level_1"]
            else:
                record["category"] = tax.category_display
    # Normalize binder JSON if provided as list
    components = raw.get("binder_components")
    if components and isinstance(components, list):
        record.update(flatten_binder_components(components))
    elif record.get("binder_components_json") and not record.get("binder_component_1"):
        try:
            parsed = json.loads(record["binder_components_json"])
            if isinstance(parsed, list):
                record.update(flatten_binder_components(parsed))
        except json.JSONDecodeError:
            pass
    # Preserve optional one-to-many citation payloads (not part of RECORD_FIELDS /
    # the flat CSV schema) so export partitioning can still expand them; JSON/JSONL
    # inputs can carry these as real lists, CSV inputs cannot.
    for extra_key in ("citations", "citation_entries"):
        value = raw.get(extra_key)
        if isinstance(value, list) and value:
            record[extra_key] = value
    return record


def validate_records(
    records: list[dict[str, Any]],
    *,
    taxonomy: Taxonomy | None = None,
) -> RecordValidationResult:
    tax = taxonomy or get_taxonomy()
    result = RecordValidationResult()
    seen_ids: set[str] = set()
    for raw in records:
        record = normalize_record(raw, taxonomy=tax)
        has_old = bool(record.get("subcategory_slug") and record.get("sub_subcategory_slug"))
        has_new = bool(record.get("taxonomy_level_1")) and record.get("taxonomy_level_1") not in {
            "",
            "N.A.",
        }
        if has_old or not has_new:
            required = [
                record["category"],
                record["subcategory"],
                record["subcategory_slug"],
                record["sub_subcategory"],
                record["sub_subcategory_slug"],
                record["taxonomy_version"],
                record["record_id"],
            ]
            if any(is_missing(v) for v in required):
                result.missing_taxonomy.append(record)
                continue
            errors = tax.validate_assignment(
                category=record["category"],
                subcategory=record["subcategory"],
                subcategory_slug=record["subcategory_slug"],
                sub_subcategory=record["sub_subcategory"],
                sub_subcategory_slug=record["sub_subcategory_slug"],
            )
        else:
            if is_missing(record["record_id"]) or is_missing(record.get("taxonomy_level_0")):
                result.missing_taxonomy.append(record)
                continue
            errors = []
            try:
                from pipeline.cementitious.decarbonization_taxonomy import (
                    get_decarbonization_taxonomy,
                )

                labels = [
                    record.get(f"taxonomy_level_{i}") or ""
                    for i in range(5)
                    if record.get(f"taxonomy_level_{i}") not in {"", "N.A.", None}
                ]
                get_decarbonization_taxonomy().resolve_path_labels(labels)
            except ValueError as exc:
                errors.append(str(exc))
        if record["record_id"] in seen_ids:
            errors.append(f"duplicate record_id: {record['record_id']}")
        seen_ids.add(record["record_id"])
        if (
            not record["source_id"]
            and not record["citation"]
            and not record.get("source_url")
            and not record.get("citations")
            and not record.get("citation_entries")
        ):
            # Soft: accepted for partition export; MissingCitationError enforced there.
            record["notes"] = (
                (record["notes"] + " | " if record["notes"] else "")
                + "validation: missing source_id and citation"
            )
            result.errors.append(f"missing source_id and citation ({record['record_id']})")
        if record["taxonomy_confidence"] and record["taxonomy_confidence"] not in CONFIDENCE_LEVELS:
            errors.append(f"invalid taxonomy_confidence: {record['taxonomy_confidence']}")
        if (
            record["extraction_confidence"]
            and record["extraction_confidence"] not in CONFIDENCE_LEVELS
        ):
            errors.append(f"invalid extraction_confidence: {record['extraction_confidence']}")
        if errors:
            record["notes"] = (
                (record["notes"] + " | " if record["notes"] else "")
                + "validation: "
                + "; ".join(errors)
            )
            result.invalid_taxonomy.append(record)
            result.errors.extend(errors)
            continue
        result.accepted.append(record)
    return result


RECORD_SORT_KEYS = (
    "taxonomy_level_1_slug",
    "taxonomy_level_2_slug",
    "taxonomy_level_3_slug",
    "taxonomy_level_4_slug",
    "subcategory_slug",
    "sub_subcategory_slug",
    "canonical_technology_name",
    "publication_year",
    "source_title",
    "record_id",
)

CITATION_SORT_KEYS = (
    "subcategory_slug",
    "sub_subcategory_slug",
    "record_id",
    "source_id",
)


def sort_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    def key_fn(row: dict[str, str]) -> tuple:
        return tuple(str(row.get(k) or "") for k in RECORD_SORT_KEYS)

    return sorted(records, key=key_fn)


def sort_citations(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    def key_fn(row: dict[str, str]) -> tuple:
        return tuple(str(row.get(k) or "") for k in CITATION_SORT_KEYS)

    return sorted(rows, key=key_fn)


YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def schema_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "category": CATEGORY_DISPLAY,
        "record_fields": list(RECORD_FIELDS),
        "citation_fields": list(CITATION_FIELDS),
        "proposal_fields": list(PROPOSAL_FIELDS),
        "missing_value_convention": "blank CSV cell / null JSON; taxonomy_level_* uses N.A. when a deeper level is unclassified",
        "confidence_levels": list(CONFIDENCE_LEVELS),
        "classification_basis": list(CLASSIFICATION_BASIS),
        "duplicate_statuses": list(DUPLICATE_STATUSES),
    }
