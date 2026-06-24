"""Stage 2: keyword relevance filtering using title + abstract only (no full text)."""

from __future__ import annotations

import logging

from pipeline.query_scoring import QueryContext, has_active_query
from pipeline.relevance_scoring import passes_relevance_filter, score_relevance
from pipeline.schema import FilteredPaper
from pipeline.screening import screening_text_lower

logger = logging.getLogger(__name__)

MIN_RELEVANCE_SCORE = 2.5


def filter_relevance(
    papers: list[FilteredPaper],
    *,
    min_score: float = MIN_RELEVANCE_SCORE,
    query_context: QueryContext | None = None,
    query_terms: list[str] | None = None,
) -> list[FilteredPaper]:
    """
    Filter papers using tiered cement/concrete decarbonization keyword matching.

    Stage 1 screening input is title + abstract only; full paper text is excluded.
    """
    if query_context is None and query_terms:
        query_context = QueryContext(query=" ".join(query_terms))

    query_active = has_active_query(query_context)
    filtered: list[FilteredPaper] = []

    for paper in papers:
        text = screening_text_lower(paper)
        if not text.strip():
            continue

        result = score_relevance(text, query_context=query_context)
        if not passes_relevance_filter(result, min_score=min_score, query_active=query_active):
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
                    "query_matches": result.query_matches,
                    "technology_synonym_matches": result.technology_synonym_matches,
                    "query_score": result.query_score,
                },
            ),
        )

    filtered.sort(
        key=lambda item: (item.query_score, item.relevance_score),
        reverse=True,
    )
    logger.info(
        "filter_relevance: kept %s/%s papers (min_score=%s, query_active=%s)",
        len(filtered),
        len(papers),
        min_score,
        query_active,
    )
    return filtered
