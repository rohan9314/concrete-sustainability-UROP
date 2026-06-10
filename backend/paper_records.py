"""Local pickle-file retrieval for cement/concrete scientific paper records."""

from __future__ import annotations

import os
import pickle
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ENV_PAPER_RECORDS_PATH = "PAPER_RECORDS_PATH"

SEARCHABLE_FIELDS = (
    "title",
    "abstract",
    "keywords",
    "doi",
    "authors",
    "journal",
    "year",
    "url",
    "full_text",
    "text",
)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "for",
        "of",
        "in",
        "on",
        "to",
        "with",
        "by",
        "is",
        "are",
        "as",
        "at",
        "from",
        "that",
        "this",
        "be",
        "it",
    }
)

_cache_lock = threading.Lock()
_cached_records: list[dict] | None = None
_cached_path: str | None = None


class PaperDatabaseConfigError(Exception):
    """Raised when PAPER_RECORDS_PATH is not configured."""


class PaperDatabaseNotFoundError(Exception):
    """Raised when the local paper database file is missing."""


class PaperDatabaseLoadError(Exception):
    """Raised when the local paper database cannot be loaded."""


def get_paper_records_path() -> str:
    """Return the configured paper database path from the environment."""
    value = os.getenv(ENV_PAPER_RECORDS_PATH, "").strip()
    if not value:
        raise PaperDatabaseConfigError(
            f"{ENV_PAPER_RECORDS_PATH} is not set. Add it to backend/.env with the "
            "absolute path to your local confidential paper database file."
        )
    return value


def resolve_records_path(path: str | None = None) -> Path:
    """Resolve the paper database path from an explicit argument or PAPER_RECORDS_PATH."""
    configured = path or get_paper_records_path()
    return Path(configured).expanduser().resolve()


def load_paper_records(path: str | None = None, *, force_reload: bool = False) -> list[dict]:
    """
    Load cement/concrete paper records from the local pickle file.

    Records are cached in memory after the first successful load.
    """
    global _cached_records, _cached_path

    resolved = resolve_records_path(path)
    resolved_str = str(resolved)

    with _cache_lock:
        if (
            not force_reload
            and _cached_records is not None
            and _cached_path == resolved_str
        ):
            return _cached_records

        if not resolved.is_file():
            raise PaperDatabaseNotFoundError(
                "Local paper database not found at the path configured in "
                f"{ENV_PAPER_RECORDS_PATH}: {resolved}. "
                "This file is confidential and must remain gitignored."
            )

        try:
            with resolved.open("rb") as handle:
                raw = pickle.load(handle)
        except Exception as exc:
            raise PaperDatabaseLoadError(
                "Failed to load local paper database. Verify that the file at "
                f"{ENV_PAPER_RECORDS_PATH} is valid and readable."
            ) from exc

        if isinstance(raw, list):
            records = [item for item in raw if isinstance(item, dict)]
        elif isinstance(raw, dict):
            records = [value for value in raw.values() if isinstance(value, dict)]
        else:
            records = []

        if not records:
            raise PaperDatabaseLoadError(
                "Local paper database loaded but contained no usable records."
            )

        _cached_records = records
        _cached_path = resolved_str
        return records


def is_paper_database_available(path: str | None = None) -> bool:
    """Return True when PAPER_RECORDS_PATH is set and the file exists."""
    try:
        return resolve_records_path(path).is_file()
    except PaperDatabaseConfigError:
        return False


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [token for token in tokens if len(token) > 2 and token not in _STOPWORDS]


def _stringify_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value[:50]:
            if isinstance(item, dict):
                for key in ("text", "title", "name", "value", "keyword"):
                    if key in item and item[key]:
                        parts.append(_stringify_value(item[key]))
                        break
                else:
                    parts.append(_stringify_value(item))
            else:
                parts.append(_stringify_value(item))
        return " ".join(part for part in parts if part)
    if isinstance(value, dict):
        return " ".join(_stringify_value(item) for item in value.values())
    return str(value)


def _paragraph_text(record: dict, max_paragraphs: int = 5, max_chars: int = 4000) -> str:
    paragraphs = record.get("paragraphs") or []
    if not isinstance(paragraphs, list):
        return ""

    chunks: list[str] = []
    for paragraph in paragraphs[:max_paragraphs]:
        if isinstance(paragraph, dict):
            text = paragraph.get("text") or paragraph.get("content") or ""
            if text:
                chunks.append(str(text))
        elif paragraph:
            chunks.append(str(paragraph))

    combined = "\n".join(chunks)
    return combined[:max_chars]


def _record_year(record: dict) -> str:
    for key in ("year", "publication_year", "pub_year"):
        value = record.get(key)
        if value:
            return str(value)

    modified = record.get("modified")
    if modified is not None:
        try:
            return str(datetime.fromtimestamp(int(modified), tz=timezone.utc).year)
        except (TypeError, ValueError, OSError):
            pass
    return ""


def record_to_searchable_text(record: dict) -> str:
    """Flatten a record into searchable plain text."""
    if not isinstance(record, dict):
        return _stringify_value(record)

    parts: list[str] = []
    for field in SEARCHABLE_FIELDS:
        if field in record:
            parts.append(_stringify_value(record[field]))

    for key, value in record.items():
        if key not in SEARCHABLE_FIELDS:
            parts.append(_stringify_value(value))

    parts.append(_paragraph_text(record, max_paragraphs=3, max_chars=1500))
    return " ".join(part for part in parts if part).lower()


