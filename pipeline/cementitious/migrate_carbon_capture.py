"""Deterministic migration of existing carbon-capture outputs into the new taxonomy."""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.cementitious import CATEGORY_DISPLAY, TAXONOMY_VERSION
from pipeline.cementitious.export_partitions import write_pending_taxonomy_review
from pipeline.cementitious.paths import ensure_730_layout
from pipeline.cementitious.schema import (
    PROPOSAL_FIELDS,
    RECORD_FIELDS,
    normalize_missing,
    normalize_record,
    new_record_id,
)
from pipeline.cementitious.taxonomy import get_taxonomy

logger = logging.getLogger(__name__)

SUBCATEGORY = "Cement-Plant Carbon Capture"
SUBCATEGORY_SLUG = "cement_plant_carbon_capture"

EMERGING_SCM_SUBCATEGORY = "Emerging Supplementary Cementitious Materials"
EMERGING_SCM_SUBCATEGORY_SLUG = "emerging_supplementary_cementitious_materials"
CARBONATED_WASTE_SCM_SLUG = "carbonated_waste_derived_scms"

PENDING_SUBCATEGORY = "Pending Taxonomy Review"
PENDING_SUBCATEGORY_SLUG = "pending_taxonomy_review"

# Map legacy CCS methodology slugs / labels → new sub-subcategory slugs
DETERMINISTIC_MAPPINGS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"chemical[_\s-]*absorption|amine|solvent[- ]based|non[- ]aqueous\s+solvent|"
            r"mea\b|monoethanolamine|post[- ]combustion\s+solvent",
            re.I,
        ),
        "chemical_absorption",
    ),
    (
        re.compile(r"cryogenic|cryogen", re.I),
        "cryogenic_carbon_capture",
    ),
    (
        re.compile(r"oxy[-_]?fuel|oxygen[- ]enriched\s+combustion|oxyfuel", re.I),
        "oxy_fuel_combustion",
    ),
    (
        re.compile(r"membrane", re.I),
        "membrane_separation",
    ),
    (
        re.compile(r"calcium[_\s-]*looping|ca[-_ ]?looping|\bcal\b", re.I),
        "calcium_looping",
    ),
    (
        re.compile(r"direct[_\s-]*separation|leilac", re.I),
        "direct_separation",
    ),
]

SLUG_ALIASES: dict[str, str] = {
    "amine_absorption": "chemical_absorption",
    "chemical_absorption": "chemical_absorption",
    "cryogenic_capture": "cryogenic_carbon_capture",
    "cryogenic_carbon_capture": "cryogenic_carbon_capture",
    "oxyfuel_combustion": "oxy_fuel_combustion",
    "oxy_fuel_combustion": "oxy_fuel_combustion",
    "membrane_separation": "membrane_separation",
    "calcium_looping": "calcium_looping",
    "direct_separation": "direct_separation",
}

MINERALIZATION_KEYS = frozenset(
    {
        "mineralization",
        "mineral_carbonation",
        "carbon_mineralization",
        "co2_mineralization",
        "carbonation_curing",
        "co2_curing",
        "mineral_sequestration",
        "carbonation_based_capture",
    }
)

SCM_COMPATIBLE_PATTERN = re.compile(
    r"\bscm\b|supplementary\s+cementitious|cement\s+replacement|"
    r"binder\s+replacement|pozzolan(?:ic)?|clinker\s+substitut|"
    r"partial(?:ly)?\s+replac(?:e|ement)|cementitious\s+addition|"
    r"reactive\s+cementitious|carbonated\s+(?:waste|slag|fly\s+ash|ckd|"
    r"tailings).{0,40}(?:scm|cement\s+replacement|binder)",
    re.I,
)

NON_SCM_MINERALIZATION_PATTERN = re.compile(
    r"aggregate\s+only|soil\s+amendment|road\s+base|"
    r"(?:only\s+)?(?:co2|carbonation)\s+curing(?:\s+only)?|"
    r"curing\s+only|sequestration\s+only|storage\s+only|"
    r"not\s+(?:an?\s+)?scm|without\s+cement\s+replacement",
    re.I,
)

