"""
Stage 1: load the local paper corpus into normalized paper objects.

Stage 1 screening uses title + abstract only (see pipeline.screening).
Full paper text is attached later for Stage 2 extraction via attach_full_text().
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.corpus_loader import load_paper_records_slice as _load_paper_records_slice
from pipeline.corpus_text import paragraph_text, stringify_value
from pipeline.record_utils import record_dedupe_key
from pipeline.schema import FilteredPaper
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
        text = stringify_value(author).strip()
        if text:
            result.append(text)
    return result[:20]


def normalize_paper(record: dict, index: int) -> FilteredPaper:
    """
    Convert a raw pickle record into a normalized paper for Stage 1 screening.

    Does not attach paragraph/full-text content. Use attach_full_text() before
    Stage 2 extraction on papers already marked relevant.
    """
    paper_id = record_dedupe_key(record) or f"paper:{index}"
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    snippet = abstract[:500] if abstract else ""

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
        text="",
    )


def attach_full_text(paper: FilteredPaper, record: dict) -> FilteredPaper:
    """Attach paragraph body text for Stage 2 extraction (post-screening only)."""
    paragraph_body = paragraph_text(record, max_paragraphs=10, max_chars=12000)
    text = paper.abstract
    if paragraph_body and paragraph_body not in text:
        text = f"{text}\n\n{paragraph_body}".strip() if text else paragraph_body
    return paper.model_copy(update={"text": text[:12000]})


def load_paper_records_slice(
    *,
    path: str | Path | None = None,
    start: int = 0,
    end: int | None = None,
) -> tuple[list[dict], int]:
    """Load a slice of raw pickle records. Returns (records, slice_end)."""
    return _load_paper_records_slice(path=path, start=start, end=end)


def load_corpus(
    *,
    start: int = 0,
    end: int | None = None,
    path: str | Path | None = None,
    paper_ids: set[str] | None = None,
    include_full_text: bool = False,
) -> list[FilteredPaper]:
    """
    Load papers from the pickle corpus.

    By default returns title+abstract only for Stage 1 screening/ranking.
    Set include_full_text=True for Stage 2 extraction on relevant papers.
    """
    records, _ = load_paper_records_slice(path=path, start=start, end=end)
    papers: list[FilteredPaper] = []
    for offset, record in enumerate(records):
        paper = normalize_paper(record, start + offset)
        if paper_ids is not None and paper.paper_id not in paper_ids:
            continue
        if include_full_text:
            paper = attach_full_text(paper, record)
        papers.append(paper)

    logger.info("load_corpus: normalized %s papers (include_full_text=%s)", len(papers), include_full_text)
    return papers
