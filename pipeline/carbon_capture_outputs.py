"""Global output filenames for the carbon capture pipeline."""

from __future__ import annotations

from pathlib import Path

from pipeline.config import get_output_dir

LITERATURE_RECORDS_FILENAME = "literature_records.jsonl"
WEB_RECORDS_FILENAME = "web_records.jsonl"
MERGED_RECORDS_FILENAME = "merged_records.jsonl"
LITERATURE_CSV_FILENAME = "literature_records.csv"
WEB_CSV_FILENAME = "web_records.csv"
FINAL_OUTPUT_CSV_FILENAME = "final_output.csv"


def literature_records_path(output_dir: Path | None = None) -> Path:
    return (output_dir or get_output_dir()) / LITERATURE_RECORDS_FILENAME


def web_records_path(output_dir: Path | None = None) -> Path:
    return (output_dir or get_output_dir()) / WEB_RECORDS_FILENAME


def merged_records_path(output_dir: Path | None = None) -> Path:
    return (output_dir or get_output_dir()) / MERGED_RECORDS_FILENAME


def final_output_csv_path(output_dir: Path | None = None) -> Path:
    return (output_dir or get_output_dir()) / FINAL_OUTPUT_CSV_FILENAME


def literature_csv_path(output_dir: Path | None = None) -> Path:
    return (output_dir or get_output_dir()) / LITERATURE_CSV_FILENAME


def web_csv_path(output_dir: Path | None = None) -> Path:
    return (output_dir or get_output_dir()) / WEB_CSV_FILENAME
