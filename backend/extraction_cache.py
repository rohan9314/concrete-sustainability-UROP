"""Simple file cache for per-source extraction results."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROMPT_VERSION = "source_extract_v1"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "cache"


def get_cache_dir() -> Path:
    configured = os.getenv("CACHE_DIR", "").strip()
    path = Path(configured) if configured else DEFAULT_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(
    *,
    source_id: str,
    technology_name: str,
    model: str,
    prompt_version: str = PROMPT_VERSION,
    question_set: str = "structured_intelligence",
) -> str:
    payload = "|".join(
        [source_id, technology_name, model, prompt_version, question_set]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_cached_extraction(
    *,
    source_id: str,
    technology_name: str,
    model: str,
    question_set: str = "structured_intelligence",
    prompt_version: str = PROMPT_VERSION,
) -> dict | None:
    key = _cache_key(
        source_id=source_id,
        technology_name=technology_name,
        model=model,
        prompt_version=prompt_version,
        question_set=question_set,
    )
    path = get_cache_dir() / f"{key}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_cached_extraction(
    *,
    source_id: str,
    technology_name: str,
    model: str,
    payload: dict,
    question_set: str = "structured_intelligence",
    prompt_version: str = PROMPT_VERSION,
) -> None:
    key = _cache_key(
        source_id=source_id,
        technology_name=technology_name,
        model=model,
        prompt_version=prompt_version,
        question_set=question_set,
    )
    path = get_cache_dir() / f"{key}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
