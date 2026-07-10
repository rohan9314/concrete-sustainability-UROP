"""Web search and source discovery for the carbon capture pipeline."""

from __future__ import annotations

import logging
import os

from pipeline.carbon_capture_config import CarbonCaptureMethodology
from pipeline.carbon_capture_extraction import CarbonCaptureRow
from pipeline.carbon_capture_schema import NA

logger = logging.getLogger(__name__)

TECHNOLOGY_LEVEL_QUERY_TEMPLATES: tuple[str, ...] = (
    "{subcategory} carbon capture cement pilot project",
    "{subcategory} carbon capture cement demonstration project",
    "{subcategory} cement plant carbon capture commercial deployment",
    "{subcategory} cement CO2 capture cost energy penalty",
    "{subcategory} cement carbon capture CAPEX OPEX",
    "{subcategory} carbon capture cement deployment stage",
    "{subcategory} cement carbon capture CO2 reduction",
)

COMPANY_PROJECT_QUERY_TEMPLATES: tuple[str, ...] = (
    "{company} {technology_type} carbon capture pilot",
    "{company} {technology_type} demonstration project",
    "{company} cement carbon capture project",
    "{company} {project_name} carbon capture",
    "{project_name} project year location carbon capture cement",
    "{project_name} CAPEX OPEX energy penalty CO2 capture",
)


def build_technology_level_queries(subcategory: str) -> list[str]:
    return [template.format(subcategory=subcategory) for template in TECHNOLOGY_LEVEL_QUERY_TEMPLATES]


def build_company_project_queries(
    *,
    company: str,
    technology_type: str,
    project_name: str = NA,
) -> list[str]:
    queries: list[str] = []
    for template in COMPANY_PROJECT_QUERY_TEMPLATES:
        if "{project_name}" in template and project_name == NA:
            continue
        if "{company}" in template and company == NA:
            continue
        if "{technology_type}" in template and technology_type == NA:
            continue
        queries.append(
            template.format(
                company=company,
                technology_type=technology_type,
                project_name=project_name,
            ),
        )
    return queries


def extract_search_seeds(
    rows: list[CarbonCaptureRow],
) -> list[tuple[str, str, str]]:
    """Return unique (company, technology_type, project_name) seeds from extracted rows."""
    seeds: set[tuple[str, str, str]] = set()
    for row in rows:
        company = row.company_or_organization.strip()
        technology = row.technology_type.strip()
        project = row.project_name.strip()
        if company == NA and project == NA:
            continue
        seeds.add(
            (
                company if company != NA else "",
                technology if technology != NA else "",
                project if project != NA else "",
            ),
        )
    return sorted(seeds)


def _source_key(source: dict) -> str:
    return str(source.get("url") or source.get("title") or "").strip().lower()


def _tavily_search(client, query: str, *, max_results: int) -> list[dict]:
    try:
        response = client.search(query=query, max_results=max_results, include_raw_content=True)
    except Exception as exc:
        logger.warning("Tavily search failed for query %r: %s", query, exc)
        return []

    results = response.get("results") if isinstance(response, dict) else []
    if not isinstance(results, list):
        return []

    sources: list[dict] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        sources.append(
            {
                "source_type": "Web",
                "title": str(item.get("title") or ""),
                "url": url,
                "snippet": str(item.get("content") or item.get("snippet") or ""),
                "full_text": str(item.get("raw_content") or item.get("content") or ""),
                "search_query": query,
            },
        )
    return sources


def discover_web_sources(
    methodology: CarbonCaptureMethodology,
    *,
    seed_rows: list[CarbonCaptureRow] | None = None,
    max_results_per_query: int = 5,
    max_total_sources: int | None = None,
) -> list[dict]:
    """
    Discover web sources for a methodology using technology-level and
    company/project-level Tavily searches.
    """
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key or api_key == "YOUR_TAVILY_TOKEN_HERE":
        logger.info(
            "TAVILY_API_KEY not set; skipping web source discovery for %s",
            methodology.slug,
        )
        return []

    try:
        from tavily import TavilyClient
    except ImportError:
        logger.warning("tavily package not installed; skipping web source discovery")
        return []

    client = TavilyClient(api_key=api_key)
    seen_urls: set[str] = set()
    discovered: list[dict] = []

    def add_sources(sources: list[dict]) -> None:
        for source in sources:
            if max_total_sources is not None and len(discovered) >= max_total_sources:
                return
            key = _source_key(source)
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            source["methodology_slug"] = methodology.slug
            discovered.append(source)

    for query in build_technology_level_queries(methodology.subcategory):
        if max_total_sources is not None and len(discovered) >= max_total_sources:
            break
        add_sources(_tavily_search(client, query, max_results=max_results_per_query))

    seeds = extract_search_seeds(seed_rows or [])
    for company, technology_type, project_name in seeds:
        if max_total_sources is not None and len(discovered) >= max_total_sources:
            break
        for query in build_company_project_queries(
            company=company or NA,
            technology_type=technology_type or methodology.display_name,
            project_name=project_name or NA,
        ):
            if max_total_sources is not None and len(discovered) >= max_total_sources:
                break
            add_sources(_tavily_search(client, query, max_results=max_results_per_query))

    if max_total_sources is not None and len(discovered) > max_total_sources:
        discovered = discovered[:max_total_sources]

    logger.info(
        "Discovered %s unique web sources for %s (%s technology queries, %s follow-up seeds%s)",
        len(discovered),
        methodology.slug,
        len(build_technology_level_queries(methodology.subcategory)),
        len(seeds),
        f", capped at {max_total_sources}" if max_total_sources is not None else "",
    )
    return discovered
