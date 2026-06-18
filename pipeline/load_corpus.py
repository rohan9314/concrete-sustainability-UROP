"""Stage 1: load the local paper corpus into normalized paper objects."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from paper_records import (  # noqa: E402
    _paragraph_text,
    _record_dedupe_key,
    _stringify_value,
    load_paper_records,
)

from pipeline.config import get_pickle_path
from pipeline.schema import FilteredPaper, NOT_REPORTED
from pipeline.year_utils import normalize_publication_year

logger = logging.getLogger(__name__)


def _normalize_authors(record: dict) -> list[str]:
    authors = record.get("authors") or []
    if isinstance(authors, str):
        return [authors.strip()] if authors.strip() else []
    if not isinstance(authors, list):
        return []
    result: list[str] = []
    for author in authors:
        text = _stringify_value(author).strip()
        if text:
            result.append(text)
    return result[:20]


def normalize_paper(record: dict, index: int) -> FilteredPaper:
    """Convert a raw pickle record into a stable normalized paper object."""
    paper_id = _record_dedupe_key(record) or f"paper:{index}"
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    paragraph_text = _paragraph_text(record, max_paragraphs=3, max_chars=2000)
    snippet = abstract[:500] if abstract else paragraph_text[:500]
    text = abstract
    if paragraph_text and paragraph_text not in text:
        text = f"{text}\n\n{paragraph_text}".strip() if text else paragraph_text

    doi = str(record.get("doi") or "").strip()
    url = str(record.get("url") or "").strip()
    if not url and doi:
        url = f"https://doi.org/{doi}"

    year, year_source = normalize_publication_year(record)

    return FilteredPaper(
        paper_id=paper_id,
        relevance_score=0.0,
        matched_keywords=[],
        title=title or "Untitled paper",
        abstract=abstract,
        authors=_normalize_authors(record),
        year=year,
        year_source=year_source,
        doi=doi,
        url=url,
        snippet=snippet,
        text=text[:12000],
    )


def load_corpus(
    *,
    start: int = 0,
    end: int | None = None,
    path: str | Path | None = None,
) -> list[FilteredPaper]:
    """
    Load papers from the pickle corpus.

    For corpus shards, pass start/end to process only an index slice without
    requiring separate pickle files.
    """
    pickle_path = Path(path) if path else get_pickle_path()
    logger.info("load_corpus: loading from %s slice [%s:%s]", pickle_path, start, end)
    records = load_paper_records(str(pickle_path))
    slice_records = records[start:end]
    papers = [
        normalize_paper(record, start + offset)
        for offset, record in enumerate(slice_records)
    ]
    logger.info("load_corpus: normalized %s papers", len(papers))
    return papers
