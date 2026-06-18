"""Stage 3: rank filtered papers by likely usefulness."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from pipeline.config import get_top_n_sources
from pipeline.schema import FilteredPaper, RankedPaper

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


def _title_match_bonus(title: str, keywords: list[str]) -> float:
    title_lower = title.lower()
    return sum(2.0 for keyword in keywords if keyword in title_lower)


def _abstract_match_bonus(abstract: str, keywords: list[str]) -> float:
    abstract_lower = abstract.lower()
    return sum(1.0 for keyword in keywords if keyword in abstract_lower)


def rank_sources(
    papers: list[FilteredPaper],
    *,
    top_n: int | None = None,
    query_terms: list[str] | None = None,
) -> list[RankedPaper]:
    """Rank filtered papers and return the top N."""
    top_n = top_n or get_top_n_sources()
    query_terms = query_terms or []
    ranked: list[RankedPaper] = []

    for paper in papers:
        text = " ".join(
            part
            for part in [paper.title, paper.abstract, paper.snippet, paper.text]
            if part
        )

        rank_score = paper.relevance_score
        rank_score += _LABEL_BONUS.get(paper.relevance_label, 0.0)
        rank_score += _title_match_bonus(paper.title, query_terms)
        rank_score += _abstract_match_bonus(paper.abstract, query_terms)
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
    result = ranked[:top_n]
    logger.info("rank_sources: returning top %s of %s ranked papers", len(result), len(ranked))
    return result
