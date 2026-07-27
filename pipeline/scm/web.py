"""Web search and source discovery for the SCM pipeline."""

from __future__ import annotations

import logging
import os

from pipeline.scm.extraction import ScmEvidenceRow
from pipeline.scm.schema import NA
from pipeline.scm.seed_categories import ScmSeedCategory

logger = logging.getLogger(__name__)

TECHNOLOGY_LEVEL_QUERY_TEMPLATES: tuple[str, ...] = (
    "{name} cement replacement concrete commercial",
    "{name} SCM concrete demonstration project",
    "{name} cementitious material pilot plant",
    "{name} concrete EPD CO2 reduction",
    "{name} binder replacement production facility",
    "{name} cement replacement cost availability",
)

COMPANY_PROJECT_QUERY_TEMPLATES: tuple[str, ...] = (
    "{company} {material} cement replacement",
    "{company} {material} SCM concrete",
    "{company} {project_name} concrete",
    "{project_name} cement replacement demonstration",
)

DISCOVERY_WEB_QUERIES: tuple[str, ...] = (
    "supplementary cementitious materials commercial concrete",
    "novel SCM cement replacement demonstration project",
    "alternative pozzolan cement industry commercial",
    "industrial byproduct cement replacement concrete plant",
    "clinker substitution material commercial deployment",
)


def build_technology_level_queries(category: ScmSeedCategory) -> list[str]:
    queries = [
        template.format(name=category.display_name)
        for template in TECHNOLOGY_LEVEL_QUERY_TEMPLATES
    ]
    for term in category.search_terms[:3]:
        queries.append(f"{term} cement replacement concrete commercial")
    return queries


def build_company_project_queries(
    *,
    company: str,
    material: str,
    project_name: str = NA,
) -> list[str]:
    queries: list[str] = []
    for template in COMPANY_PROJECT_QUERY_TEMPLATES:
        if "{project_name}" in template and project_name == NA:
            continue
        if "{company}" in template and company == NA:
            continue
        queries.append(
            template.format(
                company=company,
                material=material,
                project_name=project_name,
            ),
        )
    return queries


def extract_search_seeds(rows: list[ScmEvidenceRow]) -> list[tuple[str, str, str]]:
    seeds: set[tuple[str, str, str]] = set()
    for row in rows:
        company = row.company_or_organization.strip()
        material = (
            row.canonical_material_name.strip()
            if row.canonical_material_name != NA
            else row.raw_material_name.strip()
        )
        project = row.project_name.strip()
        if company == NA and project == NA:
            continue
        seeds.add(
            (
                company if company != NA else "",
                material if material != NA else "",
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


def _get_tavily_client():
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key or api_key == "YOUR_TAVILY_TOKEN_HERE":
        logger.info("TAVILY_API_KEY not set; skipping SCM web source discovery")
        return None
    try:
        from tavily import TavilyClient
    except ImportError:
        logger.warning("tavily package not installed; skipping SCM web source discovery")
        return None
    return TavilyClient(api_key=api_key)


def discover_web_sources(
    category: ScmSeedCategory,
    *,
    seed_rows: list[ScmEvidenceRow] | None = None,
    max_results_per_query: int = 5,
    max_total_sources: int | None = None,
) -> list[dict]:
    client = _get_tavily_client()
    if client is None:
        return []

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
            source["seed_category"] = category.slug
            discovered.append(source)

    for query in build_technology_level_queries(category):
        if max_total_sources is not None and len(discovered) >= max_total_sources:
            break
        add_sources(_tavily_search(client, query, max_results=max_results_per_query))

    for company, material, project_name in extract_search_seeds(seed_rows or []):
        if max_total_sources is not None and len(discovered) >= max_total_sources:
            break
        for query in build_company_project_queries(
            company=company or NA,
            material=material or category.display_name,
            project_name=project_name or NA,
        ):
            if max_total_sources is not None and len(discovered) >= max_total_sources:
                break
            add_sources(_tavily_search(client, query, max_results=max_results_per_query))

    logger.info(
        "Discovered %s unique web sources for SCM %s",
        len(discovered),
        category.slug,
    )
    return discovered


def discover_discovery_web_sources(
    *,
    max_results_per_query: int = 5,
    max_total_sources: int | None = None,
) -> list[dict]:
    client = _get_tavily_client()
    if client is None:
        return []

    seen_urls: set[str] = set()
    discovered: list[dict] = []
    for query in DISCOVERY_WEB_QUERIES:
        if max_total_sources is not None and len(discovered) >= max_total_sources:
            break
        for source in _tavily_search(client, query, max_results=max_results_per_query):
            if max_total_sources is not None and len(discovered) >= max_total_sources:
                break
            key = _source_key(source)
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            source["pipeline_branch"] = "open_discovery"
            discovered.append(source)
    return discovered
