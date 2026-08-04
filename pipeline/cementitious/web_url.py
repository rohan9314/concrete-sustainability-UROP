"""URL normalization for Cementitious Materials web search."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "source",
    }
)


def normalize_url(url: str) -> str:
    """
    Normalize URL for deduplication:
    - lowercase scheme/host
    - drop fragments
    - drop common tracking query params
    - preserve meaningful query params
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").casefold()
    netloc = parsed.netloc.casefold()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_items = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.casefold() not in TRACKING_PARAMS
    ]
    query = urlencode(query_items, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.casefold()
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc
