"""Stage 2: cheap keyword relevance filtering (no LLM)."""

from __future__ import annotations

import logging
import re

from pipeline.relevance_scoring import passes_relevance_filter, score_relevance
from pipeline.schema import FilteredPaper

logger = logging.getLogger(__name__)

MIN_RELEVANCE_SCORE = 2.5


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
    Filter papers using tiered cement/concrete decarbonization keyword matching.

    Outputs paper_id, relevance_score, matched tier keywords, relevance_label,
    and relevance_reason.
    """
    query_terms = [term.strip().lower() for term in (query_terms or []) if term.strip()]
    filtered: list[FilteredPaper] = []

    for paper in papers:
        text = _paper_text(paper)
        if not text.strip():
            continue

        result = score_relevance(text, query_terms=query_terms)
        if not passes_relevance_filter(result, min_score=min_score):
            continue

        filtered.append(
            paper.model_copy(
                update={
                    "relevance_score": result.relevance_score,
                    "matched_keywords": result.matched_keywords,
                    "matched_tier1_keywords": result.matched_tier1_keywords,
                    "matched_tier2_keywords": result.matched_tier2_keywords,
                    "matched_tier3_keywords": result.matched_tier3_keywords,
                    "negative_topic_matches": result.negative_topic_matches,
                    "relevance_label": result.relevance_label,
                    "relevance_reason": result.relevance_reason,
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
