"""Load canonical carbon capture pipeline outputs for the API."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.carbon_capture_export import read_canonical_csv, read_jsonl_rows
from pipeline.carbon_capture_outputs import final_output_csv_path, merged_records_path
from pipeline.config import get_output_dir


def _resolve_csv_path() -> Path:
    override = os.getenv("CARBON_CAPTURE_CSV_PATH", "").strip()
    if override:
        return Path(override)
    return final_output_csv_path(get_output_dir())


def list_carbon_capture_records() -> list[dict[str, str]]:
    csv_path = _resolve_csv_path()
    if csv_path.is_file():
        return read_canonical_csv(csv_path)

    merged_path = merged_records_path(get_output_dir())
    if merged_path.is_file():
        rows = read_jsonl_rows(merged_path)
        return [row.to_canonical_dict() for row in rows]
    return []


def get_carbon_capture_output_paths() -> dict[str, str]:
    output_dir = get_output_dir()
    return {
        "literature_records": str(output_dir / "literature_records.jsonl"),
        "literature_csv": str(output_dir / "literature_records.csv"),
        "web_records": str(output_dir / "web_records.jsonl"),
        "web_csv": str(output_dir / "web_records.csv"),
        "merged_records": str(merged_records_path(output_dir)),
        "final_output_csv": str(final_output_csv_path(output_dir)),
    }
