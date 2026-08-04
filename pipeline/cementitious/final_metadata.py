"""Final run manifest + output-contract validation for Cementitious Materials."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.cementitious import SCHEMA_VERSION, TAXONOMY_VERSION
from pipeline.cementitious.paths import ensure_730_layout, safe_partition_filename
from pipeline.cementitious.schema import CITATION_FIELDS, RECORD_FIELDS
from pipeline.cementitious.shard_io import atomic_write_json
from pipeline.cementitious.taxonomy import Taxonomy, get_taxonomy

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = "cementitious-run-manifest-v1"
VALIDATION_SCHEMA_VERSION = "cementitious-validation-report-v1"

RUN_MANIFEST_REL = "metadata/run_manifest.json"
VALIDATION_REPORT_REL = "metadata/validation_report.json"
# Backward-compatible aliases under all_records/ (historical local-runner location).
ALL_RECORDS_MANIFEST_REL = "all_records/run_manifest.json"
ALL_RECORDS_VALIDATION_REL = "all_records/validation_report.json"


class FinalMetadataError(RuntimeError):
    """Raised when final metadata generation or validation fails."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit(repo_root: Path | None = None) -> str | None:
    try:
        cmd = ["git", "rev-parse", "HEAD"]
        if repo_root is not None:
            cmd = ["git", "-C", str(repo_root), "rev-parse", "HEAD"]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
        return out or None
    except Exception:
        return None


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{k: (v if v is not None else "") for k, v in row.items()} for row in reader]
    return fields, rows


def _csv_row_count(path: Path) -> int:
    if not path.is_file():
        return -1
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for _ in reader)


def _audit_nonzero_rows(path: Path) -> int:
    """Return data-row count; missing file counts as 0 (no issues recorded)."""
    if not path.is_file():
        return 0
    return max(0, _csv_row_count(path))


def _detect_run_mode(root: Path, environ: dict[str, str] | None = None) -> str:
    env = environ or dict(os.environ)
    raw = (env.get("RUN_MODE") or env.get("WORKFLOW_MODE") or "").strip().lower()
    if raw in {"literature-and-web", "literature_and_web", "pilot", "full"}:
        if raw in {"pilot", "full"}:
            # Prefer explicit RUN_MODE literature-and-web when present.
            pass
        else:
            return "literature-and-web" if "web" in raw else raw.replace("_", "-")
    if raw in {"literature-only", "literature_only"}:
        return "literature-only"
    if raw in {"web-only", "web_only"}:
        return "web-only"
    # Infer from artifacts.
    if (root / "checkpoints" / "web_search_merge.complete").is_file() or (
        root / "metadata" / "web_records_raw.jsonl"
    ).is_file():
        if (root / "checkpoints" / "extract_merge.complete").is_file() or (
            root / "metadata" / "literature_records_raw.jsonl"
        ).is_file():
            return "literature-and-web"
        return "web-only"
    return "literature-only"


def _detect_pilot_or_full(root: Path, environ: dict[str, str] | None = None) -> str:
    env = environ or dict(os.environ)
    mode = (env.get("WORKFLOW_MODE") or "").strip().lower()
    if mode in {"pilot", "full"}:
        return mode
    if "cementitious_engaging_pilot" in str(root):
        return "pilot"
    cap = env.get("CEMENTITIOUS_MAX_RECORDS", "").strip()
    if cap and cap.isdigit():
        return "pilot"
    return "full"


