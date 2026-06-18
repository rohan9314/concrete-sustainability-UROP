"""Serve prepared technology database records to the frontend."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.config import resolve_data_path
from pipeline.export_database import load_database
from pipeline.schema import TechnologyRecord
from source_registry import attach_record_bibliography

NOT_REPORTED = "Not Reported"


def get_database_path() -> Path:
    raw = os.getenv("TECH_DATABASE_PATH", "./data/sample_technology_database.json").strip()
    return resolve_data_path(raw)


def _enrich_record(record: TechnologyRecord) -> dict:
    return attach_record_bibliography(record.model_dump())


def list_technology_records() -> list[TechnologyRecord]:
    database = load_database(get_database_path())
    return database.records


def list_technology_record_payloads() -> list[dict]:
    return [_enrich_record(record) for record in list_technology_records()]


def search_technology_records(query: str, *, limit: int = 20) -> list[dict]:
    query_lower = query.strip().lower()
    if not query_lower:
        return list_technology_record_payloads()[:limit]

    scored: list[tuple[float, TechnologyRecord]] = []
    for record in list_technology_records():
        haystack = " ".join(
            [
                record.technology_name,
                record.technology_category,
                record.company_or_organization,
                record.technical_description,
                " ".join(record.performance_metrics),
            ],
        ).lower()
        if query_lower in haystack:
            score = 0.0
            if query_lower in record.technology_name.lower():
                score += 10.0
            if query_lower in record.company_or_organization.lower():
                score += 6.0
            if query_lower in record.technology_category.lower():
                score += 4.0
            score += 1.0
            scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [_enrich_record(record) for _, record in scored[:limit]]


def get_technology_record(record_id: str) -> dict | None:
    for record in list_technology_records():
        if record.record_id == record_id:
            return _enrich_record(record)
    return None