def _field_text(record: dict, field: str) -> str:
    return _stringify_value(record.get(field)).lower()


def _score_record(record: dict, tokens: list[str]) -> float:
    if not tokens:
        return 0.0

    title = _field_text(record, "title")
    abstract = _field_text(record, "abstract")
    keywords = _field_text(record, "keywords")
    doi = _field_text(record, "doi")
    body = record_to_searchable_text(record)

    score = 0.0
    for token in tokens:
        if token in title:
            score += 12.0
        if token in keywords:
            score += 8.0
        if token in abstract:
            score += 4.0
        if token in doi:
            score += 3.0
        if token in body:
            score += 1.0

    return score


def search_paper_records(
    query: str,
    records: list[dict] | None = None,
    *,
    top_k: int = 10,
    path: str | None = None,
) -> list[dict]:
    """Return the top-k most relevant paper records for a query."""
    if records is None:
        records = load_paper_records(path)

    tokens = _tokenize(query)
    if not tokens:
        return []

    scored: list[tuple[float, dict]] = []
    for record in records:
        score = _score_record(record, tokens)
        if score > 0:
            scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [record for _, record in scored[:top_k]]


def record_to_source(record: dict, *, score: float | None = None) -> dict:
    """Convert a pickle record into the standardized source format."""
    title = str(record.get("title") or "Untitled paper")
    doi = str(record.get("doi") or "").strip()
    url = str(record.get("url") or "").strip()
    if not url and doi:
        url = f"https://doi.org/{doi}"

    abstract = str(record.get("abstract") or "").strip()
    paragraph_text = _paragraph_text(record)
    full_text = abstract
    if paragraph_text and paragraph_text not in full_text:
        full_text = f"{full_text}\n\n{paragraph_text}".strip() if full_text else paragraph_text

    keywords = record.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = []

    snippet = abstract[:500] if abstract else paragraph_text[:500]

    return {
        "title": title,
        "url": url,
        "source_type": "scientific_paper",
        "snippet": snippet,
        "full_text": full_text[:12000],
        "metadata": {
            "authors": [],
            "year": _record_year(record),
            "journal": str(record.get("journal") or ""),
            "doi": doi,
        },
        "_local_score": score,
        "_keywords": [str(keyword) for keyword in keywords[:10]],
    }


def _record_dedupe_key(record: dict) -> str:
    doi = str(record.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"

    url = str(record.get("url") or "").strip().lower()
    if url:
        return f"url:{url}"

    title = str(record.get("title") or "").strip().lower()
    return f"title:{title}" if title else ""


def retrieve_paper_sources(query: str, max_results: int = 10) -> list[dict]:
    """
    Search the local paper database and return standardized scientific_paper sources.

    # TODO: Add optional indexing/cache if full-corpus scans become too slow.
    """
    return retrieve_paper_sources_multi([query], max_per_query=max_results, max_total=max_results)


def retrieve_paper_sources_multi(
    queries: list[str],
    *,
    max_per_query: int = 15,
    max_total: int = 30,
) -> list[dict]:
    """
    Search the full paper database with multiple queries, deduplicate, and rank.

    Every query scans all records; the best-scoring match per paper is kept.
    """
    records = load_paper_records()
    best_matches: dict[str, tuple[float, dict]] = {}

    for query in queries:
        query = query.strip()
        if not query:
            continue

        tokens = _tokenize(query)
        matches = search_paper_records(query, records, top_k=max_per_query)
        for record in matches:
            dedupe_key = _record_dedupe_key(record)
            if not dedupe_key:
                continue

            score = _score_record(record, tokens)
            existing = best_matches.get(dedupe_key)
            if existing is None or score > existing[0]:
                best_matches[dedupe_key] = (score, record)

    ranked = sorted(best_matches.values(), key=lambda item: item[0], reverse=True)
    sources: list[dict] = []
    for score, record in ranked[:max_total]:
        source = record_to_source(record, score=score)
        source.pop("_local_score", None)
        source.pop("_keywords", None)
        sources.append(source)

    return sources


def format_records_for_llm(sources: list[dict]) -> str:
    """Format local paper sources for inclusion in an LLM prompt."""
    sections: list[str] = []
    for index, source in enumerate(sources, start=1):
        metadata = source.get("metadata") or {}
        body = source.get("full_text") or source.get("snippet") or "No content available."
        meta_lines: list[str] = []
        if metadata.get("year"):
            meta_lines.append(f"Year: {metadata['year']}")
        if metadata.get("journal"):
            meta_lines.append(f"Journal: {metadata['journal']}")
        if metadata.get("doi"):
            meta_lines.append(f"DOI: {metadata['doi']}")

        metadata_block = "\n".join(meta_lines)
        if metadata_block:
            metadata_block = f"{metadata_block}\n"

        sections.append(
            f"--- LOCAL PAPER {index} ---\n"
            f"Title: {source.get('title', '')}\n"
            f"URL: {source.get('url', '')}\n"
            f"Source Type: scientific_paper\n"
            f"Origin: Local cement/concrete paper database\n"
            f"{metadata_block}"
            f"Content:\n{body}\n"
        )

    return "\n".join(sections)