def _selected_lists(environ: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    env = environ or dict(os.environ)
    subs = [s.strip() for s in (env.get("SELECTED_SUBCATEGORIES") or "").split(",") if s.strip()]
    leaves = [
        s.strip() for s in (env.get("SELECTED_SUB_SUBCATEGORIES") or "").split(",") if s.strip()
    ]
    return subs, leaves


def _check(
    name: str,
    *,
    ok: bool,
    expected: Any,
    observed: Any,
    message: str,
) -> dict[str, Any]:
    return {
        "check_name": name,
        "status": "pass" if ok else "fail",
        "expected": expected,
        "observed": observed,
        "message": message,
    }


def _header_ok(fields: list[str], expected: tuple[str, ...]) -> bool:
    return list(fields) == list(expected)


def build_validation_report(
    output_dir: str | Path,
    *,
    taxonomy: Taxonomy | None = None,
    environ: dict[str, str] | None = None,
    require_resource_recommendations: bool | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    layout = ensure_730_layout(root)
    tax = taxonomy or get_taxonomy()
    env = environ or dict(os.environ)
    run_mode = _detect_run_mode(root, env)
    pilot_or_full = _detect_pilot_or_full(root, env)
    web_enabled = run_mode in {"literature-and-web", "web-only"}
    lit_enabled = run_mode in {"literature-and-web", "literature-only"}
    if require_resource_recommendations is None:
        require_resource_recommendations = pilot_or_full == "pilot"

    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []

    def add(check: dict[str, Any]) -> None:
        checks.append(check)
        if check["status"] != "pass":
            errors.append(f"{check['check_name']}: {check['message']}")

    master_path = layout["all_records"] / "cementitious_materials_all_records.csv"
    cites_path = layout["all_records"] / "citations_all.csv"
    summary_path = layout["all_records"] / "partition_summary.csv"

    master_fields: list[str] = []
    master_rows: list[dict[str, str]] = []
    cite_fields: list[str] = []
    cite_rows: list[dict[str, str]] = []

    if master_path.is_file():
        try:
            master_fields, master_rows = _read_csv(master_path)
            add(
                _check(
                    "master_records_csv_readable",
                    ok=True,
                    expected="readable CSV",
                    observed=str(master_path),
                    message="Master records CSV exists and is readable",
                )
            )
        except Exception as exc:
            add(
                _check(
                    "master_records_csv_readable",
                    ok=False,
                    expected="readable CSV",
                    observed=str(exc),
                    message="Master records CSV unreadable",
                )
            )
    else:
        add(
            _check(
                "master_records_csv_readable",
                ok=False,
                expected=str(master_path),
                observed="missing",
                message="Master records CSV missing",
            )
        )

    if cites_path.is_file():
        try:
            cite_fields, cite_rows = _read_csv(cites_path)
            add(
                _check(
                    "master_citations_csv_readable",
                    ok=True,
                    expected="readable CSV",
                    observed=str(cites_path),
                    message="Master citations CSV exists and is readable",
                )
            )
        except Exception as exc:
            add(
                _check(
                    "master_citations_csv_readable",
                    ok=False,
                    expected="readable CSV",
                    observed=str(exc),
                    message="Master citations CSV unreadable",
                )
            )
    else:
        add(
            _check(
                "master_citations_csv_readable",
                ok=False,
                expected=str(cites_path),
                observed="missing",
                message="Master citations CSV missing",
            )
        )

    # Taxonomy partition existence (empty header-only files are valid).
    missing_sub = []
    missing_sub_cit = []
    for node in tax.subcategories.values():
        rec = layout["subcategories"] / safe_partition_filename(node.slug)
        cit = layout["citations_subcategories"] / safe_partition_filename(f"{node.slug}_citations")
        if not rec.is_file():
            missing_sub.append(node.slug)
        if not cit.is_file():
            missing_sub_cit.append(node.slug)
    add(
        _check(
            "all_subcategory_record_csvs_exist",
            ok=not missing_sub,
            expected=len(tax.subcategories),
            observed=len(tax.subcategories) - len(missing_sub),
            message="All subcategory record CSVs exist"
            if not missing_sub
            else f"Missing subcategory CSVs: {missing_sub[:5]}",
        )
    )
    add(
        _check(
            "all_subcategory_citation_csvs_exist",
            ok=not missing_sub_cit,
            expected=len(tax.subcategories),
            observed=len(tax.subcategories) - len(missing_sub_cit),
            message="All subcategory citation CSVs exist"
            if not missing_sub_cit
            else f"Missing subcategory citation CSVs: {missing_sub_cit[:5]}",
        )
    )

    missing_leaf = []
    missing_leaf_cit = []
    for node in tax.sub_subcategories.values():
        rec = layout["sub_subcategories"] / safe_partition_filename(node.slug)
        cit = layout["citations_sub_subcategories"] / safe_partition_filename(
            f"{node.slug}_citations"
        )
        if not rec.is_file():
            missing_leaf.append(node.slug)
        if not cit.is_file():
            missing_leaf_cit.append(node.slug)
    add(
        _check(
            "all_leaf_record_csvs_exist",
            ok=not missing_leaf,
            expected=len(tax.sub_subcategories),
            observed=len(tax.sub_subcategories) - len(missing_leaf),
            message="All leaf record CSVs exist"
            if not missing_leaf
            else f"Missing leaf CSVs: {missing_leaf[:5]}",
        )
    )
    add(
        _check(
            "all_leaf_citation_csvs_exist",
            ok=not missing_leaf_cit,
            expected=len(tax.sub_subcategories),
            observed=len(tax.sub_subcategories) - len(missing_leaf_cit),
            message="All leaf citation CSVs exist"
            if not missing_leaf_cit
            else f"Missing leaf citation CSVs: {missing_leaf_cit[:5]}",
        )
    )

    # Header schemas (master + sample one partition if present).
    add(
        _check(
            "master_records_header_schema",
            ok=bool(master_fields) and _header_ok(master_fields, RECORD_FIELDS),
            expected=list(RECORD_FIELDS[:5]) + ["..."],
            observed=master_fields[:8],
            message="Master records header matches RECORD_FIELDS"
            if _header_ok(master_fields, RECORD_FIELDS)
            else "Master records header mismatch",
        )
    )
    add(
        _check(
            "master_citations_header_schema",
            ok=bool(cite_fields) and _header_ok(cite_fields, CITATION_FIELDS),
            expected=list(CITATION_FIELDS[:5]) + ["..."],
            observed=cite_fields[:8],
            message="Master citations header matches CITATION_FIELDS"
            if _header_ok(cite_fields, CITATION_FIELDS)
            else "Master citations header mismatch",
        )
    )

    # Partition correctness using record_id.
    valid_subs = set(tax.subcategories)
    valid_leaves = set(tax.sub_subcategories)
    id_counts = Counter(r.get("record_id") or "" for r in master_rows)
    blank_ids = id_counts.get("", 0)
    dup_ids = sorted(rid for rid, n in id_counts.items() if rid and n > 1)
    add(
        _check(
            "record_ids_unique",
            ok=blank_ids == 0 and not dup_ids,
            expected="unique non-empty record_id",
            observed={"duplicates": dup_ids[:10], "blank_ids": blank_ids},
            message="Deduplicated record IDs are unique"
            if blank_ids == 0 and not dup_ids
            else "Duplicate or blank record_id values present",
        )
    )

    bad_sub = [
        r.get("record_id")
        for r in master_rows
        if (r.get("subcategory_slug") or "") not in valid_subs
    ]
    bad_leaf = [
        r.get("record_id")
        for r in master_rows
        if (r.get("sub_subcategory_slug") or "") not in valid_leaves
    ]
    add(
        _check(
            "master_records_valid_subcategory",
            ok=not bad_sub,
            expected="subcategory_slug in taxonomy",
            observed={"invalid_count": len(bad_sub), "examples": bad_sub[:5]},
            message="Every master record has a valid taxonomy subcategory",
        )
    )
    add(
        _check(
            "master_records_valid_leaf",
            ok=not bad_leaf,
            expected="sub_subcategory_slug in taxonomy",
            observed={"invalid_count": len(bad_leaf), "examples": bad_leaf[:5]},
            message="Every master record has a valid taxonomy leaf",
        )
    )

    # Load partition ID sets.
    sub_ids: dict[str, set[str]] = {}
    leaf_ids: dict[str, set[str]] = {}
    for node in tax.subcategories.values():
        path = layout["subcategories"] / safe_partition_filename(node.slug)
        if path.is_file():
            try:
                _, rows = _read_csv(path)
                sub_ids[node.slug] = {r.get("record_id") or "" for r in rows}
                sub_ids[node.slug].discard("")
            except Exception:
                sub_ids[node.slug] = set()
        else:
            sub_ids[node.slug] = set()
    for node in tax.sub_subcategories.values():
        path = layout["sub_subcategories"] / safe_partition_filename(node.slug)
        if path.is_file():
            try:
                _, rows = _read_csv(path)
                leaf_ids[node.slug] = {r.get("record_id") or "" for r in rows}
                leaf_ids[node.slug].discard("")
            except Exception:
                leaf_ids[node.slug] = set()
        else:
            leaf_ids[node.slug] = set()

    missing_from_sub = []
    missing_from_leaf = []
    wrong_partition = []
    for row in master_rows:
        rid = row.get("record_id") or ""
        if not rid:
            continue
        ss = row.get("subcategory_slug") or ""
        leaf = row.get("sub_subcategory_slug") or ""
        if ss in sub_ids and rid not in sub_ids[ss]:
            missing_from_sub.append(rid)
        if leaf in leaf_ids and rid not in leaf_ids[leaf]:
            missing_from_leaf.append(rid)
        for other, ids in sub_ids.items():
            if other != ss and rid in ids:
                wrong_partition.append({"record_id": rid, "found_in_subcategory": other, "expected": ss})
        for other, ids in leaf_ids.items():
            if other != leaf and rid in ids:
                wrong_partition.append(
                    {"record_id": rid, "found_in_leaf": other, "expected": leaf}
                )

    add(
        _check(
            "master_in_matching_subcategory_csv",
            ok=not missing_from_sub,
            expected="each master record in matching subcategory CSV",
            observed={"missing_count": len(missing_from_sub), "examples": missing_from_sub[:5]},
            message="Every master record appears in its subcategory CSV",
        )
    )
    add(
        _check(
            "master_in_matching_leaf_csv",
            ok=not missing_from_leaf,
            expected="each master record in matching leaf CSV",
            observed={"missing_count": len(missing_from_leaf), "examples": missing_from_leaf[:5]},
            message="Every master record appears in its leaf CSV",
        )
    )
    add(
        _check(
            "no_records_in_incorrect_partitions",
            ok=not wrong_partition,
            expected="no cross-partition leakage",
            observed={"issues": wrong_partition[:10]},
            message="No record appears in an incorrect partition",
        )
    )

    # Citations linkage by record_id.
    cite_by_record: dict[str, int] = Counter(r.get("record_id") or "" for r in cite_rows)
    cite_by_record.pop("", None)
    master_id_set = {r.get("record_id") or "" for r in master_rows}
    master_id_set.discard("")
    missing_cite_for_record = sorted(rid for rid in master_id_set if cite_by_record.get(rid, 0) < 1)
    orphan_cites = sorted(rid for rid in cite_by_record if rid not in master_id_set)
    add(
        _check(
            "citations_align_to_master_records",
            ok=not missing_cite_for_record and not orphan_cites,
            expected="each master record_id has >=1 citation; no orphans",
            observed={
                "missing_citations_for_records": missing_cite_for_record[:5],
                "orphan_citation_record_ids": orphan_cites[:5],
            },
            message="Citation rows align to master records",
        )
    )

    # Citation partitions: every citation for a record should appear in that record's taxonomy citation files.
    leaf_cite_ids: dict[str, set[str]] = defaultdict(set)
    for node in tax.sub_subcategories.values():
        path = layout["citations_sub_subcategories"] / safe_partition_filename(
            f"{node.slug}_citations"
        )
        if not path.is_file():
            continue
        try:
            _, rows = _read_csv(path)
            for r in rows:
                rid = r.get("record_id") or ""
                if rid:
                    leaf_cite_ids[node.slug].add(rid)
        except Exception:
            continue
    missing_cite_partition = []
    for row in master_rows:
        rid = row.get("record_id") or ""
        leaf = row.get("sub_subcategory_slug") or ""
        if not rid or not leaf:
            continue
        if cite_by_record.get(rid, 0) and rid not in leaf_cite_ids.get(leaf, set()):
            missing_cite_partition.append(rid)
    add(
        _check(
            "citations_in_matching_leaf_citation_csv",
            ok=not missing_cite_partition,
            expected="citation record_ids present in leaf citation CSV",
            observed={"missing_count": len(missing_cite_partition), "examples": missing_cite_partition[:5]},
            message="Citations appear in matching leaf citation partitions",
        )
    )

    # Partition count reconciliation vs master.
    expected_by_sub = Counter(r.get("subcategory_slug") or "" for r in master_rows)
    expected_by_leaf = Counter(r.get("sub_subcategory_slug") or "" for r in master_rows)
    sub_mismatch = {
        slug: {"expected": expected_by_sub.get(slug, 0), "observed": len(ids)}
        for slug, ids in sub_ids.items()
        if expected_by_sub.get(slug, 0) != len(ids)
    }
    leaf_mismatch = {
        slug: {"expected": expected_by_leaf.get(slug, 0), "observed": len(ids)}
        for slug, ids in leaf_ids.items()
        if expected_by_leaf.get(slug, 0) != len(ids)
    }
    add(
        _check(
            "partition_counts_reconcile_with_master",
            ok=not sub_mismatch and not leaf_mismatch,
            expected="partition row counts == master group counts",
            observed={"subcategory_mismatches": sub_mismatch, "leaf_mismatches": leaf_mismatch},
            message="Partition counts reconcile with master output",
        )
    )

    # Provenance fields.
    missing_prov = []
    for row in master_rows:
        rid = row.get("record_id") or ""
        if not rid:
            missing_prov.append({"record_id": rid, "field": "record_id"})
            continue
        if not (row.get("source_title") or "").strip():
            missing_prov.append({"record_id": rid, "field": "source_title"})
            continue
        if not (row.get("evidence_text") or "").strip():
            missing_prov.append({"record_id": rid, "field": "evidence_text"})
            continue
        if not (
            (row.get("source_id") or "").strip()
            or (row.get("citation") or "").strip()
            or (row.get("source_url") or "").strip()
        ):
            missing_prov.append({"record_id": rid, "field": "source_id/citation/source_url"})
            continue
        # evidence_origin may be blank in older exports; source_type still provides provenance.
        if not (
            (row.get("evidence_origin") or "").strip()
            or (row.get("source_type") or "").strip()
        ):
            missing_prov.append({"record_id": rid, "field": "evidence_origin/source_type"})
    add(
        _check(
            "required_provenance_fields_present",
            ok=not missing_prov,
            expected=[
                "record_id",
                "source_title",
                "evidence_text",
                "source_id|citation|source_url",
                "evidence_origin|source_type",
            ],
            observed={"issues": missing_prov[:10]},
            message="Required provenance fields are present",
        )
    )

    # Audit files must be zero-row for a passing run.
    audits = {
        "missing_partition_citations_audit_empty": layout["rejected_records"]
        / "missing_partition_citations.csv",
        "invalid_taxonomy_audit_empty": layout["rejected_records"] / "invalid_taxonomy_records.csv",
        "missing_screen_shard_audit_empty": layout["rejected_records"] / "missing_screen_shards.csv",
    }
    for name, path in audits.items():
        n = _audit_nonzero_rows(path)
        add(
            _check(
                name,
                ok=n == 0,
                expected=0,
                observed=n,
                message=f"{path.name} has zero data rows" if n == 0 else f"{path.name} has {n} rows",
            )
        )

    web_search_miss = layout["rejected_records"] / "missing_web_search_shards.csv"
    web_extract_miss = layout["rejected_records"] / "missing_web_extraction_shards.csv"
    if web_enabled:
        n = _audit_nonzero_rows(web_search_miss)
        add(
            _check(
                "missing_web_search_shard_audit_empty",
                ok=n == 0,
                expected=0,
                observed=n,
                message="missing_web_search_shards.csv empty when web enabled",
            )
        )
        n = _audit_nonzero_rows(web_extract_miss)
        add(
            _check(
                "missing_web_extraction_shard_audit_empty",
                ok=n == 0,
                expected=0,
                observed=n,
                message="missing_web_extraction_shards.csv empty when web enabled",
            )
        )
    else:
        warnings.append(
            "Web search disabled; skipped missing_web_search/extraction shard audit strict checks"
        )
        add(
            _check(
                "missing_web_search_shard_audit_empty",
                ok=True,
                expected="skipped (web disabled)",
                observed="skipped",
                message="Web disabled; web search shard audit check skipped",
            )
        )
        add(
            _check(
                "missing_web_extraction_shard_audit_empty",
                ok=True,
                expected="skipped (web disabled)",
                observed="skipped",
                message="Web disabled; web extraction shard audit check skipped",
            )
        )

    # Required checkpoints (export.complete intentionally excluded — written after this report).
    required_checkpoints = ["dedupe_qc.complete"]
    if lit_enabled:
        required_checkpoints.extend(
            ["plan_screen.complete", "screen_merge.complete", "extract_merge.complete"]
        )
    if web_enabled:
        required_checkpoints.extend(
            ["plan_web_queries.complete", "web_search_merge.complete", "web_extract_merge.complete"]
        )
    if lit_enabled and web_enabled:
        required_checkpoints.append("merge_literature_web.complete")
    present_any_workflow = any(
        (layout["checkpoints"] / name).is_file() for name in required_checkpoints
    )
    missing_ckpt = [
        name
        for name in required_checkpoints
        if not (layout["checkpoints"] / name).is_file()
    ]
    # Export-only / local fixtures may lack Engaging checkpoints; treat as warning unless
    # this looks like a workflow run (any required checkpoint already present).
    if present_any_workflow or env.get("CEMENTITIOUS_STRICT_CHECKPOINTS", "").strip() in {
        "1",
        "true",
        "yes",
    }:
        add(
            _check(
                "required_workflow_checkpoints_exist",
                ok=not missing_ckpt,
                expected=required_checkpoints,
                observed={"missing": missing_ckpt},
                message="Required workflow checkpoints exist"
                if not missing_ckpt
                else f"Missing checkpoints: {missing_ckpt}",
            )
        )
        add(
            _check(
                "no_required_stage_incomplete",
                ok=not missing_ckpt,
                expected="all required stages complete",
                observed={"incomplete": missing_ckpt},
                message="No required stage is incomplete",
            )
        )
    else:
        warnings.append(
            "No Engaging workflow checkpoints detected; checkpoint completeness checks skipped"
        )
        add(
            _check(
                "required_workflow_checkpoints_exist",
                ok=True,
                expected="skipped (export-only / no workflow markers)",
                observed={"missing": missing_ckpt},
                message="Checkpoint completeness skipped for export-only directory",
            )
        )
        add(
            _check(
                "no_required_stage_incomplete",
                ok=True,
                expected="skipped (export-only / no workflow markers)",
                observed={"incomplete": missing_ckpt},
                message="Stage completeness skipped for export-only directory",
            )
        )

    resource_summary = root / "metadata" / "resource_usage_summary.json"
    resource_reco = root / "metadata" / "full_run_resource_recommendations.json"
    add(
        _check(
            "resource_usage_summary_exists",
            ok=resource_summary.is_file(),
            expected=str(resource_summary),
            observed="present" if resource_summary.is_file() else "missing",
            message="resource_usage_summary.json exists",
        )
    )
    if require_resource_recommendations:
        add(
            _check(
                "full_run_resource_recommendations_exists",
                ok=resource_reco.is_file(),
                expected=str(resource_reco),
                observed="present" if resource_reco.is_file() else "missing",
                message="full_run_resource_recommendations.json exists for completed pilot",
            )
        )
    else:
        warnings.append("full_run_resource_recommendations not required for this mode")
        add(
            _check(
                "full_run_resource_recommendations_exists",
                ok=True,
                expected="optional for non-pilot",
                observed="present" if resource_reco.is_file() else "optional-absent",
                message="Resource recommendations optional for this mode",
            )
        )

    # partition_summary.csv reconciliation
    if summary_path.is_file():
        try:
            _, summary_rows = _read_csv(summary_path)
            # Expect one row per taxonomy node (sub + leaf) typically.
            observed_files = sum(
                1
                for p in list(layout["subcategories"].glob("*.csv"))
                + list(layout["sub_subcategories"].glob("*.csv"))
            )
            add(
                _check(
                    "partition_summary_reconciles",
                    ok=len(summary_rows) >= len(tax.subcategories) + len(tax.sub_subcategories)
                    or len(summary_rows) == observed_files,
                    expected="summary covers taxonomy partitions",
                    observed={
                        "summary_rows": len(summary_rows),
                        "taxonomy_nodes": len(tax.subcategories) + len(tax.sub_subcategories),
                        "partition_csvs": observed_files,
                    },
                    message="partition_summary.csv reconciles with exported files",
                )
            )
        except Exception as exc:
            add(
                _check(
                    "partition_summary_reconciles",
                    ok=False,
                    expected="readable partition_summary.csv",
                    observed=str(exc),
                    message="partition_summary.csv unreadable",
                )
            )
    else:
        add(
            _check(
                "partition_summary_reconciles",
                ok=False,
                expected=str(summary_path),
                observed="missing",
                message="partition_summary.csv missing",
            )
        )

    overall = "pass" if all(c["status"] == "pass" for c in checks) else "fail"
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "created_at": _now(),
        "overall_status": overall,
        "run_mode": run_mode,
        "pilot_or_full": pilot_or_full,
        "web_search_enabled": web_enabled,
        "literature_enabled": lit_enabled,
        "taxonomy_version": tax.taxonomy_version or TAXONOMY_VERSION,
        "record_schema_version": SCHEMA_VERSION,
        "master_record_count": len(master_rows),
        "master_citation_count": len(cite_rows),
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }


def build_run_manifest(
    output_dir: str | Path,
    *,
    taxonomy: Taxonomy | None = None,
    environ: dict[str, str] | None = None,
    validation_report: dict[str, Any] | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    layout = ensure_730_layout(root)
    tax = taxonomy or get_taxonomy()
    env = environ or dict(os.environ)
    run_mode = _detect_run_mode(root, env)
    pilot_or_full = _detect_pilot_or_full(root, env)
    selected_subs, selected_leaves = _selected_lists(env)
    repo_root = env.get("REPO_ROOT") or None
    if not repo_root and (root / "metadata" / "repo_root.txt").is_file():
        repo_root = (root / "metadata" / "repo_root.txt").read_text(encoding="utf-8").strip() or None

    master_path = layout["all_records"] / "cementitious_materials_all_records.csv"
    cites_path = layout["all_records"] / "citations_all.csv"
    master_count = max(0, _csv_row_count(master_path)) if master_path.is_file() else 0
    cite_count = max(0, _csv_row_count(cites_path)) if cites_path.is_file() else 0

    populated_subs = 0
    populated_leaves = 0
    for node in tax.subcategories.values():
        path = layout["subcategories"] / safe_partition_filename(node.slug)
        if path.is_file() and _csv_row_count(path) > 0:
            populated_subs += 1
    for node in tax.sub_subcategories.values():
        path = layout["sub_subcategories"] / safe_partition_filename(node.slug)
        if path.is_file() and _csv_row_count(path) > 0:
            populated_leaves += 1

    checkpoints = sorted(p.name for p in layout["checkpoints"].glob("*.complete"))
    job_ids: list[dict[str, Any]] = []
    for name in ("one_line_submission_manifest.json", "submitted_jobs.json"):
        path = layout["metadata"] / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for job in payload.get("jobs") or []:
                if isinstance(job, dict) and job.get("job_id"):
                    job_ids.append(
                        {"name": job.get("name"), "job_id": str(job.get("job_id"))}
                    )
        except Exception:
            continue

    rejected = {
        "invalid_taxonomy": max(
            0, _csv_row_count(layout["rejected_records"] / "invalid_taxonomy_records.csv")
        )
        if (layout["rejected_records"] / "invalid_taxonomy_records.csv").is_file()
        else 0,
        "missing_taxonomy": max(
            0, _csv_row_count(layout["rejected_records"] / "missing_taxonomy_records.csv")
        )
        if (layout["rejected_records"] / "missing_taxonomy_records.csv").is_file()
        else 0,
    }
    pending_count = 0
    pending = layout["pending_taxonomy_review"] / "pending_taxonomy_records.csv"
    if pending.is_file():
        pending_count = max(0, _csv_row_count(pending))

    dedupe_in = None
    dedupe_out = master_count
    for candidate in (
        layout["metadata"] / "combined_records_pre_dedupe.jsonl",
        layout["metadata"] / "extracted_records_raw.jsonl",
        layout["metadata"] / "literature_records_raw.jsonl",
    ):
        if candidate.is_file():
            dedupe_in = sum(1 for _ in candidate.open("r", encoding="utf-8") if _.strip())
            break

    taxonomy_path = tax.source_path or env.get("TAXONOMY_PATH") or ""
    taxonomy_hash = None
    if taxonomy_path and Path(taxonomy_path).is_file():
        taxonomy_hash = hashlib.sha256(Path(taxonomy_path).read_bytes()).hexdigest()[:16]

    web_leaves = selected_leaves[:]
    if not web_leaves and pilot_or_full == "pilot":
        # Pilot default leaf when selected list empty but Chemical Absorption was run.
        if populated_leaves == 1:
            for node in tax.sub_subcategories.values():
                path = layout["sub_subcategories"] / safe_partition_filename(node.slug)
                if path.is_file() and _csv_row_count(path) > 0:
                    web_leaves = [node.slug]
                    break

    stages = [
        "preprocess_plan",
        "screen",
        "screen_merge",
        "extract",
        "extract_merge",
        "web_search",
        "web_extract",
        "merge_literature_web",
        "dedupe_qc",
        "export",
        "final_metadata",
    ]

    status = "complete"
    if validation_report is not None:
        status = "complete" if validation_report.get("overall_status") == "pass" else "validation_failed"

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": _now(),
        "completed_at": completed_at or _now(),
        "run_mode": run_mode,
        "pilot_or_full": pilot_or_full,
        "final_status": status,
        "output_dir": str(root),
        "repository_root": repo_root,
        "git_commit": _git_commit(Path(repo_root) if repo_root else None),
        "taxonomy_path": taxonomy_path,
        "taxonomy_version": tax.taxonomy_version or TAXONOMY_VERSION,
        "taxonomy_hash": taxonomy_hash,
        "taxonomy_subcategory_count": len(tax.subcategories),
        "taxonomy_leaf_count": len(tax.sub_subcategories),
        "selected_subcategories": selected_subs,
        "selected_sub_subcategories": selected_leaves,
        "web_enabled_leaves": web_leaves,
        "literature_enabled": run_mode in {"literature-and-web", "literature-only"},
        "web_search_enabled": run_mode in {"literature-and-web", "web-only"},
        "literature_record_cap": env.get("CEMENTITIOUS_MAX_RECORDS") or None,
        "source_corpus_path": env.get("PICKLE_PATH") or env.get("PAPER_RECORDS_PATH") or None,
        "source_corpus_record_count": None,
        "shard_size": env.get("SHARD_SIZE") or None,
        "worker_count": int(env.get("CEMENTITIOUS_WORKERS") or env.get("WORKERS") or 1),
        "array_concurrency": int(env.get("ARRAY_MAX_CONCURRENCY") or 1),
        "workflow_stages": stages,
        "submitted_job_ids": job_ids,
        "completed_checkpoints": checkpoints,
        "master_record_count": master_count,
        "master_citation_count": cite_count,
        "populated_subcategory_count": populated_subs,
        "populated_leaf_count": populated_leaves,
        "total_subcategory_csv_count": len(tax.subcategories),
        "total_leaf_csv_count": len(tax.sub_subcategories),
        "rejected_record_counts": rejected,
        "pending_taxonomy_review_count": pending_count,
        "deduplication_input_count": dedupe_in,
        "deduplication_output_count": dedupe_out,
        "resource_summary_path": "metadata/resource_usage_summary.json",
        "resource_recommendation_path": "metadata/full_run_resource_recommendations.json",
        "openai_api_key_set": bool(env.get("OPENAI_API_KEY")),
        "tavily_api_key_set": bool(env.get("TAVILY_API_KEY")),
        "secrets_included": False,
        "compatibility_aliases": {
            "all_records_run_manifest": ALL_RECORDS_MANIFEST_REL,
            "all_records_validation_report": ALL_RECORDS_VALIDATION_REL,
        },
    }


def write_final_metadata(
    output_dir: str | Path,
    *,
    taxonomy: Taxonomy | None = None,
    environ: dict[str, str] | None = None,
    write_compatibility_aliases: bool = True,
    ensure_resources: bool = True,
) -> dict[str, Any]:
    """
    Build and atomically write metadata/run_manifest.json and metadata/validation_report.json.

    Optionally ensures resource summary/recommendations exist before validation.
    Does not write export.complete.
    """
    root = Path(output_dir)
    layout = ensure_730_layout(root)
    tax = taxonomy or get_taxonomy()
    env = environ or dict(os.environ)

    if ensure_resources:
        try:
            from pipeline.cementitious.resource_calibration import (
                build_full_run_recommendations,
                write_resource_usage_summary,
            )

            write_resource_usage_summary(root)
            if _detect_pilot_or_full(root, env) == "pilot":
                build_full_run_recommendations(root)
        except Exception as exc:
            logger.warning("Resource summary/recommendations unavailable: %s", exc)

    validation = build_validation_report(root, taxonomy=tax, environ=env)
    manifest = build_run_manifest(
        root,
        taxonomy=tax,
        environ=env,
        validation_report=validation,
    )

    meta_manifest = layout["metadata"] / "run_manifest.json"
    meta_validation = layout["metadata"] / "validation_report.json"
    atomic_write_json(meta_manifest, manifest)
    atomic_write_json(meta_validation, validation)

    if write_compatibility_aliases:
        # Preserve historical all_records locations for older tests/resume helpers.
        # Keep any richer stats already written by export_partitions under a nested key.
        alias_validation = dict(validation)
        existing = layout["all_records"] / "validation_report.json"
        if existing.is_file():
            try:
                prior = json.loads(existing.read_text(encoding="utf-8"))
                if isinstance(prior, dict) and "checks" not in prior:
                    alias_validation["export_stats"] = prior
            except Exception:
                pass
        atomic_write_json(layout["all_records"] / "run_manifest.json", manifest)
        atomic_write_json(layout["all_records"] / "validation_report.json", alias_validation)

    return {
        "run_manifest_path": str(meta_manifest),
        "validation_report_path": str(meta_validation),
        "overall_status": validation.get("overall_status"),
        "manifest": manifest,
        "validation_report": validation,
    }


def finalize_metadata(
    *,
    output_dir: str | Path,
    force: bool = False,
    write_export_complete: bool = True,
    require_pass: bool = True,
) -> dict[str, Any]:
    """
    Metadata-only repair / finalization.

    Safe for completed Engaging outputs: no OpenAI/Tavily, no re-extraction.
    If require_pass and validation fails, does not write export.complete and raises.
    """
    root = Path(output_dir)
    ensure_730_layout(root)
    marker = root / "checkpoints" / "export.complete"
    # Always regenerate metadata even when an older incomplete export.complete exists.
    result = write_final_metadata(root, ensure_resources=True)
    if require_pass and result.get("overall_status") != "pass":
        if marker.is_file() and force:
            # Leave marker for inspection but signal failure.
            pass
        raise FinalMetadataError(
            "validation_report overall_status is fail; export.complete not written. "
            f"See {result.get('validation_report_path')}"
        )
    if write_export_complete and result.get("overall_status") == "pass":
        from pipeline.cementitious.shard_io import write_marker

        write_marker(marker)
    return result
