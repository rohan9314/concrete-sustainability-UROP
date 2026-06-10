"""Tavily web search for cement decarbonization technology research."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from tavily import TavilyClient

from scraper import scrape_url

load_dotenv()

# Paste your Tavily API key in the .env file as TAVILY_API_KEY=your_key_here
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

SEARCH_SUFFIX_TERMS = [
    "cement decarbonization",
    "lifecycle emissions",
    "CAPEX",
    "OPEX",
    "energy requirement",
    "cost per ton CO2",
    "commercial deployment",
]

# Source types we prioritize in ranking
PRIORITY_DOMAINS = {
    "gov": 5,
    "edu": 5,
    "doi.org": 5,
    "sciencedirect.com": 4,
    "springer.com": 4,
    "nature.com": 4,
    "wiley.com": 4,
    "iea.org": 4,
    "energy.gov": 5,
    "nrel.gov": 5,
    "epa.gov": 5,
    "cement.org": 3,
    "gccassociation.com": 3,
}


class MissingAPIKeyError(Exception):
    """Raised when a required API key is not configured."""


class NoSearchResultsError(Exception):
    """Raised when Tavily returns no usable search results."""


@dataclass
class SearchResult:
    """A single search result with optional full content."""

    title: str
    url: str
    snippet: str
    content: str = ""
    source_type: str = "other"


def validate_api_key() -> str:
    """Ensure Tavily API key is present and not a placeholder."""
    if not TAVILY_API_KEY or TAVILY_API_KEY == "YOUR_TAVILY_TOKEN_HERE":
        raise MissingAPIKeyError(
            "TAVILY_API_KEY is missing or still set to the placeholder. "
            "Paste your Tavily API key in research_agent/.env as "
            "TAVILY_API_KEY=your_key_here"
        )
    return TAVILY_API_KEY


def _build_query(technology_name: str) -> str:
    """Combine technology name with decarbonization search terms."""
    terms = " OR ".join(f'"{term}"' for term in SEARCH_SUFFIX_TERMS[:4])
    return f'"{technology_name}" cement concrete decarbonization ({terms})'


def _score_result(url: str, title: str) -> int:
    """Rank results — higher score means higher priority."""
    score = 0
    url_lower = url.lower()
    title_lower = title.lower()

    for domain, weight in PRIORITY_DOMAINS.items():
        if domain in url_lower:
            score += weight

    priority_keywords = [
        "peer-reviewed",
        "epd",
        "environmental product declaration",
        "technical report",
        "white paper",
        "deployment",
        "commercial",
        "lifecycle",
        "lca",
        "trl",
        "carbon capture",
        "cement",
        "concrete",
    ]
    for keyword in priority_keywords:
        if keyword in title_lower or keyword in url_lower:
            score += 1

    return score


def _infer_source_type(url: str, title: str) -> str:
    """Heuristically classify a source type from URL and title."""
    combined = f"{url} {title}".lower()

    if "doi.org" in combined or "journal" in combined or "peer" in combined:
        return "peer-reviewed paper"
    if "epd" in combined or "environmental product declaration" in combined:
        return "EPD"
    if any(d in combined for d in (".gov", "doe", "energy.gov", "epa.gov")):
        return "government report"
    if "white paper" in combined or "whitepaper" in combined:
        return "white paper"
    if "deploy" in combined or "commercial" in combined or "announcement" in combined:
        return "commercial announcement"
    if "report" in combined or "technical" in combined:
        return "technical report"
    return "other"


def _extract_content(item: dict) -> str:
    """Get the best available text content from a Tavily result."""
    content = item.get("content") or item.get("raw_content") or ""
    if content and len(content.strip()) > 100:
        return content.strip()

    url = item.get("url", "")
    if url:
        scraped = scrape_url(url)
        if scraped:
            return scraped

    return item.get("snippet", "") or ""


def search_technology(
    technology_name: str,
    max_results: int = 8,
    *,
    query: str | None = None,
) -> list[SearchResult]:
    """
    Search Tavily for high-quality sources about a decarbonization technology.

    Returns a ranked list of SearchResult objects with title, URL, snippet, and content.
    """
    api_key = validate_api_key()
    client = TavilyClient(api_key=api_key)

    query = query or _build_query(technology_name)

    try:
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_raw_content=True,
        )
    except Exception as exc:
        raise NoSearchResultsError(f"Tavily search failed: {exc}") from exc

    raw_results = response.get("results", [])
    if not raw_results:
        raise NoSearchResultsError(
            f"No Tavily results found for technology: {technology_name}"
        )

    ranked = sorted(
        raw_results,
        key=lambda r: _score_result(r.get("url", ""), r.get("title", "")),
        reverse=True,
    )

    results: list[SearchResult] = []
    for item in ranked:
        url = item.get("url", "")
        title = item.get("title", "")
        snippet = item.get("content", "") or item.get("snippet", "")
        content = _extract_content(item)

        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=snippet[:500] if snippet else "",
                content=content,
                source_type=_infer_source_type(url, title),
            )
        )

    return results


def _search_result_to_source(result: SearchResult) -> dict:
    """Convert a Tavily search result to the standardized source format."""
    return {
        "title": result.title,
        "url": result.url,
        "source_type": "internet",
        "snippet": result.snippet,
        "full_text": result.content,
        "metadata": {
            "authors": [],
            "year": "",
            "journal": "",
            "doi": "",
        },
    }


def retrieve_internet_sources(technology_name: str, max_results: int = 8) -> list[dict]:
    """
    Run the Tavily internet search workflow and return standardized source dicts.

    This wraps search_technology without changing its behavior.
    """
    return retrieve_internet_sources_multi(
        [_build_query(technology_name)],
        max_per_query=max_results,
        max_total=max_results,
        technology_name=technology_name,
    )


def retrieve_internet_sources_multi(
    queries: list[str],
    *,
    max_per_query: int = 6,
    max_total: int = 20,
    technology_name: str = "",
) -> list[dict]:
    """Run multiple Tavily searches, deduplicate by URL, and return ranked sources."""
    best_results: dict[str, SearchResult] = {}

    for query in queries:
        query = query.strip()
        if not query:
            continue

        try:
            results = search_technology(
                technology_name or query,
                max_results=max_per_query,
                query=query,
            )
        except NoSearchResultsError:
            continue

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


def _format_single_source_for_llm(source: dict, index: int, *, origin: str) -> str:
    metadata = source.get("metadata") or {}
    body = source.get("full_text") or source.get("snippet") or "No content available."
    source_type = source.get("source_type") or "unknown"
    meta_lines: list[str] = []

    authors = metadata.get("authors") or []
    if authors:
        meta_lines.append(f"Authors: {', '.join(authors)}")
    if metadata.get("year"):
        meta_lines.append(f"Year: {metadata['year']}")
    if metadata.get("journal"):
        meta_lines.append(f"Journal: {metadata['journal']}")
    if metadata.get("doi"):
        meta_lines.append(f"DOI: {metadata['doi']}")

    metadata_block = "\n".join(meta_lines)
    if metadata_block:
        metadata_block = f"{metadata_block}\n"

    return (
        f"--- {origin.upper()} SOURCE {index} ---\n"
        f"Title: {source.get('title', '')}\n"
        f"URL: {source.get('url', '')}\n"
        f"Source Type: {source_type}\n"
        f"Origin: {origin}\n"
        f"{metadata_block}"
        f"Content:\n{body}\n"
    )


def format_sources_for_llm(sources: list[dict]) -> str:
    """Format standardized sources into labeled paper and internet sections for the LLM."""
    paper_sources = [
        source for source in sources if source.get("source_type") == "scientific_paper"
    ]
    internet_sources = [
        source for source in sources if source.get("source_type") == "internet"
    ]
    other_sources = [
        source
        for source in sources
        if source.get("source_type") not in {"scientific_paper", "internet"}
    ]

    sections: list[str] = []

    if paper_sources:
        sections.append("=== SCIENTIFIC PAPERS (Local Paper Database) ===")
        for index, source in enumerate(paper_sources, start=1):
            sections.append(
                _format_single_source_for_llm(
                    source,
                    index,
                    origin="Scientific paper (local database)",
                )
            )

    if internet_sources:
        sections.append("=== INTERNET SOURCES ===")
        for index, source in enumerate(internet_sources, start=1):
            sections.append(
                _format_single_source_for_llm(source, index, origin="Internet")
            )

    if other_sources:
        sections.append("=== OTHER SOURCES ===")
        for index, source in enumerate(other_sources, start=1):
            sections.append(_format_single_source_for_llm(source, index, origin="Other"))

    if not sections:
        return "No sources available."

    return "\n".join(sections)
