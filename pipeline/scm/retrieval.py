"""Retrieve and rank corpus papers for an SCM seed category or discovery query."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pipeline.filter_relevance import filter_relevance
from pipeline.load_corpus import load_corpus
from pipeline.query_scoring import QueryContext, build_query_context
from pipeline.rank_sources import rank_sources
from pipeline.schema import RankedPaper
from pipeline.screening_results import load_screening_results
from pipeline.scm.seed_categories import ScmSeedCategory

logger = logging.getLogger(__name__)

DISCOVERY_RETRIEVAL_QUERY = (
    "supplementary cementitious material SCM pozzolan cement replacement "
    "clinker substitution binder concrete mortar"
)


def _phrase_weight(phrase: str) -> float:
    if " " in phrase:
        return 5.0
    if re.fullmatch(r"[a-z0-9]{1,4}", phrase):
        return 3.5
    return 4.0


def build_seed_query_context(category: ScmSeedCategory) -> QueryContext:
    context = build_query_context(query=category.retrieval_query, technology_name="")
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

    for term in category.search_terms:
        add_phrase(term)
    for synonym in category.synonyms:
        add_phrase(synonym)
    for abbr in category.abbreviations:
        add_phrase(abbr)

    match_phrases = sorted(
        ((phrase, weight, source) for phrase, (weight, source) in phrases.items()),
        key=lambda item: (-len(item[0]), item[0]),
    )
    query_terms = list(
        dict.fromkeys(
            [*context.query_terms, *[term.lower() for term in category.search_terms]],
        ),
    )
    return QueryContext(
        query=category.retrieval_query,
        technology_name=category.display_name,
        query_terms=query_terms,
        match_phrases=match_phrases,
    )


def build_discovery_query_context() -> QueryContext:
    context = build_query_context(query=DISCOVERY_RETRIEVAL_QUERY, technology_name="")
    extra = (
        "supplementary cementitious",
        "scm",
        "pozzolan",
        "pozzolanic",
        "cement replacement",
        "clinker substitution",
        "clinker replacement",
        "latent hydraulic",
        "binder replacement",
    )
    phrases: dict[str, tuple[float, str]] = {
        phrase: (weight, source) for phrase, weight, source in context.match_phrases
    }
    for term in extra:
        phrases[term] = (_phrase_weight(term), "synonym")
    match_phrases = sorted(
        ((phrase, weight, source) for phrase, (weight, source) in phrases.items()),
        key=lambda item: (-len(item[0]), item[0]),
    )
    return QueryContext(
        query=DISCOVERY_RETRIEVAL_QUERY,
        technology_name="SCM discovery",
        query_terms=list(dict.fromkeys([*context.query_terms, *extra])),
        match_phrases=match_phrases,
    )


def _paper_ids_from_screening(screening_path: Path) -> set[str] | None:
    if not screening_path.is_file():
        logger.warning("Screening results not found: %s", screening_path)
        return None
    try:
        _, rows = load_screening_results(screening_path)
        paper_ids = {row.paper_id for row in rows if row.is_relevant and row.paper_id}
    except Exception as exc:
        # Fall back to raw JSONL for SCM-native screening shards.
        logger.warning("Strict screening load failed (%s); using raw JSONL", exc)
        paper_ids = set()
        import json

        for line in screening_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if payload.get("is_relevant") and payload.get("paper_id"):
                paper_ids.add(str(payload["paper_id"]))
    logger.info("Screening filter retained %s papers", len(paper_ids))
    return paper_ids or None


def _apply_negative_terms(
    papers: list,
    negative_terms: tuple[str, ...],
) -> list:
    if not negative_terms:
        return papers
    lowered = [term.lower() for term in negative_terms]
    kept = []
    for paper in papers:
        text = f"{paper.title}\n{paper.abstract}".lower()
        # Keep papers that match negatives only if they also have strong positive content;
        # drop when negative phrase dominates without seed terms already filtered.
        if any(term in text for term in lowered) and not any(
            seed in text
            for seed in ("cement replacement", "pozzolan", "binder", "scm", "clinker")
        ):
            continue
        kept.append(paper)
    return kept


def retrieve_seed_category_papers(
    category: ScmSeedCategory,
    *,
    start: int,
    end: int,
    top_n: int | None = None,
    screening_results: str | Path | None = None,
    input_path: str | Path | None = None,
    include_full_text: bool = True,
) -> list[RankedPaper]:
    paper_ids: set[str] | None = None
    if screening_results:
        paper_ids = _paper_ids_from_screening(Path(screening_results))

    papers = load_corpus(
        start=start,
        end=end,
        path=input_path,
        paper_ids=paper_ids,
        include_full_text=include_full_text,
    )
    query_context = build_seed_query_context(category)
    filtered = filter_relevance(papers, query_context=query_context)
    filtered = _apply_negative_terms(filtered, category.negative_terms)
    ranked = rank_sources(filtered, top_n=top_n, query_context=query_context)
    logger.info(
        "Retrieved %s ranked papers for SCM seed=%s (loaded=%s filtered=%s)",
        len(ranked),
        category.slug,
        len(papers),
        len(filtered),
    )
    return ranked


def retrieve_discovery_papers(
    *,
    start: int,
    end: int,
    top_n: int | None = None,
    screening_results: str | Path | None = None,
    input_path: str | Path | None = None,
    include_full_text: bool = True,
) -> list[RankedPaper]:
    paper_ids: set[str] | None = None
    if screening_results:
        paper_ids = _paper_ids_from_screening(Path(screening_results))

    papers = load_corpus(
        start=start,
        end=end,
        path=input_path,
        paper_ids=paper_ids,
        include_full_text=include_full_text,
    )
    query_context = build_discovery_query_context()
    filtered = filter_relevance(papers, query_context=query_context)
    ranked = rank_sources(filtered, top_n=top_n, query_context=query_context)
    logger.info(
        "Retrieved %s ranked papers for SCM discovery (loaded=%s filtered=%s)",
        len(ranked),
        len(papers),
        len(filtered),
    )
    return ranked
