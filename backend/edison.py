"""Edison API client for scientific literature retrieval."""

import os

from dotenv import load_dotenv

load_dotenv()

EDISON_API_KEY = os.getenv("EDISON_API_KEY")
EDISON_PLACEHOLDER = "YOUR_TOKEN_HERE"

# TODO: Set the real Edison API base URL once documentation is available.
EDISON_API_BASE_URL = "https://api.edison.example/v1"


def is_edison_configured() -> bool:
    """Return True when a non-placeholder Edison API key is present."""
    return bool(EDISON_API_KEY and EDISON_API_KEY != EDISON_PLACEHOLDER)


def _empty_paper_metadata() -> dict:
    return {
        "authors": [],
        "year": "",
        "journal": "",
        "doi": "",
    }


def _paper_to_source(paper: dict) -> dict:
    """Convert a raw Edison API paper record to the standardized source format."""
    authors = paper.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]

    return {
        "title": paper.get("title", ""),
        "url": paper.get("url", "") or paper.get("link", ""),
        "source_type": "scientific_paper",
        "snippet": paper.get("abstract", "") or paper.get("snippet", ""),
        "full_text": paper.get("full_text", "") or paper.get("abstract", ""),
        "metadata": {
            "authors": authors,
            "year": str(paper.get("year", "") or ""),
            "journal": paper.get("journal", "") or paper.get("venue", ""),
            "doi": paper.get("doi", ""),
        },
    }


def retrieve_edison_papers(query: str, max_results: int = 8) -> list[dict]:
    """
    Retrieve scientific papers from the Edison API for a technology query.

    Returns an empty list when the API key is missing or still a placeholder.
    Never raises due to missing Edison configuration.
    """
    if not is_edison_configured():
        return []

    # TODO: Replace this placeholder with the real Edison API request.
    # Example sketch:
    #   import requests
    #   response = requests.get(
    #       f"{EDISON_API_BASE_URL}/search",
    #       headers={"Authorization": f"Bearer {EDISON_API_KEY}"},
    #       params={"q": query, "limit": max_results},
    #       timeout=30,
    #   )
    #   response.raise_for_status()
    #   papers = response.json().get("results", [])
    #   return [_paper_to_source(paper) for paper in papers]

    _ = (query, max_results, EDISON_API_BASE_URL)
    return []
