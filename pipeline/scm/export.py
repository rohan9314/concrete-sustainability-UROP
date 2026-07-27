"""CSV / JSONL export helpers for the SCM pipeline."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pipeline.scm.extraction import ScmDiscoveryRow, ScmEvidenceRow
from pipeline.scm.merge import MergeStats, conservative_merge_rows
from pipeline.scm.outputs import (
    ALL_CITATIONS_CSV,
    ALL_EVIDENCE_CSV,
    DISCOVERED_CATEGORIES_CSV,
    DISCOVERY_EVIDENCE_CSV,
    NORMALIZATION_CSV,
    all_citations_path,
    all_evidence_path,
    category_citations_path,
    category_results_path,
    literature_path_for_slug,
    web_path_for_slug,
)
from pipeline.scm.schema import (
    CATEGORY_LABEL,
    DISCOVERED_CATEGORY_FIELDS,
    DISCOVERY_FIELDS,
    EVIDENCE_FIELDS,
    NA,
    NORMALIZATION_FIELDS,
    ValidationStats,
)
from pipeline.scm.seed_categories import ScmSeedCategory

logger = logging.getLogger(__name__)

CITATION_FIELDS: tuple[str, ...] = (
    "record_id",
    "seed_category",
    "pipeline_branch",
    "source_type",
    "source_id",
    "source_title",
    "source_url_or_citation",
    "confidence",
)


@dataclass
class ScmExportSummary:
    literature_records: int = 0
    web_records: int = 0
    discovery_records: int = 0
    merged_records: int = 0
    exact_duplicates_removed: int = 0
    complementary_fields_filled: int = 0
    results_path: str = ""
    citations_path: str = ""
    all_evidence_path: str = ""
    all_citations_path: str = ""

    def to_log_lines(self) -> list[str]:
        return [
            f"Literature records: {self.literature_records}",
            f"Web records: {self.web_records}",
            f"Discovery records: {self.discovery_records}",
            f"Merged evidence records: {self.merged_records}",
            f"Exact duplicates removed: {self.exact_duplicates_removed}",
            f"Complementary fields filled: {self.complementary_fields_filled}",
            f"Results CSV: {self.results_path}",
            f"Citations CSV: {self.citations_path}",
            f"All evidence CSV: {self.all_evidence_path}",
            f"All citations CSV: {self.all_citations_path}",
        ]


def write_jsonl_evidence(path: Path, rows: list[ScmEvidenceRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "scm_evidence_meta", "row_count": len(rows)}) + "\n")
        for row in rows:
            payload = row.to_dict()
            payload["type"] = "scm_evidence_row"
            handle.write(json.dumps(payload) + "\n")
    return path


def read_jsonl_evidence(path: str | Path) -> list[ScmEvidenceRow]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    rows: list[ScmEvidenceRow] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if payload.get("type") != "scm_evidence_row":
            continue
        data = {k: v for k, v in payload.items() if k != "type"}
        rows.append(ScmEvidenceRow.from_dict(data))
    return rows


def write_jsonl_discovery(path: Path, rows: list[ScmDiscoveryRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "scm_discovery_meta", "row_count": len(rows)}) + "\n")
        for row in rows:
            payload = row.to_dict()
            payload["type"] = "scm_discovery_row"
            handle.write(json.dumps(payload) + "\n")
    return path


def read_jsonl_discovery(path: str | Path) -> list[ScmDiscoveryRow]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    rows: list[ScmDiscoveryRow] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if payload.get("type") != "scm_discovery_row":
            continue
        data = {k: v for k, v in payload.items() if k != "type"}
        rows.append(ScmDiscoveryRow.from_dict(data))
    return rows


def write_evidence_csv(path: Path, rows: list[ScmEvidenceRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EVIDENCE_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_evidence_dict())
    return path


def write_citations_csv(path: Path, rows: list[ScmEvidenceRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CITATION_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field, NA) for field in CITATION_FIELDS})
    return path


def write_discovery_csv(path: Path, rows: list[ScmDiscoveryRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(DISCOVERY_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_discovery_dict())
    return path


def write_dict_csv(path: Path, rows: list[dict], fieldnames: tuple[str, ...]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, NA) for field in fieldnames})
    return path


def export_seed_category_outputs(
    *,
    literature_rows: list[ScmEvidenceRow],
    web_rows: list[ScmEvidenceRow],
    category: ScmSeedCategory,
    output_dir: Path,
    stats: ValidationStats | None = None,
) -> ScmExportSummary:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "literature").mkdir(parents=True, exist_ok=True)
    (output_dir / "web").mkdir(parents=True, exist_ok=True)
    (output_dir / "csv").mkdir(parents=True, exist_ok=True)
    (output_dir / "citations").mkdir(parents=True, exist_ok=True)
    (output_dir / "merged").mkdir(parents=True, exist_ok=True)
    (output_dir / "validation").mkdir(parents=True, exist_ok=True)

    merged, merge_stats = conservative_merge_rows(literature_rows, web_rows)

    lit_path = literature_path_for_slug(output_dir, category.slug)
    web_path = web_path_for_slug(output_dir, category.slug)
    results_path = category_results_path(output_dir, category)
    citations_path = category_citations_path(output_dir, category)
    merged_path = output_dir / "merged" / f"{category.slug}_all_evidence.csv"

    # Also keep flat filenames for backward-compatible local inspection.
    flat_results = output_dir / category.results_filename
    flat_citations = output_dir / category.citations_filename

    write_jsonl_evidence(lit_path, literature_rows)
    write_jsonl_evidence(web_path, web_rows)
    write_evidence_csv(results_path, merged)
    write_citations_csv(citations_path, merged)
    write_evidence_csv(flat_results, merged)
    write_citations_csv(flat_citations, merged)
    write_evidence_csv(merged_path, merged)
    if stats is not None and stats.warnings:
        _append_validation_warnings(
            output_dir / "validation" / "validation_warnings.csv",
            stats.warnings,
            subcategory_or_discovery=category.slug,
        )

    summary = ScmExportSummary(
        literature_records=len(literature_rows),
        web_records=len(web_rows),
        merged_records=len(merged),
        exact_duplicates_removed=merge_stats.exact_duplicates_removed,
        complementary_fields_filled=merge_stats.complementary_fields_filled,
        results_path=str(results_path),
        citations_path=str(citations_path),
    )
    for line in summary.to_log_lines():
        logger.info(line)
    return summary


def _append_validation_warnings(
    path: Path,
    warnings: list[str],
    *,
    subcategory_or_discovery: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "record_id",
        "source_id",
        "subcategory_or_discovery",
        "warning_type",
        "warning_message",
        "severity",
    )
    write_header = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        if write_header:
            writer.writeheader()
        for warning in warnings:
            writer.writerow(
                {
                    "record_id": NA,
                    "source_id": NA,
                    "subcategory_or_discovery": subcategory_or_discovery,
                    "warning_type": "schema_validation",
                    "warning_message": warning,
                    "severity": "warning",
                },
            )


def export_combined_outputs(
    *,
    seed_rows: list[ScmEvidenceRow],
    discovery_evidence_rows: list[ScmEvidenceRow],
    output_dir: Path,
) -> ScmExportSummary:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "merged").mkdir(parents=True, exist_ok=True)

    for row in discovery_evidence_rows:
        if row.pipeline_branch in {NA, ""}:
            row.pipeline_branch = "open_discovery"
        if row.category in {NA, ""}:
            row.category = CATEGORY_LABEL
    for row in seed_rows:
        if row.pipeline_branch in {NA, ""}:
            row.pipeline_branch = "seed_category"
        if row.category in {NA, ""}:
            row.category = CATEGORY_LABEL

    merged, merge_stats = conservative_merge_rows(seed_rows, [], discovery_evidence_rows)

    # Hard validation: every retained record must be SCM.
    for row in merged:
        if row.category != CATEGORY_LABEL:
            raise ValueError(
                f"SCM combined export found non-SCM category on {row.record_id!r}: "
                f"{row.category!r}",
            )

    seed_only, _ = conservative_merge_rows(seed_rows, [])
    seed_only_path = output_dir / "merged" / "scm_all_seed_evidence.csv"
    write_evidence_csv(seed_only_path, seed_only)

    evidence_path = all_evidence_path(output_dir)
    citations_path = all_citations_path(output_dir)
    # Flat copies for convenience / docs examples.
    flat_evidence = output_dir / ALL_EVIDENCE_CSV
    flat_citations = output_dir / ALL_CITATIONS_CSV
    write_evidence_csv(evidence_path, merged)
    write_citations_csv(citations_path, merged)
    write_evidence_csv(flat_evidence, merged)
    write_citations_csv(flat_citations, merged)
    summary = ScmExportSummary(
        literature_records=sum(1 for r in merged if r.source_type == "Literature"),
        web_records=sum(1 for r in merged if r.source_type == "Web"),
        discovery_records=sum(1 for r in merged if r.pipeline_branch == "open_discovery"),
        merged_records=len(merged),
        exact_duplicates_removed=merge_stats.exact_duplicates_removed,
        complementary_fields_filled=merge_stats.complementary_fields_filled,
        all_evidence_path=str(evidence_path),
        all_citations_path=str(citations_path),
    )
    for line in summary.to_log_lines():
        logger.info(line)
    return summary


def export_discovery_evidence_csv(path: Path, rows: list[ScmDiscoveryRow]) -> Path:
    return write_discovery_csv(path, rows)


def export_discovered_categories_csv(path: Path, rows: list[dict]) -> Path:
    return write_dict_csv(path, rows, DISCOVERED_CATEGORY_FIELDS)


def export_normalization_csv(path: Path, rows: list[dict]) -> Path:
    return write_dict_csv(path, rows, NORMALIZATION_FIELDS)


def discovery_evidence_csv_name() -> str:
    return DISCOVERY_EVIDENCE_CSV


def discovered_categories_csv_name() -> str:
    return DISCOVERED_CATEGORIES_CSV


def normalization_csv_name() -> str:
    return NORMALIZATION_CSV
