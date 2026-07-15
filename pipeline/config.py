"""Pipeline configuration from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")

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
    """
    Resolve the paper corpus pickle from PICKLE_PATH / PAPER_RECORDS_PATH.

    Does not assume the pickle lives inside the repository. The env var may be
    an absolute path or a path relative to the current working directory.
    """
    raw = (
        os.getenv("PICKLE_PATH", "").strip()
        or os.getenv("PAPER_RECORDS_PATH", "").strip()
    )
    if not raw:
        raise ValueError(
            "PICKLE_PATH (or PAPER_RECORDS_PATH) is not set. "
            "Export it to the absolute path of your corpus pickle, e.g.\n"
            "  export PICKLE_PATH=/path/to/filtered_records_rohan.pkl"
        )

    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()

    # Relative paths resolve against CWD first (cluster jobs often set CWD=REPO_ROOT).
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return path.resolve()


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
