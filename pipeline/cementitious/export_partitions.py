"""Partition export for Cementitious Materials taxonomy results."""

from __future__ import annotations

import csv
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.cementitious.canonical_user_export import write_canonical_user_export
from pipeline.cementitious.hierarchical_export import write_hierarchical_export
from pipeline.cementitious.taxonomy_migration import (
    apply_decarbonization_path,
    coverage_report,
)
from pipeline.cementitious.paths import (
    ensure_730_layout,
    safe_partition_filename,
    sanitize_slug,
)
from pipeline.cementitious.shard_io import atomic_write_csv
from pipeline.cementitious.schema import (
    CITATION_FIELDS,
    RECORD_FIELDS,
    citation_from_record,
    normalize_missing,
    normalize_record,
    schema_manifest,
    sort_records,
    validate_records,
)
from pipeline.cementitious.taxonomy import Taxonomy, get_taxonomy, load_taxonomy

logger = logging.getLogger(__name__)


class MissingCitationError(RuntimeError):
    """Raised when an accepted export row has no citation and overrides are not allowed."""


_PENDING_MINERALIZATION_RE = re.compile(
    r"mineraliz|mineral\s+carbonation|carbonation\s+curing|co2\s+curing|"
    r"co2\s+mineralization|carbon\s+mineralization",
    re.I,
)

PARTITION_SUMMARY_FIELDS: tuple[str, ...] = (
    "partition_level",
    "partition_name",
    "partition_slug",
    "parent_partition",
    "record_count",
    "literature_record_count",
    "web_record_count",
    "unique_source_count",
    "literature_source_count",
    "web_source_count",
    "unique_project_count",
    "unique_company_count",
    "high_confidence_count",
    "medium_confidence_count",
    "low_confidence_count",
    "missing_citation_count",
    "missing_evidence_count",
    "output_path",
    "citation_output_path",
)


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Input not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    if suffix == ".jsonl":
        from pipeline.cementitious.shard_io import iter_jsonl

        rows: list[dict[str, Any]] = []
        for payload in iter_jsonl(path):
            if payload.get("type") in {"cementitious_meta", "meta"}:
                continue
            rows.append(payload)
        return rows
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and "records" in payload:
            return list(payload["records"])
        raise ValueError(f"Unsupported JSON structure in {path}")
    raise ValueError(f"Unsupported input format: {path.suffix}")


def write_csv(path: Path, fieldnames: tuple[str, ...] | list[str], rows: list[dict[str, Any]]) -> Path:
    return atomic_write_csv(Path(path), fieldnames, rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"type": "cementitious_meta", "row_count": len(rows)},
                ensure_ascii=False,
            )
            + "\n"
        )
        for row in rows:
            payload = dict(row)
            # JSON null for missing blanks
            for key, value in list(payload.items()):
                if value == "":
                    payload[key] = None
            payload["type"] = "cementitious_record"
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