EXPLICIT_SCM_ROLES = frozenset(
    {
        "cement replacement",
        "pozzolanic scm",
        "scm",
        "supplementary cementitious material",
        "binder replacement",
        "clinker substitute",
    }
)


@dataclass
class MigrationResult:
    """Outcome of migrating one legacy CCS row."""

    status: str  # migrated | pending_review | invalid
    record: dict[str, str] | None = None
    proposal: dict[str, str] | None = None
    legacy_mineralization: dict[str, Any] | None = None
    original: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def map_sub_subcategory(
    *,
    methodology_slug: str = "",
    subcategory: str = "",
    technology_type: str = "",
    text_blob: str = "",
) -> str | None:
    """Return new plant-capture sub-subcategory slug or None if unmapped.

    Mineralization is intentionally never mapped into the six plant-capture nodes.
    """
    for candidate in (methodology_slug, subcategory):
        key = _norm_key(candidate)
        if key in MINERALIZATION_KEYS:
            return None
        if key in SLUG_ALIASES:
            return SLUG_ALIASES[key]
    blob = " ".join(
        part for part in (methodology_slug, subcategory, technology_type, text_blob) if part
    )
    # Do not let "mineralization" text fall through into other patterns
    if _is_mineralization_blob(methodology_slug, subcategory, technology_type, text_blob):
        return None
    for pattern, slug in DETERMINISTIC_MAPPINGS:
        if pattern.search(blob):
            return slug
    return None


