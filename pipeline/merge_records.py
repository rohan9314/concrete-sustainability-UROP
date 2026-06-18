"""Stage 5: merge source-level extractions into consolidated technology records."""

from __future__ import annotations

import logging
from collections import defaultdict

from pipeline.schema import (
    NOT_REPORTED,
    TechnologyRecord,
    finalize_record,
    is_field_reported,
    merge_group_key,
)

logger = logging.getLogger(__name__)

CONFIDENCE_RANK = {"High": 3, "Medium": 2, "Low": 1, "Not Reported": 0}


def _best_confidence(
    current: str | None,
    candidate: str | None,
) -> str:
    current_rank = CONFIDENCE_RANK.get(current or "Not Reported", 0)
    candidate_rank = CONFIDENCE_RANK.get(candidate or "Not Reported", 0)
    if candidate_rank > current_rank:
        return candidate or "Not Reported"
    return current or "Not Reported"


def _merge_string_field(
    target: dict,
    field: str,
    value: str,
    *,
    source_id: str,
    provenance: dict[str, list[str]],
    confidence: dict[str, str],
    field_confidence: str,
    notes: list[str],
    counts: dict[str, dict[str, int]],
) -> None:
    if not is_field_reported(value):
        return

    field_counts = counts.setdefault(field, {})
    field_counts[value] = field_counts.get(value, 0) + 1

    current = target.get(field)
    if not is_field_reported(current):
        target[field] = value
        provenance.setdefault(field, []).append(source_id)
        confidence[field] = field_confidence
        return

    if current == value:
        provenance.setdefault(field, []).append(source_id)
        confidence[field] = _best_confidence(confidence.get(field), field_confidence)
        return

    notes.append(f"Conflicting {field}: kept '{current}', also saw '{value}' from {source_id}")


def _merge_string_list_field(target: list[str], values: list[str]) -> None:
    seen = {item.lower() for item in target}
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in seen:
            target.append(text)
            seen.add(text.lower())
def _merge_object_list_field(
    target: list,
    values: list,
    *,
    key: str,
) -> None:
    seen = {
        str(item.get(key) or item).strip().lower()
        for item in target
        if isinstance(item, dict)
    }
    for item in values:
        if isinstance(item, dict):
            identifier = str(item.get(key) or "").strip().lower()
            if identifier and identifier not in seen:
                target.append(item)
                seen.add(identifier)


def merge_records(records: list[TechnologyRecord]) -> list[TechnologyRecord]:
    """
    Merge multiple source-level TechnologyRecord objects.

    Groups by technology name and company where possible, preserves provenance,
    prefers values supported by multiple sources, and records conflicts in notes.
    """
    groups: dict[str, list[TechnologyRecord]] = defaultdict(list)
    for record in records:
        groups[merge_group_key(record)].append(record)

    merged: list[TechnologyRecord] = []

    for group_key, group_records in groups.items():
        base = group_records[0].model_dump()
        notes: list[str] = list(base.get("extraction_notes") or [])
        provenance: dict[str, list[str]] = {}
        confidence: dict[str, str] = dict(base.get("confidence_by_field") or {})
        counts: dict[str, dict[str, int]] = {}

        merged_data = {
            "technology_name": base["technology_name"],
            "technology_category": base.get("technology_category") or "Other",
            "company_or_organization": base.get("company_or_organization") or NOT_REPORTED,
            "deployment_stage": base.get("deployment_stage") or NOT_REPORTED,
            "technical_description": base.get("technical_description") or NOT_REPORTED,
            "replaces_or_improves": base.get("replaces_or_improves") or NOT_REPORTED,
            "performance_metrics": list(base.get("performance_metrics") or []),
            "reported_ghg_reduction_percent": base.get("reported_ghg_reduction_percent")
            or NOT_REPORTED,
            "absolute_emissions_intensity_kg_co2e": base.get(
                "absolute_emissions_intensity_kg_co2e",
            )
            or NOT_REPORTED,
            "energy_reduction_percent": base.get("energy_reduction_percent") or NOT_REPORTED,
            "cost_reduction_percent": base.get("cost_reduction_percent") or NOT_REPORTED,
            "pilot_projects": list(base.get("pilot_projects") or []),
            "demonstration_projects": list(base.get("demonstration_projects") or []),
            "relevant_sources": list(base.get("relevant_sources") or []),
        }

        string_fields = [
            "technology_category",
            "company_or_organization",
            "deployment_stage",
            "technical_description",
            "replaces_or_improves",
            "reported_ghg_reduction_percent",
            "absolute_emissions_intensity_kg_co2e",
            "energy_reduction_percent",
            "cost_reduction_percent",
        ]

        for record in group_records[1:]:
            data = record.model_dump()
            source_ids = [
                src.get("paper_id", "")
                for src in data.get("relevant_sources") or []
                if isinstance(src, dict)
            ]
            source_id = source_ids[0] if source_ids else record.record_id or group_key

            for field in string_fields:
                field_conf = (data.get("confidence_by_field") or {}).get(field, "Not Reported")
                _merge_string_field(
                    merged_data,
                    field,
                    str(data.get(field) or NOT_REPORTED),
                    source_id=source_id,
                    provenance=provenance,
                    confidence=confidence,
                    field_confidence=field_conf,
                    notes=notes,
                    counts=counts,
                )

            _merge_string_list_field(
                merged_data["performance_metrics"],
                data.get("performance_metrics") or [],
            )
            _merge_object_list_field(
                merged_data["pilot_projects"],
                data.get("pilot_projects") or [],
                key="name",
            )
            _merge_object_list_field(
                merged_data["demonstration_projects"],
                data.get("demonstration_projects") or [],
                key="name",
            )
            _merge_object_list_field(
                merged_data["relevant_sources"],
                data.get("relevant_sources") or [],
                key="paper_id",
            )

        for field, value_counts in counts.items():
            if len(value_counts) > 1:
                winner = max(value_counts.items(), key=lambda item: item[1])[0]
                if merged_data.get(field) != winner:
                    notes.append(
                        f"Promoted {field}='{winner}' based on multi-source agreement",
                    )
                    merged_data[field] = winner

        record = TechnologyRecord.model_validate(
            {
                **merged_data,
                "extraction_notes": notes,
                "confidence_by_field": confidence,
                "source_provenance": provenance,
            },
        )
        record = finalize_record(record)
        merged.append(record)

    logger.info("merge_records: produced %s consolidated records", len(merged))
    return merged