def citations_for_records(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    Expand records (in ``sort_records`` order) into one-or-more citation rows.

    A record may carry a ``citations`` or ``citation_entries`` list of dicts to
    describe multiple sources for one record; each entry is merged over the
    record before ``citation_from_record`` so per-entry fields win. Otherwise a
    single citation is emitted from the record itself. All citations for a
    given record are grouped consecutively and the overall order follows the
    result record order, so the citation twin lines up with the record CSV.
    """
    out: list[dict[str, str]] = []
    for record in sort_records(rows):
        entries = record.get("citations") or record.get("citation_entries")
        if isinstance(entries, list) and entries:
            for entry in entries:
                if isinstance(entry, dict):
                    out.append(citation_from_record({**record, **entry}))
                else:
                    out.append(citation_from_record(record))
        else:
            out.append(citation_from_record(record))
    return out


def validate_partition_citations(
    records: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> list[str]:
    """
    Confirm every record has >=1 aligned citation and no citation is orphaned.

    Returns a list of human-readable issue strings (empty when aligned).
    """
    issues: list[str] = []
    record_ids = {str(r.get("record_id") or "") for r in records}
    record_ids.discard("")
    citation_counts: Counter[str] = Counter(
        str(c.get("record_id") or "") for c in citations
    )
    for rid in sorted(record_ids):
        if citation_counts.get(rid, 0) < 1:
            issues.append(f"record_id {rid!r} has no citation entry")
    for rid, count in citation_counts.items():
        if rid and rid not in record_ids:
            issues.append(f"citation record_id {rid!r} ({count}) not present in result set")
    return issues


def _is_pending_mineralization(row: dict[str, Any]) -> bool:
    blob = " ".join(
        str(row.get(k) or "")
        for k in (
            "canonical_technology_name",
            "technology_variant",
            "raw_technology_name",
            "notes",
            "classification_reasoning",
        )
    )
    return bool(_PENDING_MINERALIZATION_RE.search(blob))


def write_pending_taxonomy_review(
    output_dir: str | Path,
    pending_records: list[dict[str, Any]],
    *,
    taxonomy: Taxonomy | None = None,
) -> dict[str, Any]:
    """
    Write the Pending Taxonomy Review export twin under ``pending_taxonomy_review/``.

    Pending records are preserved for human review and must never be merged
    into approved subcategory / sub-subcategory partitions. Writes:
      - pending_taxonomy_records.csv (RECORD_FIELDS headers, even if empty)
      - pending_taxonomy_citations.csv (CITATION_FIELDS, record_ids preserved)
      - pending_taxonomy_summary.json
    """
    root = Path(output_dir)
    pending_dir = root / "pending_taxonomy_review"
    pending_dir.mkdir(parents=True, exist_ok=True)

    # Keep any extra (non-RECORD_FIELDS) keys such as proposed_subcategory /
    # reason_pending around for the summary counts, alongside the normalized
    # RECORD_FIELDS view that is actually written to the CSV twin.
    ordered_raw = sort_records(
        [
            {**raw, **{key: normalize_missing(raw.get(key)) for key in RECORD_FIELDS}}
            for raw in pending_records
        ]
    )
    ordered = [{key: row.get(key, "") for key in RECORD_FIELDS} for row in ordered_raw]

    records_path = pending_dir / "pending_taxonomy_records.csv"
    citations_path = pending_dir / "pending_taxonomy_citations.csv"
    summary_path = pending_dir / "pending_taxonomy_summary.json"

    write_csv(records_path, RECORD_FIELDS, ordered)
    citations = citations_for_records(ordered_raw)
    write_csv(citations_path, CITATION_FIELDS, citations)

    def _counts(rows: list[dict[str, Any]], *keys: str) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for row in rows:
            value = ""
            for key in keys:
                value = str(row.get(key) or "").strip()
                if value:
                    break
            counter[value] += 1
        return dict(counter)

    mineralization_count = sum(1 for r in ordered_raw if _is_pending_mineralization(r))
    summary = {
        "total_pending_records": len(ordered),
        "total_pending_citations": len(citations),
        "counts_by_proposed_subcategory": _counts(
            ordered_raw, "proposed_subcategory", "subcategory"
        ),
        "counts_by_proposed_sub_subcategory": _counts(
            ordered_raw, "proposed_sub_subcategory", "sub_subcategory"
        ),
        "counts_by_functional_role": _counts(ordered_raw, "functional_role"),
        "counts_by_confidence": _counts(ordered_raw, "taxonomy_confidence"),
        "counts_by_reason_pending": _counts(ordered_raw, "reason_pending", "notes"),
        "mineralization_pending_count": mineralization_count,
        "non_mineralization_pending_count": len(ordered_raw) - mineralization_count,
    }
    try:
        summary["records_path"] = str(records_path.relative_to(root))
        summary["citations_path"] = str(citations_path.relative_to(root))
    except ValueError:
        summary["records_path"] = str(records_path)
        summary["citations_path"] = str(citations_path)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _partition_stats(
    *,
    level: str,
    name: str,
    slug: str,
    parent: str,
    rows: list[dict[str, str]],
    output_path: Path,
    citation_output_path: Path,
    root: Path,
) -> dict[str, Any]:
    conf = Counter((r.get("taxonomy_confidence") or "") for r in rows)
    sources = {(r.get("source_id") or r.get("citation") or "") for r in rows}
    sources.discard("")
    lit_rows = [r for r in rows if (r.get("evidence_origin") or "Literature") == "Literature"]
    web_rows = [r for r in rows if r.get("evidence_origin") == "Web"]
    lit_sources = {(r.get("source_id") or r.get("citation") or "") for r in lit_rows}
    lit_sources.discard("")
    web_sources = {(r.get("source_id") or r.get("source_url") or "") for r in web_rows}
    web_sources.discard("")
    projects = {(r.get("project_name") or "") for r in rows}
    projects.discard("")
    companies = {(r.get("company_or_organization") or "") for r in rows}
    companies.discard("")
    missing_citation = sum(
        1 for r in rows if not (r.get("source_id") or r.get("citation") or r.get("source_url"))
    )
    missing_evidence = sum(1 for r in rows if not (r.get("evidence_text") or "").strip())
    try:
        out_rel = str(output_path.relative_to(root))
    except ValueError:
        out_rel = str(output_path)
    try:
        cit_rel = str(citation_output_path.relative_to(root))
    except ValueError:
        cit_rel = str(citation_output_path)
    return {
        "partition_level": level,
        "partition_name": name,
        "partition_slug": slug,
        "parent_partition": parent,
        "record_count": len(rows),
        "literature_record_count": len(lit_rows),
        "web_record_count": len(web_rows),
        "unique_source_count": len(sources),
        "literature_source_count": len(lit_sources),
        "web_source_count": len(web_sources),
        "unique_project_count": len(projects),
        "unique_company_count": len(companies),
        "high_confidence_count": conf.get("High", 0),
        "medium_confidence_count": conf.get("Medium", 0),
        "low_confidence_count": conf.get("Low", 0),
        "missing_citation_count": missing_citation,
        "missing_evidence_count": missing_evidence,
        "output_path": out_rel,
        "citation_output_path": cit_rel,
    }


def export_taxonomy_partitions(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    taxonomy: Taxonomy | None = None,
    subcategory: str | None = None,
    sub_subcategory: str | None = None,
    force: bool = False,
    allow_missing_citations: bool = False,
) -> dict[str, Any]:
    """
    Export all-records files and taxonomy partition CSVs.

    If subcategory or sub_subcategory is set, only those partitions are
    (re)written; all-records files are still refreshed from the filtered set.

    Raises ``MissingCitationError`` when any exported row has no source_id,
    citation, source_url, or citation entries, unless
    ``allow_missing_citations`` is set.
    """
    tax = taxonomy or get_taxonomy()
    root = Path(output_dir)
    layout = ensure_730_layout(root)
    raw_records = _read_records(Path(input_path))
    validation = validate_records(raw_records, taxonomy=tax)
    accepted = sort_records(validation.accepted)

    # Optional selective filter for partition rewriting
    filtered = accepted
    if subcategory:
        slug = tax.resolve_slug(subcategory, level="subcategory")
        filtered = [r for r in accepted if r["subcategory_slug"] == slug]
    if sub_subcategory:
        slug = tax.resolve_slug(sub_subcategory, level="sub_subcategory")
        filtered = [r for r in accepted if r["sub_subcategory_slug"] == slug]

    write_csv(
        layout["rejected_records"] / "invalid_taxonomy_records.csv",
        RECORD_FIELDS,
        validation.invalid_taxonomy,
    )
    write_csv(
        layout["rejected_records"] / "missing_taxonomy_records.csv",
        RECORD_FIELDS,
        validation.missing_taxonomy,
    )

    # All-records (full accepted set unless selective mode requested for export-only)
    export_rows = filtered if (subcategory or sub_subcategory) else accepted
    export_rows = [apply_decarbonization_path(r) for r in export_rows]
    all_csv = layout["all_records"] / "cementitious_materials_all_records.csv"
    all_jsonl = layout["all_records"] / "cementitious_materials_all_records.jsonl"
    write_csv(all_csv, RECORD_FIELDS, export_rows)
    write_jsonl(all_jsonl, export_rows)

    citations = citations_for_records(export_rows)
    citations_all = layout["all_records"] / "citations_all.csv"
    write_csv(citations_all, CITATION_FIELDS, citations)
    citation_alignment_issues = validate_partition_citations(export_rows, citations)

    # Records with no usable citation identifier and no citation entries.
    missing_citation_rows = [
        r
        for r in export_rows
        if not (r.get("source_id") or r.get("citation") or r.get("source_url"))
        and not (isinstance(r.get("citations"), list) and r.get("citations"))
        and not (isinstance(r.get("citation_entries"), list) and r.get("citation_entries"))
    ]
    missing_citations_path = layout["rejected_records"] / "missing_partition_citations.csv"
    write_csv(missing_citations_path, RECORD_FIELDS, missing_citation_rows)

    summary_rows: list[dict[str, Any]] = []
    taxonomy_manifest_nodes: list[dict[str, Any]] = []
    empty_partition_count = 0
    partition_file_count = 0

    # Subcategory partitions
    subcats_to_write = list(tax.subcategories.values())
    if subcategory:
        slug = tax.resolve_slug(subcategory, level="subcategory")
        subcats_to_write = [tax.subcategories[slug]]
    if sub_subcategory and not subcategory:
        parent = tax.parent_of_sub_sub[
            tax.resolve_slug(sub_subcategory, level="sub_subcategory")
        ]
        subcats_to_write = [tax.subcategories[parent]]

    for node in subcats_to_write:
        rows = [r for r in accepted if r["subcategory_slug"] == node.slug]
        if subcategory or sub_subcategory:
            rows = [r for r in filtered if r["subcategory_slug"] == node.slug]
        out_path = layout["subcategories"] / safe_partition_filename(node.slug)
        cit_path = layout["citations_subcategories"] / safe_partition_filename(
            f"{node.slug}_citations"
        )
        write_csv(out_path, RECORD_FIELDS, sort_records(rows))
        write_csv(cit_path, CITATION_FIELDS, citations_for_records(rows))
        partition_file_count += 1
        if not rows:
            empty_partition_count += 1
        summary_rows.append(
            _partition_stats(
                level="subcategory",
                name=node.display_name,
                slug=node.slug,
                parent=tax.category_slug,
                rows=rows,
                output_path=out_path,
                citation_output_path=cit_path,
                root=root,
            )
        )
        taxonomy_manifest_nodes.append(
            {
                "level": "subcategory",
                "display_name": node.display_name,
                "slug": node.slug,
                "parent": tax.category_slug,
                "output_path": str(out_path.relative_to(root)),
                "citation_output_path": str(cit_path.relative_to(root)),
            }
        )

    # Sub-subcategory partitions — always create every configured file unless selective
    ss_to_write = list(tax.sub_subcategories.values())
    if sub_subcategory:
        slug = tax.resolve_slug(sub_subcategory, level="sub_subcategory")
        ss_to_write = [tax.sub_subcategories[slug]]
    elif subcategory:
        parent = tax.resolve_slug(subcategory, level="subcategory")
        ss_to_write = tax.children_of(parent)

    # When doing a full export, write ALL sub-subcategories (including empty)
    if not subcategory and not sub_subcategory:
        ss_to_write = list(tax.sub_subcategories.values())

    for node in ss_to_write:
        rows = [r for r in accepted if r["sub_subcategory_slug"] == node.slug]
        if subcategory or sub_subcategory:
            rows = [r for r in filtered if r["sub_subcategory_slug"] == node.slug]
        out_path = layout["sub_subcategories"] / safe_partition_filename(node.slug)
        cit_path = layout["citations_sub_subcategories"] / safe_partition_filename(
            f"{node.slug}_citations"
        )
        write_csv(out_path, RECORD_FIELDS, sort_records(rows))
        write_csv(cit_path, CITATION_FIELDS, citations_for_records(rows))
        partition_file_count += 1
        if not rows:
            empty_partition_count += 1
        summary_rows.append(
            _partition_stats(
                level="sub_subcategory",
                name=node.display_name,
                slug=node.slug,
                parent=node.parent,
                rows=rows,
                output_path=out_path,
                citation_output_path=cit_path,
                root=root,
            )
        )
        taxonomy_manifest_nodes.append(
            {
                "level": "sub_subcategory",
                "display_name": node.display_name,
                "slug": node.slug,
                "parent": node.parent,
                "output_path": str(out_path.relative_to(root)),
                "citation_output_path": str(cit_path.relative_to(root)),
            }
        )

    # Full export also ensures every subcategory partition exists (already above)
    if not subcategory and not sub_subcategory:
        # Ensure any missing subcategory files (and their citation twins) from
        # earlier selective runs are present; never leave a record CSV without
        # a citation CSV alongside it.
        for node in tax.subcategories.values():
            out_path = layout["subcategories"] / safe_partition_filename(node.slug)
            cit_path = layout["citations_subcategories"] / safe_partition_filename(
                f"{node.slug}_citations"
            )
            if not out_path.is_file():
                write_csv(out_path, RECORD_FIELDS, [])
            if not cit_path.is_file():
                write_csv(cit_path, CITATION_FIELDS, [])
        for node in tax.sub_subcategories.values():
            out_path = layout["sub_subcategories"] / safe_partition_filename(node.slug)
            cit_path = layout["citations_sub_subcategories"] / safe_partition_filename(
                f"{node.slug}_citations"
            )
            if not out_path.is_file():
                write_csv(out_path, RECORD_FIELDS, [])
            if not cit_path.is_file():
                write_csv(cit_path, CITATION_FIELDS, [])

    write_csv(
        layout["all_records"] / "partition_summary.csv",
        PARTITION_SUMMARY_FIELDS,
        summary_rows,
    )

    # Pending Taxonomy Review twin — always (re)written so pending records are
    # never silently dropped and never merged into approved partitions.
    pending_records: list[dict[str, Any]] = []
    seen_pending_ids: set[str] = set()
    for pending_source in (
        root / "metadata" / "pending_taxonomy_review_records.csv",
        layout["pending_taxonomy_review"] / "pending_taxonomy_records.csv",
    ):
        if not pending_source.is_file():
            continue
        with pending_source.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                rid = str(row.get("record_id") or "")
                if rid and rid in seen_pending_ids:
                    continue
                if rid:
                    seen_pending_ids.add(rid)
                pending_records.append(row)
    pending_summary = write_pending_taxonomy_review(root, pending_records, taxonomy=tax)

    # Canonical user-facing tree (master → category → subcategory). Derived from
    # the same export_rows list as all_records/; not an independent transform.
    user_export = write_canonical_user_export(
        root,
        export_rows,
        fieldnames=RECORD_FIELDS,
        force=force,
    )
    hierarchical_export = write_hierarchical_export(
        root,
        export_rows,
        fieldnames=RECORD_FIELDS,
        force=force,
    )
    migration_coverage = coverage_report()
    (layout["metadata"] / "cementitious_runtime_taxonomy_migration.json").write_text(
        json.dumps(migration_coverage, indent=2) + "\n",
        encoding="utf-8",
    )

    # Counts for validation report
    by_sub = Counter(r["subcategory_slug"] for r in accepted)
    by_ss = Counter(r["sub_subcategory_slug"] for r in accepted)
    duplicate_ids = [
        rid
        for rid, count in Counter(r["record_id"] for r in accepted).items()
        if count > 1
    ]
    low_tax = sum(1 for r in accepted if r.get("taxonomy_confidence") == "Low")
    unresolved = sum(
        1 for r in accepted if r.get("classification_basis") == "Unresolved"
    )
    missing_citation = sum(
        1 for r in accepted if not (r.get("source_id") or r.get("citation"))
    )
    missing_evidence = sum(
        1 for r in accepted if not (r.get("evidence_text") or "").strip()
    )
    suspected_dupes = sum(
        1 for r in accepted if r.get("duplicate_status") == "Possible Duplicate"
    )

    validation_report = {
        "total_records": len(raw_records),
        "total_accepted": len(accepted),
        "total_rejected": len(validation.invalid_taxonomy) + len(validation.missing_taxonomy),
        "record_counts_by_subcategory": dict(by_sub),
        "record_counts_by_sub_subcategory": dict(by_ss),
        "literature_record_count": sum(
            1 for r in accepted if (r.get("evidence_origin") or "Literature") == "Literature"
        ),
        "web_record_count": sum(1 for r in accepted if r.get("evidence_origin") == "Web"),
        "records_with_invalid_category": sum(
            1 for r in validation.invalid_taxonomy if "invalid category" in (r.get("notes") or "")
        ),
        "records_with_invalid_subcategory": sum(
            1
            for e in validation.errors
            if "subcategory" in e and "sub_subcategory" not in e
        ),
        "records_with_invalid_sub_subcategory": sum(
            1 for e in validation.errors if "sub_subcategory" in e
        ),
        "records_with_inconsistent_parent_child_assignment": sum(
            1 for e in validation.errors if "inconsistent parent-child" in e
        ),
        "records_with_missing_source_citation": missing_citation,
        "records_with_missing_evidence": missing_evidence,
        "records_with_duplicate_record_ids": len(duplicate_ids),
        "suspected_duplicate_records": suspected_dupes,
        "records_with_low_taxonomy_confidence": low_tax,
        "records_with_unresolved_classification": unresolved,
        "partition_file_count": partition_file_count,
        "empty_partition_count": empty_partition_count,
        "schema_version": tax.schema_version or schema_manifest()["schema_version"],
        "taxonomy_version": tax.taxonomy_version,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "selective_subcategory": subcategory or None,
        "selective_sub_subcategory": sub_subcategory or None,
        "missing_partition_citations_count": len(missing_citation_rows),
        "missing_partition_citations_path": (
            str(missing_citations_path.relative_to(root))
            if missing_citation_rows
            else None
        ),
        "pending_taxonomy_review": pending_summary,
        "citation_alignment_issue_count": len(citation_alignment_issues),
        "citation_alignment_issues": citation_alignment_issues[:50],
        "user_facing_export": {
            "root": "cementitious_materials_results/",
            "master_csv": "cementitious_materials_results/cementitious_materials_all_records.csv",
            "category_csv_count": user_export.get("category_csv_count"),
            "subcategory_csv_count": user_export.get("subcategory_csv_count"),
            "empty_partition_policy": user_export.get("empty_partition_policy"),
            "taxonomy_level_mapping": user_export.get("taxonomy_level_mapping"),
        },
        "hierarchical_export": {
            "root": "concrete_decarbonization_results/",
            "master_csv": "concrete_decarbonization_results/concrete_decarbonization.csv",
            "total_csvs_generated": hierarchical_export.get("total_csvs_generated"),
            "manifest": "metadata/taxonomy_export_manifest.json",
        },
    }
    # Enrich with web stage metrics when available
    meta = root / "metadata"
    web_merge = meta / "web_search_merge_summary.json"
    web_ex_merge = meta / "web_extraction_merge_summary.json"
    if web_merge.is_file():
        try:
            ws = json.loads(web_merge.read_text(encoding="utf-8"))
            validation_report.update(
                {
                    "total_web_queries": ws.get("query_count"),
                    "successful_web_queries": ws.get("successful_query_count"),
                    "failed_web_queries": ws.get("failed_query_count"),
                    "raw_web_results": ws.get("raw_result_count"),
                    "unique_web_urls": ws.get("unique_url_count"),
                }
            )
        except Exception:
            pass
    if web_ex_merge.is_file():
        try:
            wes = json.loads(web_ex_merge.read_text(encoding="utf-8"))
            validation_report.update(
                {
                    "successfully_fetched_pages": wes.get("successful_fetch_count"),
                    "failed_page_fetches": wes.get("failed_fetch_count"),
                    "web_records_extracted": wes.get("extracted_record_count"),
                    "web_records_rejected": wes.get("malformed_output_count"),
                    "web_records_low_confidence": wes.get("low_confidence_count"),
                }
            )
        except Exception:
            pass
    web_recs = [r for r in accepted if r.get("evidence_origin") == "Web"]
    validation_report["web_records_missing_url"] = sum(
        1 for r in web_recs if not (r.get("source_url") or "").strip()
    )
    validation_report["web_records_missing_evidence"] = sum(
        1 for r in web_recs if not (r.get("evidence_text") or "").strip()
    )
    (layout["all_records"] / "validation_report.json").write_text(
        json.dumps(validation_report, indent=2),
        encoding="utf-8",
    )

    taxonomy_manifest = {
        "taxonomy_version": tax.taxonomy_version,
        "schema_version": tax.schema_version,
        "category": {
            "display_name": tax.category_display,
            "slug": tax.category_slug,
            "all_records_csv": str(all_csv.relative_to(root)),
            "all_records_jsonl": str(all_jsonl.relative_to(root)),
            "citations_all": str(citations_all.relative_to(root)),
        },
        "nodes": taxonomy_manifest_nodes,
        "source_taxonomy_path": tax.source_path,
    }
    (layout["all_records"] / "taxonomy_manifest.json").write_text(
        json.dumps(taxonomy_manifest, indent=2),
        encoding="utf-8",
    )

    run_manifest_path = layout["all_records"] / "run_manifest.json"
    if not run_manifest_path.is_file() or force:
        run_manifest_path.write_text(
            json.dumps(
                {
                    "note": "Export-only run_manifest (full extraction runner writes a richer manifest)",
                    "taxonomy_version": tax.taxonomy_version,
                    "schema_version": tax.schema_version or schema_manifest()["schema_version"],
                    "output_directory": str(root),
                    "input_path": str(input_path),
                    "run_timestamp": validation_report["run_timestamp"],
                    "commands_used": [
                        "python -m pipeline.export_taxonomy_partitions",
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    result = {
        "output_dir": str(root),
        "accepted": len(accepted),
        "exported": len(export_rows),
        "rejected_invalid": len(validation.invalid_taxonomy),
        "rejected_missing": len(validation.missing_taxonomy),
        "partition_file_count": partition_file_count,
        "empty_partition_count": empty_partition_count,
        "user_facing_export": user_export,
        "hierarchical_export": hierarchical_export,
        "validation_report": validation_report,
    }

    if missing_citation_rows and not allow_missing_citations:
        raise MissingCitationError(
            f"{len(missing_citation_rows)} exported record(s) have no citation "
            f"(source_id/citation/source_url/citation entries); see "
            f"{missing_citations_path}. Pass allow_missing_citations=True to override."
        )

    return result


def print_taxonomy_listing(taxonomy: Taxonomy | None = None) -> None:
    tax = taxonomy or get_taxonomy()
    print(f"Taxonomy version: {tax.taxonomy_version}")
    print(f"{'display_name':40} {'slug':45} {'level':16} {'parent':40} expected_output_filename")
    for row in tax.list_rows():
        print(
            f"{row['display_name'][:40]:40} "
            f"{row['slug'][:45]:45} "
            f"{row['level'][:16]:16} "
            f"{row['parent'][:40]:40} "
            f"{row['expected_output_filename']}"
        )


def print_summary(input_path: str | Path, taxonomy: Taxonomy | None = None) -> None:
    tax = taxonomy or get_taxonomy()
    records = [
        normalize_record(r, taxonomy=tax) for r in _read_records(Path(input_path))
    ]
    print("By subcategory:")
    for slug, count in sorted(Counter(r["subcategory_slug"] for r in records if r["subcategory_slug"]).items()):
        name = tax.subcategories.get(slug).display_name if slug in tax.subcategories else slug
        print(f"  {name} ({slug}): {count}")
    print("By sub-subcategory:")
    for slug, count in sorted(
        Counter(r["sub_subcategory_slug"] for r in records if r["sub_subcategory_slug"]).items()
    ):
        name = (
            tax.sub_subcategories.get(slug).display_name
            if slug in tax.sub_subcategories
            else slug
        )
        print(f"  {name} ({slug}): {count}")
    print("By technology_variant:")
    for variant, count in sorted(
        Counter(r["technology_variant"] for r in records if r["technology_variant"]).items()
    ):
        print(f"  {variant}: {count}")
