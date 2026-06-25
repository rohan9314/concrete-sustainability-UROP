"""Stage 3: rank filtered papers by likely usefulness."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from pipeline.config import get_top_n_sources
from pipeline.query_scoring import QueryContext, has_active_query
from pipeline.schema import FilteredPaper, RankedPaper
from pipeline.screening import screening_text_lower

logger = logging.getLogger(__name__)

QUANT_PATTERNS = [
    r"\d+\s*%",
    r"kg\s*co2e?",
    r"co2e",
    r"\bcost\b",
    r"\benergy\b",
    r"\breduction\b",
    r"\bpilot\b",
    r"\bdemonstration\b",
    r"\bcommercial\b",
]

COMPANY_PATTERNS = [
    r"\binc\.?\b",
    r"\bltd\.?\b",
    r"\bcorp\.?\b",
    r"\bcompany\b",
    r"\bproject\b",
    r"\bplant\b",
]

_LABEL_BONUS: dict[str, float] = {
    "High": 8.0,
    "Medium": 3.0,
    "Low": -4.0,
}


def _recency_bonus(year: str, year_source: str) -> float:
    if not year or year == "Not Reported" or year_source == "not_reported":
        return 0.0
    try:
        year_int = int(re.sub(r"[^\d]", "", year)[:4])
    except ValueError:
        return 0.0
    current = datetime.now().year
    if year_int < 1990 or year_int > current + 1:
        return 0.0
    age = max(0, current - year_int)
    base = max(0.0, 10.0 - age * 0.4)
    if year_source == "doi_inferred":
        return base * 0.5
    return base


def _pattern_bonus(text: str, patterns: list[str], weight: float = 1.0) -> float:
    bonus = 0.0
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            bonus += weight
    return bonus


def _phrase_title_bonus(title: str, phrases: list[str]) -> float:
    title_lower = title.lower()
    return sum(2.5 for phrase in phrases if phrase in title_lower)


def _phrase_abstract_bonus(abstract: str, phrases: list[str]) -> float:
    abstract_lower = abstract.lower()
    return sum(1.5 for phrase in phrases if phrase in abstract_lower)


def rank_sources(
    papers: list[FilteredPaper],
    *,
    top_n: int | None = None,
    query_context: QueryContext | None = None,
    query_terms: list[str] | None = None,
) -> list[RankedPaper]:
    """Rank filtered papers using title+abstract signals only."""
    if query_context is None and query_terms:
        query_context = QueryContext(query=" ".join(query_terms))

    match_phrases = [phrase for phrase, _, _ in (query_context.match_phrases if query_context else [])]
    query_active = has_active_query(query_context)
    ranked: list[RankedPaper] = []

    for paper in papers:
        # Title + abstract only for ranking bonuses (no full text).
        text = screening_text_lower(paper)

        rank_score = paper.relevance_score
        rank_score += _LABEL_BONUS.get(paper.relevance_label, 0.0)
        if query_active:
            rank_score += paper.query_score * 0.5
            rank_score += _phrase_title_bonus(paper.title, match_phrases)
            rank_score += _phrase_abstract_bonus(paper.abstract, match_phrases)
        rank_score += _recency_bonus(paper.year, paper.year_source)
        rank_score += _pattern_bonus(text, QUANT_PATTERNS, weight=1.5)
        rank_score += _pattern_bonus(text, COMPANY_PATTERNS, weight=0.8)
        rank_score -= min(4.0, len(paper.negative_topic_matches) * 1.2)

        ranked.append(
            RankedPaper(
                **paper.model_dump(),
                rank_score=round(rank_score, 3),
            ),
        )

    ranked.sort(key=lambda item: item.rank_score, reverse=True)
    if top_n == 0:
        limit = len(ranked)
    elif top_n is None:
        limit = get_top_n_sources()
    else:
        limit = top_n
    result = ranked[:limit]
    logger.info("rank_sources: returning top %s of %s ranked papers", len(result), len(ranked))
    return result
