"""Retrieve ranked papers for a specific carbon capture methodology."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pipeline.carbon_capture_config import CarbonCaptureMethodology
from pipeline.filter_relevance import filter_relevance
from pipeline.load_corpus import load_corpus
from pipeline.query_scoring import QueryContext, build_query_context, score_query
from pipeline.rank_sources import rank_sources
from pipeline.schema import RankedPaper
from pipeline.screening_results import load_screening_results

logger = logging.getLogger(__name__)

_SLUG_TO_LEGACY_TECHNOLOGY: dict[str, str] = {
    "amine_absorption": "chemical absorption",
    "membrane_separation": "membrane separation",
    "calcium_looping": "calcium looping",
    "oxyfuel_combustion": "oxy-fuel combustion",
    "cryogenic_capture": "cryogenic processes",
}


def _phrase_weight(phrase: str) -> float:
    if " " in phrase:
        return 5.0
    if re.fullmatch(r"[a-z0-9]{1,4}", phrase):
        return 3.5
    return 4.0


def build_methodology_query_context(methodology: CarbonCaptureMethodology) -> QueryContext:
    """Build a query context with methodology-specific keywords and synonyms."""
    context = build_query_context(query=methodology.retrieval_query, technology_name="")
    phrases: dict[str, tuple[float, str]] = {
        phrase: (weight, source) for phrase, weight, source in context.match_phrases
    }

    def add_phrase(phrase: str, source: str = "synonym") -> None:
        normalized = phrase.lower().strip()
        if not normalized:
            return
        weight = _phrase_weight(normalized)
        existing = phrases.get(normalized)
        if existing is None or weight > existing[0]:
            phrases[normalized] = (weight, source)

    legacy_name = _SLUG_TO_LEGACY_TECHNOLOGY.get(methodology.slug)
    if legacy_name:
        legacy_context = build_query_context(technology_name=legacy_name)
        for phrase, weight, source in legacy_context.match_phrases:
            existing = phrases.get(phrase)
            if existing is None or weight > existing[0]:
                phrases[phrase] = (weight, source)

    for keyword in methodology.search_keywords:
        add_phrase(keyword)
    for synonym in methodology.synonyms:
        add_phrase(synonym)

    match_phrases = sorted(
        ((phrase, weight, source) for phrase, (weight, source) in phrases.items()),
        key=lambda item: (-len(item[0]), item[0]),
    )
    query_terms = list(
        dict.fromkeys(
            [*context.query_terms, *[term.lower() for term in methodology.search_keywords]],
        ),
    )
    return QueryContext(
        query=methodology.retrieval_query,
        technology_name=methodology.display_name,
        query_terms=query_terms,
        match_phrases=match_phrases,
    )


def _paper_ids_from_screening(
    screening_path: Path,
    *,
    subpath: str | None,
) -> set[str] | None:
    if not screening_path.is_file():
        logger.warning("Screening results not found: %s", screening_path)
        return None

    _, rows = load_screening_results(screening_path)
    if subpath:
        rows = [
            row
            for row in rows
            if row.is_relevant and subpath in row.relevant_subpaths
        ]
    else:
        rows = [row for row in rows if row.is_relevant]

    paper_ids = {row.paper_id for row in rows if row.paper_id}
    logger.info(
        "Screening filter for subpath=%s retained %s papers",
        subpath or "any",
        len(paper_ids),
    )
    return paper_ids or None


def retrieve_methodology_papers(
    methodology: CarbonCaptureMethodology,
    *,
    start: int,
    end: int,
    top_n: int | None = None,
    screening_results: str | Path | None = None,
    input_path: str | Path | None = None,
    include_full_text: bool = True,
) -> list[RankedPaper]:
    """
    Load, filter, and rank corpus papers for one carbon capture methodology.

    Retrieval is methodology-specific via query context and optional Stage 1
    screening subpath filters.
    """
    paper_ids: set[str] | None = None
    if screening_results:
        screening_path = Path(screening_results)
        paper_ids = _paper_ids_from_screening(
            screening_path,
            subpath=methodology.screening_subpath,
        )

    papers = load_corpus(
        start=start,
        end=end,
        path=input_path,
        paper_ids=paper_ids,
        include_full_text=include_full_text,
    )
    query_context = build_methodology_query_context(methodology)
    filtered = filter_relevance(papers, query_context=query_context)

    if methodology.screening_subpath and not screening_results:
        filtered = [
            paper
            for paper in filtered
            if score_query(
                f"{paper.title}\n{paper.abstract}",
                query_context,
            ).strong_query_match
        ]

    ranked = rank_sources(filtered, top_n=top_n, query_context=query_context)
    logger.info(
        "Retrieved %s ranked papers for methodology=%s (loaded=%s filtered=%s)",
        len(ranked),
        methodology.slug,
        len(papers),
        len(filtered),
    )
    return ranked
