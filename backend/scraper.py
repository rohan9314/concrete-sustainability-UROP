"""Fallback webpage scraper using requests and BeautifulSoup."""

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ResearchAgent/1.0; "
        "+https://github.com/research-agent)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Tags to remove entirely from scraped pages
REMOVE_TAGS = [
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "noscript",
    "iframe",
    "svg",
    "form",
    "button",
    "input",
    "select",
    "textarea",
]

# Common navbar / menu class/id patterns
NAV_PATTERNS = re.compile(
    r"(nav|navbar|navigation|menu|sidebar|breadcrumb|cookie|banner|advert|ads|footer|header)",
    re.IGNORECASE,
)


def _is_valid_url(url: str) -> bool:
    """Return True if the URL has a usable http/https scheme."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _remove_noise_elements(soup: BeautifulSoup) -> None:
    """Remove scripts, styles, navbars, and other non-content elements."""
    for tag_name in REMOVE_TAGS:
        for element in soup.find_all(tag_name):
            element.decompose()

    for element in soup.find_all(True):
        attrs = " ".join(
            filter(
                None,
                [
                    element.get("id", ""),
                    " ".join(element.get("class", [])),
                    element.get("role", ""),
                ],
            )
        )
        if NAV_PATTERNS.search(attrs):
            element.decompose()


def _clean_text(text: str) -> str:
    """Normalize whitespace and strip excessive blank lines."""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def scrape_url(url: str, timeout: int = 15, max_chars: int = 12000) -> str:
    """
    Fetch and extract readable text from a webpage.

    Returns cleaned text, or an empty string if the fetch fails.
    """
    if not _is_valid_url(url):
        return ""

    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return ""

    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type and "text" not in content_type:
        return ""

    try:
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception:
        return ""

    _remove_noise_elements(soup)

    # Prefer main content landmarks when present
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", role="main")
        or soup.body
    )
    if main is None:
        return ""

    text = main.get_text(separator="\n")
    text = _clean_text(text)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[Content truncated]"

    return text
