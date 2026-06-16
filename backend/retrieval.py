"""Multi-query source retrieval across the paper database and internet."""

from __future__ import annotations

from typing import Callable

from paper_records import (
    PaperDatabaseConfigError,
    PaperDatabaseLoadError,
    PaperDatabaseNotFoundError,
    retrieve_paper_sources_multi,
)
from search import (
    MissingAPIKeyError as TavilyMissingKeyError,
    NoSearchResultsError,
    retrieve_internet_sources_multi,
    validate_api_key as validate_tavily_key,
)

ProgressCallback = Callable[[str, str], None]

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

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.lower()
        if key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def retrieve_all_sources(
    technology_name: str,
    *,
    company_name: str = "",
    ccs_subcategory: str = "",
    project_stage: str = "Not Reported",
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Run multiple targeted searches over the full paper database and internet.

    Results are deduplicated and capped before being sent to the LLM.
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
            f"Searching paper database with {len(queries)} targeted queries...",
        )

    try:
        paper_sources = retrieve_paper_sources_multi(
            queries,
            max_per_query=PAPER_MAX_PER_QUERY,
            max_total=PAPER_MAX_TOTAL,
        )
    except (
        PaperDatabaseConfigError,
        PaperDatabaseNotFoundError,
        PaperDatabaseLoadError,
    ):
        raise

    if progress_callback:
        progress_callback(
            "searching_local_papers",
            f"Found {len(paper_sources)} scientific papers across targeted queries.",
        )

    internet_sources: list[dict] = []
    if progress_callback:
        progress_callback(
            "searching_internet",
            f"Searching internet with {len(queries)} targeted queries...",
        )

    try:
        validate_tavily_key()
        internet_sources = retrieve_internet_sources_multi(
            queries,
            max_per_query=INTERNET_MAX_PER_QUERY,
            max_total=INTERNET_MAX_TOTAL,
        )
        if progress_callback:
            progress_callback(
                "searching_internet",
                f"Found {len(internet_sources)} internet sources across targeted queries.",
            )
    except TavilyMissingKeyError:
        if progress_callback:
            progress_callback(
                "searching_internet",
                "Tavily API key not configured. Continuing with local paper sources only.",
            )
    except NoSearchResultsError:
        if progress_callback:
            progress_callback(
                "searching_internet",
                "No internet sources found. Continuing with local paper sources only.",
            )

    return paper_sources, internet_sources
