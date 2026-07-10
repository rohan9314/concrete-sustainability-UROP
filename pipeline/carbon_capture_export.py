"""Export carbon capture extraction results to canonical CSV and JSONL outputs."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pipeline.carbon_capture_config import CarbonCaptureMethodology
from pipeline.carbon_capture_extraction import CarbonCaptureRow
from pipeline.carbon_capture_merge import (
    MergeStats,
    conservative_merge_rows,
    count_project_specific_rows,
    count_rows_without_project,
)
from pipeline.carbon_capture_outputs import (
    FINAL_OUTPUT_CSV_FILENAME,
    LITERATURE_CSV_FILENAME,
    LITERATURE_RECORDS_FILENAME,
    MERGED_RECORDS_FILENAME,
    WEB_CSV_FILENAME,
    WEB_RECORDS_FILENAME,
    final_output_csv_path,
    literature_csv_path,
    literature_records_path,
    merged_records_path,
    web_csv_path,
    web_records_path,
)
from pipeline.carbon_capture_schema import CANONICAL_FIELDS, ValidationStats

logger = logging.getLogger(__name__)


@dataclass
class PipelineExportSummary:
    literature_records: int = 0
    web_records: int = 0
    merged_records: int = 0
    final_csv_rows: int = 0
    project_specific_rows: int = 0
    rows_without_project: int = 0
    invalid_controlled_values_corrected: int = 0
    missing_values_normalized: int = 0
    exact_duplicates_removed: int = 0
    complementary_fields_filled: int = 0
    duplicate_columns_removed: list[str] | None = None
    literature_path: str = ""
    web_path: str = ""
    literature_csv_path: str = ""
    web_csv_path: str = ""
    merged_path: str = ""
    csv_path: str = ""

    def to_log_lines(self) -> list[str]:
        dupes = ", ".join(self.duplicate_columns_removed or []) or "none"
        return [
            f"Literature records extracted: {self.literature_records}",
            f"Web records extracted: {self.web_records}",
            f"Merged records: {self.merged_records}",
            f"Final CSV rows: {self.final_csv_rows}",
            f"Project-specific rows: {self.project_specific_rows}",
            f"Rows with N.A. project_name: {self.rows_without_project}",
            f"Invalid controlled vocabulary values corrected: {self.invalid_controlled_values_corrected}",
            f"Missing values normalized to N.A.: {self.missing_values_normalized}",
            f"Exact duplicate rows removed: {self.exact_duplicates_removed}",
            f"Complementary descriptive fields filled: {self.complementary_fields_filled}",
            f"Duplicate columns removed: {dupes}",
            f"Literature JSONL: {self.literature_path}",
            f"Literature CSV: {self.literature_csv_path}",
            f"Web JSONL: {self.web_path}",
            f"Web CSV: {self.web_csv_path}",
            f"Merged JSONL: {self.merged_path}",
            f"Final merged CSV: {self.csv_path}",
        ]


# Backward-compatible alias for per-methodology exports.
ExportSummary = PipelineExportSummary


def write_jsonl_rows(path: Path, rows: list[CarbonCaptureRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        meta = {"type": "carbon_capture_rows_meta", "row_count": len(rows)}
        handle.write(json.dumps(meta) + "\n")
        for row in rows:
            payload = row.to_dict()
            payload["type"] = "carbon_capture_row"
            handle.write(json.dumps(payload) + "\n")
    return path


def read_jsonl_rows(path: str | Path) -> list[CarbonCaptureRow]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    rows: list[CarbonCaptureRow] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if payload.get("type") != "carbon_capture_row":
            continue
        data = {key: value for key, value in payload.items() if key != "type"}
        rows.append(CarbonCaptureRow(**data))
    return rows


def write_canonical_csv(path: Path, rows: list[CarbonCaptureRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CANONICAL_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_canonical_dict())
    return path


def read_canonical_csv(path: str | Path) -> list[dict[str, str]]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    with file_path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def export_pipeline_outputs(
    *,
    literature_rows: list[CarbonCaptureRow],
    web_rows: list[CarbonCaptureRow],
    output_dir: Path,
    stats: ValidationStats | None = None,
    merge_stats: MergeStats | None = None,
) -> tuple[Path, Path, Path, Path, PipelineExportSummary]:
    """Write global literature, web, merged JSONL files and final canonical CSV."""
    local_stats = stats or ValidationStats()
    output_dir.mkdir(parents=True, exist_ok=True)

    lit_jsonl_path = literature_records_path(output_dir)
    web_jsonl_path = web_records_path(output_dir)
    lit_csv_path = literature_csv_path(output_dir)
    web_csv_out_path = web_csv_path(output_dir)
    merged_path = merged_records_path(output_dir)
    csv_path = final_output_csv_path(output_dir)

    write_jsonl_rows(lit_jsonl_path, literature_rows)
    write_jsonl_rows(web_jsonl_path, web_rows)
    write_canonical_csv(lit_csv_path, literature_rows)
    write_canonical_csv(web_csv_out_path, web_rows)

    merged_rows, local_merge_stats = conservative_merge_rows(literature_rows, web_rows)
    if merge_stats is not None:
        merge_stats.literature_input = local_merge_stats.literature_input
        merge_stats.web_input = local_merge_stats.web_input
        merge_stats.exact_duplicates_removed = local_merge_stats.exact_duplicates_removed
        merge_stats.complementary_fields_filled = local_merge_stats.complementary_fields_filled
        merge_stats.merged_output = local_merge_stats.merged_output
    else:
        merge_stats = local_merge_stats

    write_jsonl_rows(merged_path, merged_rows)
    write_canonical_csv(csv_path, merged_rows)

    invalid_corrected = (
        local_stats.invalid_confidence_corrected
        + local_stats.invalid_deployment_stage_corrected
        + local_stats.invalid_source_type_corrected
        + local_stats.invalid_metric_dimension_corrected
    )

    summary = PipelineExportSummary(
        literature_records=len(literature_rows),
        web_records=len(web_rows),
        merged_records=len(merged_rows),
        final_csv_rows=len(merged_rows),
        project_specific_rows=count_project_specific_rows(merged_rows),
        rows_without_project=count_rows_without_project(merged_rows),
        invalid_controlled_values_corrected=invalid_corrected,
        missing_values_normalized=local_stats.missing_values_normalized,
        exact_duplicates_removed=merge_stats.exact_duplicates_removed,
        complementary_fields_filled=merge_stats.complementary_fields_filled,
        duplicate_columns_removed=local_stats.duplicate_columns_removed,
        literature_path=str(lit_jsonl_path),
        web_path=str(web_jsonl_path),
        literature_csv_path=str(lit_csv_path),
        web_csv_path=str(web_csv_out_path),
        merged_path=str(merged_path),
        csv_path=str(csv_path),
    )

    for line in summary.to_log_lines():
        logger.info(line)

    return lit_jsonl_path, web_jsonl_path, merged_path, csv_path, summary


def merge_existing_outputs(
    output_dir: Path,
    *,
    stats: ValidationStats | None = None,
) -> tuple[Path, Path, PipelineExportSummary]:
    """Re-run merge from existing literature/web JSONL files."""
    literature_rows = read_jsonl_rows(literature_records_path(output_dir))
    web_rows = read_jsonl_rows(web_records_path(output_dir))
    _, _, merged_path, csv_path, summary = export_pipeline_outputs(
        literature_rows=literature_rows,
        web_rows=web_rows,
        output_dir=output_dir,
        stats=stats,
    )
    return merged_path, csv_path, summary


def export_methodology_outputs(
    *,
    literature_rows: list[CarbonCaptureRow],
    web_rows: list[CarbonCaptureRow],
    methodology: CarbonCaptureMethodology,
    output_dir: Path,
    stats: ValidationStats | None = None,
    deduplicate_on_merge: bool = False,
) -> tuple[Path, Path, Path, PipelineExportSummary]:
    """Write per-methodology literature/web JSONL and merged canonical CSV."""
    local_stats = stats or ValidationStats()
    output_dir.mkdir(parents=True, exist_ok=True)

    literature_path = output_dir / methodology.literature_filename
    web_path = output_dir / methodology.web_filename
    csv_path = output_dir / methodology.answers_filename

    write_jsonl_rows(literature_path, literature_rows)
    write_jsonl_rows(web_path, web_rows)
    write_canonical_csv(output_dir / f"{methodology.slug}_literature.csv", literature_rows)
    write_canonical_csv(output_dir / f"{methodology.slug}_web.csv", web_rows)

    if deduplicate_on_merge:
        merged_rows, _ = conservative_merge_rows(literature_rows, web_rows)
    else:
        merged_rows = [*literature_rows, *web_rows]

    write_canonical_csv(csv_path, merged_rows)

    invalid_corrected = (
        local_stats.invalid_confidence_corrected
        + local_stats.invalid_deployment_stage_corrected
        + local_stats.invalid_source_type_corrected
        + local_stats.invalid_metric_dimension_corrected
    )

    summary = PipelineExportSummary(
        literature_records=len(literature_rows),
        web_records=len(web_rows),
        merged_records=len(merged_rows),
        final_csv_rows=len(merged_rows),
        project_specific_rows=count_project_specific_rows(merged_rows),
        rows_without_project=count_rows_without_project(merged_rows),
        invalid_controlled_values_corrected=invalid_corrected,
        missing_values_normalized=local_stats.missing_values_normalized,
        duplicate_columns_removed=local_stats.duplicate_columns_removed,
        literature_path=str(literature_path),
        web_path=str(web_path),
        merged_path=str(csv_path),
        csv_path=str(csv_path),
    )

    for line in summary.to_log_lines():
        logger.info(line)

    return literature_path, web_path, csv_path, summary


def log_export_summary(summary: PipelineExportSummary) -> None:
    for line in summary.to_log_lines():
        logger.info(line)
