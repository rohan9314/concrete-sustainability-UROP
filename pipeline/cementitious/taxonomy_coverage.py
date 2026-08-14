"""Pilot/full taxonomy coverage report (literature + web vs every canonical node)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy
from pipeline.cementitious.shard_io import atomic_write_json

logger = logging.getLogger(__name__)

WEB_QUERY_COVERAGE_WARNING_FRACTION = 0.20
ZERO_REASON_VALUES = (
    "no_literature_candidates",
    "no_web_results",
    "screened_out",
    "extraction_failed",
    "no_qualifying_evidence",
    "deduplicated_into_other_record",
    "other",
)


def write_taxonomy_coverage_report(
    output_dir: str | Path,
    *,
    retrieval_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    meta = root / "metadata"
    meta.mkdir(parents=True, exist_ok=True)
    tax = get_decarbonization_taxonomy()
    coverage = retrieval_coverage or _load_json(meta / "retrieval_coverage_manifest.json")
    export_manifest = _load_json(meta / "taxonomy_export_manifest.json")
    per_searched = {
        str(n.get("taxonomy_path") or n.get("path") or ""): n
        for n in (coverage.get("per_searched_node") or [])
    }
    export_nodes = {str(n.get("path") or ""): n for n in (export_manifest.get("nodes") or [])}

    per_l1: dict[str, dict[str, Any]] = {}
    for node in tax.nodes_at(1):
        per_l1[node.label] = {
            "level_1": node.label,
            "path": node.path,
            "literature_candidate_count": 0,
            "literature_final_record_count": 0,
            "web_query_count": 0,
            "web_result_count": 0,
            "final_record_count": int((export_nodes.get(node.path) or {}).get("row_count") or 0),
        }

    per_l4: list[dict[str, Any]] = []
    l4_with_records = 0
    lit_only = 0
    web_only = 0
    both = 0
    zero_final = 0
    zero_query = 0
    zero_results = 0
    for node in tax.nodes_at(4):
        cov = per_searched.get(node.path) or {}
        exported = export_nodes.get(node.path) or {}
        l1 = node.path_labels[1] if len(node.path_labels) > 1 else ""
        n_queries = int(cov.get("query_count") or cov.get("web_queries") or 0)
        n_results = int(cov.get("raw_result_count") or cov.get("web_results_retrieved") or 0)
        n_lit = int(cov.get("merged_final_literature") or 0)
        n_web = int(cov.get("merged_final_web") or 0)
        n_final = int(exported.get("row_count") or cov.get("final_retained_record_count") or 0)
        if l1 in per_l1:
            per_l1[l1]["literature_candidate_count"] += int(cov.get("literature_candidates") or 0)
            per_l1[l1]["literature_final_record_count"] += n_lit
            per_l1[l1]["web_query_count"] += n_queries
            per_l1[l1]["web_result_count"] += n_results
        zero_row = n_final == 0
        if n_final >= 1:
            l4_with_records += 1
            if n_lit and n_web:
                both += 1
            elif n_lit:
                lit_only += 1
            elif n_web:
                web_only += 1
        else:
            zero_final += 1
        if n_queries == 0:
            zero_query += 1
        if n_results == 0:
            zero_results += 1
        skip_reason = cov.get("skip_reason") or ""
        zero_reason = ""
        if zero_row:
            if n_queries == 0 and skip_reason:
                zero_reason = "other"
            elif n_queries == 0:
                zero_reason = "other"
            elif n_results == 0:
                zero_reason = "no_web_results"
            elif int(cov.get("literature_candidates") or 0) == 0 and n_web == 0:
                zero_reason = "no_qualifying_evidence"
            else:
                zero_reason = "no_qualifying_evidence"
        per_l4.append(
            {
                "full_taxonomy_path": " → ".join(node.path_labels),
                "path": node.path,
                "canonical_label": node.label,
                "level_1": l1,
                "literature_final_count": n_lit,
                "web_query_count": n_queries,
                "web_result_count": n_results,
                "final_record_count": n_final,
                "zero_row": zero_row,
                "csv_emitted": bool(exported.get("csv_emitted", True)),
                "csv_path": exported.get("csv_path"),
                "skip_reason": skip_reason,
                "zero_reason": zero_reason if zero_reason in ZERO_REASON_VALUES else (
                    zero_reason if zero_reason else ""
                ),
            }
        )

    n_l4 = tax.count(4) or 1
    warnings: list[str] = []
    if zero_query / n_l4 >= WEB_QUERY_COVERAGE_WARNING_FRACTION:
        msg = (
            f"QUALITY WARNING: {zero_query}/{tax.count(4)} Level-4 nodes have "
            f"web_query_count=0 (retrieval did not run for those nodes)."
        )
        warnings.append(msg)
        logger.warning(msg)
    if zero_results / n_l4 >= WEB_QUERY_COVERAGE_WARNING_FRACTION and zero_query == 0:
        msg = (
            f"QUALITY WARNING: {zero_results}/{tax.count(4)} Level-4 nodes have "
            f"web_result_count=0. Distinguish true evidence scarcity from a weak search."
        )
        warnings.append(msg)
        logger.warning(msg)

    payload = {
        "taxonomy_version": tax.taxonomy_version,
        "level_1": list(per_l1.values()),
        "level_4": per_l4,
        "summary": {
            "level_4_total": tax.count(4),
            "level_4_with_records": l4_with_records,
            "level_4_literature_only": lit_only,
            "level_4_web_only": web_only,
            "level_4_both_literature_and_web": both,
            "level_4_zero_final_records": zero_final,
            "level_4_web_query_count_zero": zero_query,
            "level_4_web_result_count_zero": zero_results,
        },
        "warnings": warnings,
    }
    atomic_write_json(meta / "taxonomy_coverage_report.json", payload)
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
