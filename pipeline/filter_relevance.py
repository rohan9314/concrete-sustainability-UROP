"""Stage 2: cheap keyword relevance filtering (no LLM)."""

from __future__ import annotations

import logging
import re

from pipeline.schema import FilteredPaper

logger = logging.getLogger(__name__)

DOMAIN_KEYWORDS: list[tuple[str, float]] = [
    ("cement", 2.0),
    ("concrete", 2.0),
    ("clinker", 2.5),
    ("portland cement", 3.0),
    ("scm", 2.0),
    ("supplementary cementitious material", 3.5),
    ("fly ash", 2.5),
    ("slag", 1.5),
    ("calcined clay", 3.0),
    ("limestone calcined clay cement", 4.0),
    ("lc3", 3.0),
    ("carbon capture", 3.0),
    ("ccs", 2.0),
    ("cement kiln", 2.5),
    ("carbonation curing", 3.0),
    ("co2 mineralization", 3.0),
    ("aggregate", 1.5),
    ("admixture", 1.5),
    ("binder", 1.5),
    ("low-carbon concrete", 3.5),
    ("decarbonization", 2.5),
    ("emissions intensity", 3.0),
    ("co2 reduction", 2.5),
    ("greenhouse gas", 2.0),
    ("pilot", 1.0),
    ("demonstration", 1.0),
    ("commercial", 1.0),
]

MIN_RELEVANCE_SCORE = 2.0


def _paper_text(paper: FilteredPaper) -> str:
    parts = [paper.title, paper.abstract, paper.snippet, paper.text]
    return " ".join(part for part in parts if part).lower()


def filter_relevance(
    papers: list[FilteredPaper],
    *,
    min_score: float = MIN_RELEVANCE_SCORE,
    query_terms: list[str] | None = None,
) -> list[FilteredPaper]:
    """
    Filter papers using cement/concrete decarbonization keyword matching.

    Outputs paper_id, relevance_score, matched_keywords, and metadata.
    """
    query_terms = [term.strip().lower() for term in (query_terms or []) if term.strip()]
    filtered: list[FilteredPaper] = []

    for paper in papers:
        text = _paper_text(paper)
        if not text.strip():
            continue

        score = 0.0
        matched: list[str] = []

        for keyword, weight in DOMAIN_KEYWORDS:
            if keyword in text:
                score += weight
                matched.append(keyword)

        for term in query_terms:
            if term in text:
                score += 3.0
                matched.append(term)

        if score < min_score:
            continue

        filtered.append(
            paper.model_copy(
                update={
                    "relevance_score": round(score, 3),
                    "matched_keywords": sorted(set(matched)),
                },
            ),
        )

    filtered.sort(key=lambda item: item.relevance_score, reverse=True)
    logger.info(
        "filter_relevance: kept %s/%s papers (min_score=%s)",
        len(filtered),
        len(papers),
        min_score,
    )
    return filtered


def tokenize_query(query: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2
    ]
