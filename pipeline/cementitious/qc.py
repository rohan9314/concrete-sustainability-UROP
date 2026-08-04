"""Optional quality-control pass for Cementitious Materials records."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from pipeline.llm_utils import DEFAULT_MODEL
from pipeline.cementitious.extraction import call_json_llm
from pipeline.cementitious.prompts import qc_system_prompt, qc_user_prompt

logger = logging.getLogger(__name__)

QC_FIELDS: tuple[str, ...] = (
    "record_id",
    "original_subcategory",
    "original_sub_subcategory",
    "original_technology_variant",
    "original_functional_role",
    "proposed_subcategory",
    "proposed_sub_subcategory",
    "proposed_technology_variant",
    "proposed_functional_role",
    "correction_reason",
    "confidence",
    "requires_human_review",
    "issue_flags",
)


def needs_qc(record: dict[str, Any]) -> bool:
    if record.get("taxonomy_confidence") == "Low":
        return True
    if record.get("extraction_confidence") == "Low":
        return True
    if record.get("functional_role") in {"", "Uncertain", "Other"}:
        return True
    if not (record.get("evidence_text") or "").strip():
        return True
    if record.get("classification_basis") in {"Weakly Inferred", "Unresolved"}:
        return True
    # Heuristic conflict flags
    text = " ".join(
        str(record.get(k) or "")
        for k in (
            "raw_technology_name",
            "classification_reasoning",
            "evidence_text",
            "notes",
        )
    ).casefold()
    if "aggregate" in text and record.get("subcategory_slug", "").endswith("materials"):
        return True
    if "kiln fuel" in text and record.get("sub_subcategory_slug") == "biomass_ashes":
        return True
    return False


def run_qc_pass(
    records: list[dict[str, Any]],
    *,
    output_path: Path,
    model: str = DEFAULT_MODEL,
    use_llm: bool = False,
) -> list[dict[str, str]]:
    """
    Produce QC review rows. Does not overwrite production records.
    """
    rows: list[dict[str, str]] = []
    for record in records:
        if not needs_qc(record):
            continue
        if use_llm:
            try:
                payload = call_json_llm(
                    system=qc_system_prompt(),
                    user=qc_user_prompt(record=record),
                    model=model,
                    fail_name=f"qc_{record.get('record_id')}",
                )
                original = payload.get("original_classification") or {}
                proposed = payload.get("proposed_corrected_classification") or {}
                rows.append(
                    {
                        "record_id": str(record.get("record_id") or ""),
                        "original_subcategory": str(
                            original.get("subcategory") or record.get("subcategory") or ""
                        ),
                        "original_sub_subcategory": str(
                            original.get("sub_subcategory")
                            or record.get("sub_subcategory")
                            or ""
                        ),
                        "original_technology_variant": str(
                            original.get("technology_variant")
                            or record.get("technology_variant")
                            or ""
                        ),
                        "original_functional_role": str(
                            original.get("functional_role")
                            or record.get("functional_role")
                            or ""
                        ),
                        "proposed_subcategory": str(proposed.get("subcategory") or ""),
                        "proposed_sub_subcategory": str(proposed.get("sub_subcategory") or ""),
                        "proposed_technology_variant": str(
                            proposed.get("technology_variant") or ""
                        ),
                        "proposed_functional_role": str(proposed.get("functional_role") or ""),
                        "correction_reason": str(payload.get("correction_reason") or ""),
                        "confidence": str(payload.get("confidence") or ""),
                        "requires_human_review": str(
                            bool(payload.get("requires_human_review", True))
                        ),
                        "issue_flags": json.dumps(payload.get("issue_flags") or []),
                    }
                )
                continue
            except Exception as exc:
                logger.warning("QC LLM failed for %s: %s", record.get("record_id"), exc)

        rows.append(
            {
                "record_id": str(record.get("record_id") or ""),
                "original_subcategory": str(record.get("subcategory") or ""),
                "original_sub_subcategory": str(record.get("sub_subcategory") or ""),
                "original_technology_variant": str(record.get("technology_variant") or ""),
                "original_functional_role": str(record.get("functional_role") or ""),
                "proposed_subcategory": "",
                "proposed_sub_subcategory": "",
                "proposed_technology_variant": "",
                "proposed_functional_role": "",
                "correction_reason": "Flagged for human review by heuristic QC rules",
                "confidence": "Low",
                "requires_human_review": "True",
                "issue_flags": json.dumps(["heuristic_flag"]),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(QC_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return rows