def _norm_key(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _is_mineralization_blob(
    methodology_slug: str = "",
    subcategory: str = "",
    technology_type: str = "",
    text_blob: str = "",
) -> bool:
    for candidate in (methodology_slug, subcategory, technology_type):
        if _norm_key(candidate) in MINERALIZATION_KEYS:
            return True
    blob = f"{methodology_slug} {subcategory} {technology_type} {text_blob}".casefold()
    return bool(
        re.search(
            r"mineralization|mineral\s+carbonation|carbonation\s+curing|\bco2\s+curing\b|"
            r"co2\s+mineralization|carbon\s+mineralization",
            blob,
        )
    )


def is_mineralization_record(
    raw: dict[str, Any],
    *,
    methodology_slug: str = "",
) -> bool:
    return _is_mineralization_blob(
        methodology_slug or str(raw.get("methodology_slug") or raw.get("methodology") or ""),
        str(raw.get("subcategory") or ""),
        str(raw.get("technology_type") or raw.get("technology_name") or ""),
        " ".join(
            str(raw.get(k) or "")
            for k in ("notes", "source_title", "evidence_text", "category", "functional_role")
        ),
    )


def _context_blob(raw: dict[str, Any]) -> str:
    return " ".join(
        str(raw.get(k) or "")
        for k in (
            "functional_role",
            "notes",
            "evidence_text",
            "source_title",
            "technology_type",
            "technology_name",
            "category",
            "descriptor",
            "material_or_process",
            "metric_name",
        )
    )


def mineralization_is_scm_compatible(raw: dict[str, Any]) -> bool:
    """
    True only when the source describes a carbonated material used as an SCM
    or cement replacement. Oxides alone are never enough.
    """
    role = str(raw.get("functional_role") or "").strip().casefold()
    blob = _context_blob(raw)
    if role and role in EXPLICIT_SCM_ROLES:
        # Explicit SCM role wins unless strongly contradicted
        if NON_SCM_MINERALIZATION_PATTERN.search(blob) and not SCM_COMPATIBLE_PATTERN.search(blob):
            return False
        return True
    if SCM_COMPATIBLE_PATTERN.search(blob):
        if NON_SCM_MINERALIZATION_PATTERN.search(blob) and not re.search(
            r"cement\s+replacement|binder\s+replacement|\bscm\b", blob, re.I
        ):
            return False
        return True
    return False


def _preserve_identifiers(raw: dict[str, Any]) -> dict[str, str]:
    record_id = normalize_missing(raw.get("record_id")) or ""
    source_id = normalize_missing(raw.get("source_id")) or ""
    citation = (
        normalize_missing(raw.get("source_url_or_citation"))
        or normalize_missing(raw.get("citation"))
        or normalize_missing(raw.get("source_url"))
        or ""
    )
    source_url = normalize_missing(raw.get("source_url")) or ""
    return {
        "record_id": record_id,
        "source_id": source_id,
        "citation": citation,
        "source_url": source_url,
        "source_title": normalize_missing(raw.get("source_title")) or "",
        "source_type": normalize_missing(raw.get("source_type")) or "",
    }


def _base_fields_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    ids = _preserve_identifiers(raw)
    technology_type = str(raw.get("technology_type") or raw.get("technology_name") or "")
    co2_value = raw.get("co2_reduction") or raw.get("metric_value") or ""
    co2_unit = raw.get("metric_unit") or ""
    if raw.get("metric_dimension") and str(raw.get("metric_dimension")).lower().startswith("co2"):
        co2_value = raw.get("metric_value") or co2_value
        co2_unit = raw.get("metric_unit") or co2_unit
    return {
        **ids,
        "record_id": ids["record_id"] or new_record_id("ccs_mig"),
        "taxonomy_version": TAXONOMY_VERSION,
        "taxonomy_confidence": raw.get("confidence") or "Medium",
        "classification_basis": "Explicit",
        "technology_variant": technology_type,
        "canonical_technology_name": technology_type,
        "raw_technology_name": technology_type,
        "company_or_organization": raw.get("company_or_organization") or raw.get("company") or "",
        "project_name": raw.get("project_name") or "",
        "deployment_stage": raw.get("deployment_stage") or "",
        "location": raw.get("project_location") or raw.get("location") or "",
        "project_year": raw.get("project_year") or "",
        "co2_reduction_value": co2_value,
        "co2_reduction_unit": co2_unit,
        "lifecycle_boundary": raw.get("metric_boundary") or "",
        "energy_impact": raw.get("energy_impact") or "",
        "cost_impact": raw.get("cost_impact") or "",
        "evidence_text": raw.get("evidence_text") or raw.get("notes") or "",
        "extraction_confidence": raw.get("confidence") or "",
        "notes": raw.get("notes") or "",
        "duplicate_status": "Unique",
        "functional_role": raw.get("functional_role") or "",
        "evidence_origin": raw.get("evidence_origin") or "Literature",
    }


def _legacy_mineralization_row(
    raw: dict[str, Any],
    *,
    migration_status: str,
    reason: str,
) -> dict[str, Any]:
    ids = _preserve_identifiers(raw)
    row = dict(raw)
    row["migration_status"] = migration_status
    row["migration_reason"] = reason
    row["preserved_record_id"] = ids["record_id"]
    row["preserved_source_id"] = ids["source_id"]
    row["preserved_citation"] = ids["citation"]
    row["preserved_source_url"] = ids["source_url"]
    return row


def _migrate_mineralization(raw: dict[str, Any]) -> MigrationResult:
    tax = get_taxonomy()
    scm_compatible = mineralization_is_scm_compatible(raw)
    base = _base_fields_from_raw(raw)
    functional_role = str(raw.get("functional_role") or "").strip()

    if scm_compatible:
        ss_node = tax.sub_subcategories[CARBONATED_WASTE_SCM_SLUG]
        sub_node = tax.subcategories[EMERGING_SCM_SUBCATEGORY_SLUG]
        record = {
            **base,
            "category": CATEGORY_DISPLAY,
            "subcategory": sub_node.display_name,
            "subcategory_slug": EMERGING_SCM_SUBCATEGORY_SLUG,
            "sub_subcategory": ss_node.display_name,
            "sub_subcategory_slug": CARBONATED_WASTE_SCM_SLUG,
            "technology_variant": base["technology_variant"] or ss_node.display_name,
            "canonical_technology_name": base["canonical_technology_name"]
            or ss_node.display_name,
            "classification_reasoning": (
                "Deterministic migration of legacy mineralization record describing "
                "a carbonated material used as an SCM / cement replacement into "
                f"{EMERGING_SCM_SUBCATEGORY} / {ss_node.display_name}."
            ),
            "technology_domain": "Supplementary Cementitious Material",
            "material_or_process": raw.get("material_or_process") or "Material",
            "functional_role": functional_role or "Cement Replacement",
            "alternative_classification": "",
        }
        normalized = normalize_record(record, taxonomy=tax)
        return MigrationResult(
            status="migrated",
            record=normalized,
            proposal=None,
            legacy_mineralization=_legacy_mineralization_row(
                raw,
                migration_status="migrated_scm",
                reason="scm_compatible_carbonated_waste_scm",
            ),
            original=raw,
            reason="scm_compatible_carbonated_waste_scm",
        )

    # Pending taxonomy review — preserved, not rejected, not forced into the six plant nodes
    pending_record = {
        **base,
        "category": CATEGORY_DISPLAY,
        "subcategory": PENDING_SUBCATEGORY,
        "subcategory_slug": PENDING_SUBCATEGORY_SLUG,
        "sub_subcategory": PENDING_SUBCATEGORY,
        "sub_subcategory_slug": PENDING_SUBCATEGORY_SLUG,
        "technology_variant": base["technology_variant"] or "Mineralization",
        "canonical_technology_name": base["canonical_technology_name"] or "Mineralization",
        "taxonomy_confidence": "Low",
        "classification_basis": "Unresolved",
        "classification_reasoning": (
            "Legacy mineralization record preserved for human taxonomy review; "
            "not mapped into Cement-Plant Carbon Capture sub-subcategories."
        ),
        "alternative_classification": "",
        "technology_domain": "Carbon Capture Process",
        "material_or_process": raw.get("material_or_process") or "Process",
        "functional_role": functional_role,
        "notes": (
            (base.get("notes") + " | " if base.get("notes") else "")
            + "Pending Taxonomy Review (legacy mineralization)."
        ),
        "duplicate_status": "Unique",
    }
    # Do not run full taxonomy validation (pending is intentionally outside approved nodes)
    pending_out = {key: normalize_missing(pending_record.get(key)) for key in RECORD_FIELDS}
    for key, value in pending_record.items():
        if key not in pending_out:
            pending_out[key] = normalize_missing(value)

    proposed_parent = EMERGING_SCM_SUBCATEGORY
    proposed_name = base["canonical_technology_name"] or "Mineralization / mineral carbonation"
    proposal = {
        "raw_term": base["raw_technology_name"] or "mineralization",
        "proposed_canonical_name": proposed_name,
        "proposed_level": "sub_subcategory",
        "proposed_parent": proposed_parent,
        "definition": (
            "Legacy CCS mineralization evidence pending human review for taxonomy placement."
        ),
        "source_record_id": pending_out["record_id"],
        "source_title": pending_out.get("source_title") or "",
        "evidence_text": pending_out.get("evidence_text") or "",
        "reason_existing_taxonomy_is_insufficient": (
            "Mineralization is outside the six Cement-Plant Carbon Capture nodes; "
            "SCM-compatible cases map to Carbonated Waste-Derived SCMs, but this "
            "record lacks sufficient SCM / cement-replacement evidence."
            if not functional_role
            else (
                f"Functional role {functional_role!r} did not meet SCM-compatible "
                "criteria for Carbonated Waste-Derived SCMs."
            )
        ),
        "suggested_synonyms": json.dumps(
            ["mineralization", "mineral carbonation", "CO2 mineralization"]
        ),
        "confidence": "Low",
        "review_status": "Pending Review",
        "functional_role": functional_role,
        "proposed_parent_slug": EMERGING_SCM_SUBCATEGORY_SLUG,
    }

    return MigrationResult(
        status="pending_review",
        record=pending_out,
        proposal={k: str(proposal.get(k) or "") for k in list(PROPOSAL_FIELDS) + ["functional_role", "proposed_parent_slug"]},
        legacy_mineralization=_legacy_mineralization_row(
            raw,
            migration_status="pending_taxonomy_review",
            reason="mineralization_outside_plant_capture_pending_review",
        ),
        original=raw,
        reason="mineralization_pending_taxonomy_review",
    )


def migrate_carbon_capture_record(
    raw: dict[str, Any],
    *,
    methodology_slug: str = "",
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """
    Convert one legacy CCS row to the cementitious schema.

    Returns (normalized_record, unmapped_payload) for backward compatibility.
    Prefer migrate_carbon_capture_record_detailed for mineralization handling.
    """
    result = migrate_carbon_capture_record_detailed(raw, methodology_slug=methodology_slug)
    if result.status == "invalid":
        return None, result.original or dict(raw)
    return result.record, None


def migrate_carbon_capture_record_detailed(
    raw: dict[str, Any],
    *,
    methodology_slug: str = "",
) -> MigrationResult:
    """Convert one legacy CCS row with explicit mineralization preservation."""
    if is_mineralization_record(raw, methodology_slug=methodology_slug):
        return _migrate_mineralization(raw)

    tax = get_taxonomy()
    subcategory_legacy = str(
        raw.get("subcategory")
        or raw.get("methodology")
        or raw.get("technology_type")
        or ""
    )
    technology_type = str(raw.get("technology_type") or raw.get("technology_name") or "")
    slug = map_sub_subcategory(
        methodology_slug=methodology_slug
        or str(raw.get("methodology_slug") or raw.get("methodology") or ""),
        subcategory=subcategory_legacy,
        technology_type=technology_type,
        text_blob=" ".join(
            str(raw.get(k) or "")
            for k in ("notes", "source_title", "metric_name", "category", "evidence_text")
        ),
    )
    if not slug or slug not in tax.sub_subcategories:
        return MigrationResult(
            status="invalid",
            record=None,
            proposal=None,
            legacy_mineralization=None,
            original=dict(raw),
            reason="unmapped_non_mineralization",
        )

    ss_node = tax.sub_subcategories[slug]
    sub_node = tax.subcategories[SUBCATEGORY_SLUG]
    base = _base_fields_from_raw(raw)
    record = {
        **base,
        "category": CATEGORY_DISPLAY,
        "subcategory": sub_node.display_name,
        "subcategory_slug": SUBCATEGORY_SLUG,
        "sub_subcategory": ss_node.display_name,
        "sub_subcategory_slug": slug,
        "technology_variant": base["technology_variant"] or ss_node.display_name,
        "canonical_technology_name": base["canonical_technology_name"] or ss_node.display_name,
        "classification_reasoning": (
            "Deterministic migration from existing carbon-capture pipeline output "
            f"into Cement-Plant Carbon Capture / {ss_node.display_name}."
        ),
        "alternative_classification": "",
        "technology_domain": "Carbon Capture Process",
        "material_or_process": "Process",
        "functional_role": raw.get("functional_role") or "Carbon Capture System",
    }
    return MigrationResult(
        status="migrated",
        record=normalize_record(record, taxonomy=tax),
        proposal=None,
        legacy_mineralization=None,
        original=raw,
        reason=f"mapped_{slug}",
    )


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        rows: list[dict[str, Any]] = []
        for csv_path in sorted(path.rglob("*.csv")):
            rows.extend(_load_rows(csv_path))
        for jsonl_path in sorted(path.rglob("*.jsonl")):
            rows.extend(_load_rows(jsonl_path))
        return rows
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    if suffix == ".jsonl":
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict) and payload.get("type", "").endswith("_meta"):
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and "records" in payload:
            return list(payload["records"])
    return []


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def migrate_carbon_capture(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    methodology_slug: str = "",
) -> dict[str, Any]:
    """Migrate CCS results into normalized cementitious records (no LLM)."""
    src = Path(input_path)
    out = Path(output_dir)
    layout = ensure_730_layout(out)
    raw_rows = _load_rows(src)

    migrated: list[dict[str, str]] = []
    pending_review: list[dict[str, str]] = []
    proposals: list[dict[str, str]] = []
    legacy_mineralization: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    for row in raw_rows:
        inferred = methodology_slug
        if not inferred:
            for key in ("methodology_slug", "methodology", "subcategory"):
                if row.get(key):
                    inferred = str(row[key])
                    break
        result = migrate_carbon_capture_record_detailed(row, methodology_slug=inferred)
        if result.legacy_mineralization is not None:
            legacy_mineralization.append(result.legacy_mineralization)
        if result.status == "migrated" and result.record is not None:
            migrated.append(result.record)
        elif result.status == "pending_review" and result.record is not None:
            pending_review.append(result.record)
            if result.proposal:
                proposals.append(result.proposal)
        else:
            invalid.append(result.original or row)

    # Legacy mineralization archive (all mineralization, never discarded)
    legacy_path = layout["metadata"] / "legacy_mineralization_records.csv"
    if legacy_mineralization:
        legacy_fields = sorted({k for row in legacy_mineralization for k in row.keys()})
        # Prefer stable leading columns
        preferred = [
            "preserved_record_id",
            "preserved_source_id",
            "preserved_citation",
            "preserved_source_url",
            "migration_status",
            "migration_reason",
            "record_id",
            "source_id",
            "citation",
            "source_url_or_citation",
            "source_url",
            "source_title",
            "subcategory",
            "methodology_slug",
            "technology_type",
            "functional_role",
        ]
        fieldnames = [c for c in preferred if c in legacy_fields] + [
            c for c in legacy_fields if c not in preferred
        ]
        _write_csv(legacy_path, fieldnames, legacy_mineralization)
    else:
        _write_csv(
            legacy_path,
            ["migration_status", "migration_reason", "preserved_record_id", "preserved_citation"],
            [],
        )

    pending_path = layout["metadata"] / "pending_taxonomy_review_records.csv"
    _write_csv(pending_path, list(RECORD_FIELDS), pending_review)
    pending_summary = write_pending_taxonomy_review(out, pending_review)

    proposal_fields = list(PROPOSAL_FIELDS) + ["functional_role", "proposed_parent_slug"]
    proposals_path = layout["metadata"] / "taxonomy_proposals.csv"
    _write_csv(proposals_path, proposal_fields, proposals)

    # Genuinely invalid / unmapped non-mineralization only
    unmapped_path = layout["rejected_records"] / "unmapped_carbon_capture_records.csv"
    if invalid:
        fieldnames = sorted({k for row in invalid for k in row.keys()})
        _write_csv(unmapped_path, fieldnames, invalid)
    else:
        _write_csv(unmapped_path, ["reason"], [])

    migrated_path = layout["metadata"] / "migrated_carbon_capture_records.csv"
    _write_csv(migrated_path, list(RECORD_FIELDS), migrated)

    missing_citation_count = sum(
        1
        for r in migrated + pending_review
        if not (r.get("source_id") or r.get("citation") or r.get("source_url"))
    )
    missing_functional_role_count = sum(
        1 for r in migrated + pending_review if not str(r.get("functional_role") or "").strip()
    )

    report = {
        "input": str(src),
        "output_dir": str(out),
        "input_rows": len(raw_rows),
        "migrated": len(migrated),
        "pending_review": len(pending_review),
        "invalid": len(invalid),
        "unmapped": len(invalid),  # backward-compatible alias
        "legacy_mineralization": len(legacy_mineralization),
        "taxonomy_proposals": len(proposals),
        # Explicit counts requested for production reporting (aliases of the above).
        "deterministically_migrated": len(migrated),
        "pending_taxonomy_review": len(pending_review),
        "genuinely_invalid": len(invalid),
        "missing_citation": missing_citation_count,
        "missing_functional_role": missing_functional_role_count,
        "migrated_path": str(migrated_path),
        "pending_review_path": str(pending_path),
        "pending_taxonomy_review_summary": pending_summary,
        "legacy_mineralization_path": str(legacy_path),
        "taxonomy_proposals_path": str(proposals_path),
        "unmapped_path": str(unmapped_path),
        "taxonomy_version": TAXONOMY_VERSION,
        "note": (
            "Mineralization records are preserved in legacy_mineralization_records.csv; "
            "SCM-compatible cases migrate to Carbonated Waste-Derived SCMs; "
            "others are Pending Taxonomy Review and are not rejected solely for "
            "falling outside the six plant-capture categories."
        ),
    }
    (layout["metadata"] / "carbon_capture_migration_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "Migrated %s; pending_review %s; invalid %s; legacy_mineralization %s -> %s",
        len(migrated),
        len(pending_review),
        len(invalid),
        len(legacy_mineralization),
        migrated_path,
    )
    return report
