"""Pipeline configuration from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"


def resolve_data_path(raw: str) -> Path:
    """Resolve a config path from repo root or the current working directory."""
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()

    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.is_file():
        return cwd_candidate

    return (REPO_ROOT / path).resolve()


def get_pickle_path() -> Path:
    raw = (
        os.getenv("PICKLE_PATH", "").strip()
        or os.getenv("PAPER_RECORDS_PATH", "").strip()
    )
    if not raw:
        raise ValueError(
            "PICKLE_PATH (or PAPER_RECORDS_PATH) is not set. "
            "Add it to backend/.env with the path to your local corpus."
        )
    return Path(raw).expanduser().resolve()


def get_output_dir() -> Path:
    raw = os.getenv("OUTPUT_DIR", "./outputs").strip() or "./outputs"
    path = resolve_data_path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_tech_database_path() -> Path:
    raw = os.getenv(
        "TECH_DATABASE_PATH",
        "./data/sample_technology_database.json",
    ).strip()
    return resolve_data_path(raw)


def get_top_n_sources() -> int:
    raw = os.getenv("TOP_N_SOURCES", "50")
    try:
        value = int(raw)
    except ValueError:
        value = 50
    return max(1, min(value, 500))


def get_extraction_concurrency() -> int:
    raw = os.getenv("EXTRACTION_CONCURRENCY", "4")
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(1, min(value, 20))
