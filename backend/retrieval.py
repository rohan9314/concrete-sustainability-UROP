"""Multi-query source retrieval across the paper database and internet."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from concurrency import get_extraction_concurrency, run_parallel_ordered
from paper_records import (
    PaperDatabaseConfigError,
    PaperDatabaseLoadError,
    PaperDatabaseNotFoundError,
    _record_dedupe_key,
    _score_record,
    _tokenize,
    load_paper_records,
    record_to_source,
    search_paper_records,
)
from search import (
    MissingAPIKeyError as TavilyMissingKeyError,
    NoSearchResultsError,
    _score_result,
    _search_result_to_source,
    search_technology,
    validate_api_key as validate_tavily_key,
)

ProgressCallback = Callable[[str, str], None]

logger = logging.getLogger(__name__)

PAPER_MAX_TOTAL = 30
PAPER_MAX_PER_QUERY = 15
INTERNET_MAX_TOTAL = 20
INTERNET_MAX_PER_QUERY = 6
LLM_QUESTION_BATCH_SIZE = 13


def build_search_queries(
    technology_name: str,
    *,
    company_name: str = "",
    ccs_subcategory: str = "",
    project_stage: str = "Not Reported",
) -> list[str]:
    """Return focused queries to surface technical, economic, and deployment evidence."""
    tech = technology_name.strip()
    queries = [
        f"{tech} cement concrete carbon capture",
        f"{tech} CO2 capture cement plant technology",
        f"{tech} CAPEX OPEX cost cement carbon capture",
        f"{tech} energy requirement heat electricity cement capture",
        f"{tech} lifecycle emissions greenhouse gas cement",
        f"{tech} commercial deployment pilot demonstration cement",
        f"{tech} adoption barriers infrastructure cement plant",
        f"{tech} company developer cement carbon capture pilot project",
        f"{tech} demonstration plant cement CO2 capture capacity",
    ]

    if ccs_subcategory and ccs_subcategory != "Not Reported":
        queries.append(f"{tech} {ccs_subcategory} cement carbon capture")

    if company_name.strip():
        company = company_name.strip()
        queries.extend(
            [
                f"{tech} {company} cement carbon capture pilot",
                f"{company} cement decarbonization project demonstration",
            ]
        )

    if project_stage in {"Pilot", "Demonstration"}:
        queries.append(f"{tech} {project_stage.lower()} project cement CO2 capture")

    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.lower()
        if key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def _paper_query_search(
    args: tuple[str, list[dict], int],
) -> tuple[str, float, dict]:
    """Worker: score one query against the in-memory corpus."""
    query, records, max_per_query = args
    tokens = _tokenize(query)
    matches = search_paper_records(query, records, top_k=max_per_query)
    best: tuple[str, float, dict] | None = None
    for record in matches:
        dedupe_key = _record_dedupe_key(record)
        if not dedupe_key:
            continue
        score = _score_record(record, tokens)
        if best is None or score > best[1]:
            best = (dedupe_key, score, record)
    if best is None:
        raise ValueError(f"No paper matches for query: {query}")
    return best


def retrieve_paper_sources_multi(
    queries: list[str],
    *,
    max_per_query: int = 15,
    max_total: int = 30,
    records: list[dict] | None = None,
) -> list[dict]:
    """
    Search the full paper database with multiple queries in bounded parallel.

    Batch workers can reuse this function against a preloaded records slice.
    """
    records = records if records is not None else load_paper_records()
    cleaned_queries = [query.strip() for query in queries if query.strip()]
    if not cleaned_queries:
        return []

    worker_args = [(query, records, max_per_query) for query in cleaned_queries]
    parallel = run_parallel_ordered(
        worker_args,
        _paper_query_search,
        concurrency=get_extraction_concurrency(),
        label="paper_query_search",
    )

    best_matches: dict[str, tuple[float, dict]] = {}
    for item in parallel:
        if not item.success or item.value is None:
            continue
        dedupe_key, score, record = item.value
        existing = best_matches.get(dedupe_key)
        if existing is None or score > existing[0]:
            best_matches[dedupe_key] = (score, record)

    ranked = sorted(best_matches.values(), key=lambda entry: entry[0], reverse=True)
    sources: list[dict] = []
    for score, record in ranked[:max_total]:
        source = record_to_source(record, score=score)
        source.pop("_local_score", None)
        source.pop("_keywords", None)
        sources.append(source)

    return sources


def _internet_query_search(args: tuple[str, str, int]) -> tuple[str, object]:
    """Worker: run one Tavily query."""
    technology_name, query, max_per_query = args
    results = search_technology(
        technology_name or query,
        max_results=max_per_query,
        query=query,
    )
    if not results:
        raise NoSearchResultsError(f"No internet results for query: {query}")
    return query, results


def retrieve_internet_sources_multi(
    queries: list[str],
    *,
    max_per_query: int = 6,
    max_total: int = 20,
    technology_name: str = "",
) -> list[dict]:
    """Run multiple Tavily searches in bounded parallel and deduplicate by URL."""
    cleaned_queries = [query.strip() for query in queries if query.strip()]
    if not cleaned_queries:
        return []

    worker_args = [
        (technology_name, query, max_per_query) for query in cleaned_queries
    ]
    parallel = run_parallel_ordered(
        worker_args,
        _internet_query_search,
        concurrency=get_extraction_concurrency(),
        label="internet_query_search",
    )

    best_results: dict[str, object] = {}
    for item in parallel:
        if not item.success or item.value is None:
            continue
        _, results = item.value
        for result in results:
            url_key = result.url.strip().lower()
            if not url_key or url_key in best_results:
                continue
            best_results[url_key] = result

    ranked = sorted(
        best_results.values(),
        key=lambda result: _score_result(result.url, result.title),
        reverse=True,
    )
    return [_search_result_to_source(result) for result in ranked[:max_total]]


def _retrieve_papers_safe(
    queries: list[str],
    *,
    records: list[dict] | None = None,
) -> list[dict]:
    return retrieve_paper_sources_multi(
        queries,
        max_per_query=PAPER_MAX_PER_QUERY,
        max_total=PAPER_MAX_TOTAL,
        records=records,
    )


def _retrieve_internet_safe(
    queries: list[str],
    *,
    technology_name: str,
) -> list[dict]:
    validate_tavily_key()
    return retrieve_internet_sources_multi(
        queries,
        max_per_query=INTERNET_MAX_PER_QUERY,
        max_total=INTERNET_MAX_TOTAL,
        technology_name=technology_name,
    )


def retrieve_all_sources(
    technology_name: str,
    *,
    company_name: str = "",
    ccs_subcategory: str = "",
    project_stage: str = "Not Reported",
    progress_callback: ProgressCallback | None = None,
    records: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Run paper and internet retrieval concurrently with bounded worker pools.

    The live website uses this for small interactive runs. Large-scale corpus
    processing should use scripts/process_batch.py instead of scaling this path.
    """
    queries = build_search_queries(
        technology_name,
        company_name=company_name,
        ccs_subcategory=ccs_subcategory,
        project_stage=project_stage,
    )

    if progress_callback:
        progress_callback(
            "searching_local_papers",
            f"Searching paper database with {len(queries)} parallel queries...",
        )

    paper_sources: list[dict] = []
    internet_sources: list[dict] = []
    paper_error: Exception | None = None
    internet_error: Exception | None = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        paper_future = executor.submit(_retrieve_papers_safe, queries, records=records)
        internet_future = executor.submit(
            _retrieve_internet_safe,
            queries,
            technology_name=technology_name,
        )

        try:
            paper_sources = paper_future.result()
        except (
            PaperDatabaseConfigError,
            PaperDatabaseNotFoundError,
            PaperDatabaseLoadError,
        ):
            raise
        except Exception as exc:
            paper_error = exc
            logger.warning("Paper retrieval failed: %s", exc)

        try:
            internet_sources = internet_future.result()
        except TavilyMissingKeyError as exc:
            internet_error = exc
        except Exception as exc:
            internet_error = exc
            logger.warning("Internet retrieval failed: %s", exc)

    if progress_callback:
        progress_callback(
            "searching_local_papers",
            f"Found {len(paper_sources)} scientific papers across targeted queries.",
        )
        if isinstance(internet_error, TavilyMissingKeyError):
            progress_callback(
                "searching_internet",
                "Tavily API key not configured. Continuing with local paper sources only.",
            )
        elif internet_error is not None:
            progress_callback(
                "searching_internet",
                "Internet search failed. Continuing with local paper sources only.",
            )
        else:
            progress_callback(
                "searching_internet",
                f"Found {len(internet_sources)} internet sources across targeted queries.",
            )

    if paper_error and not paper_sources:
        raise paper_error

    return paper_sources, internet_sources
