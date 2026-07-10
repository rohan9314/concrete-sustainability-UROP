"""Validation report for local carbon capture test runs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pipeline.carbon_capture_export import PipelineExportSummary
from pipeline.carbon_capture_extraction import CarbonCaptureRow
from pipeline.carbon_capture_schema import (
    CANONICAL_FIELDS,
    CONFIDENCE_LEVELS,
    DEPLOYMENT_STAGES,
    METRIC_DIMENSIONS,
    NA,
    SOURCE_TYPES,
    ValidationStats,
)

VALIDATION_REPORT_FILENAME = "validation_report.json"

CONTROLLED_FIELDS = {
    "confidence": CONFIDENCE_LEVELS,
    "deployment_stage": DEPLOYMENT_STAGES,
    "source_type": SOURCE_TYPES,
    "metric_dimension": METRIC_DIMENSIONS,
}

PROSE_PATTERN = re.compile(r"\b(because|however|although|therefore|expected to)\b", re.I)


def _field_fill_rate(rows: list[CarbonCaptureRow], field: str) -> float:
    if not rows:
        return 0.0
    filled = sum(1 for row in rows if getattr(row, field) != NA)
    return round(filled / len(rows), 3)


def _prose_in_controlled_fields(rows: list[CarbonCaptureRow]) -> list[dict]:
    issues: list[dict] = []
    for row in rows:
        for field, allowed in CONTROLLED_FIELDS.items():
            value = getattr(row, field)
            if value == NA:
                continue
            if value not in allowed:
                issues.append(
                    {
                        "record_id": row.record_id,
                        "field": field,
                        "value": value,
                        "issue": "invalid_controlled_vocabulary",
                    },
                )
            elif PROSE_PATTERN.search(value):
                issues.append(
                    {
                        "record_id": row.record_id,
                        "field": field,
                        "value": value[:120],
                        "issue": "prose_in_controlled_field",
                    },
                )
    return issues


def _sample_records(rows: list[CarbonCaptureRow], limit: int = 3) -> list[dict]:
    samples: list[dict] = []
    for row in rows[:limit]:
        samples.append({field: getattr(row, field) for field in CANONICAL_FIELDS})
    return samples


def build_validation_report(
    *,
    mode: str,
    slugs: list[str],
    output_dir: Path,
    start: int,
    end: int,
    paper_limit: int | None,
    web_limit: int | None,
    literature_rows: list[CarbonCaptureRow],
    web_rows: list[CarbonCaptureRow],
    merged_rows: list[CarbonCaptureRow],
    stats: ValidationStats,
    summary: PipelineExportSummary,
) -> dict:
    all_rows = [*literature_rows, *web_rows]
    issues = _prose_in_controlled_fields(all_rows)

    return {
        "mode": mode,
        "subcategories": slugs,
        "limits": {
            "paper_limit": paper_limit,
            "web_limit": web_limit,
            "corpus_slice": [start, end],
        },
        "counts": {
            "literature_records": summary.literature_records,
            "web_records": summary.web_records,
            "merged_records": summary.merged_records,
            "final_csv_rows": summary.final_csv_rows,
            "project_specific_rows": summary.project_specific_rows,
            "rows_without_project": summary.rows_without_project,
        },
        "validation": {
            "invalid_controlled_values_corrected": summary.invalid_controlled_values_corrected,
            "missing_values_normalized": summary.missing_values_normalized,
            "exact_duplicates_removed": summary.exact_duplicates_removed,
            "duplicate_columns_removed": summary.duplicate_columns_removed or [],
            "controlled_field_issues_remaining": issues,
            "field_fill_rates": {
                field: _field_fill_rate(merged_rows, field) for field in CANONICAL_FIELDS
            },
        },
        "outputs": {
        "literature_records": summary.literature_path,
        "literature_csv": summary.literature_csv_path,
        "web_records": summary.web_path,
        "web_csv": summary.web_csv_path,
        "merged_records": summary.merged_path,
        "final_output_csv": summary.csv_path,
            "validation_report": str(output_dir / VALIDATION_REPORT_FILENAME),
        },
        "sample_merged_records": _sample_records(merged_rows),
        "warnings": stats.warnings[:20],
    }


def write_validation_report(path: Path, report: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
