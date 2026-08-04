"""Tavily client and page-content helpers for Cementitious Materials web search."""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class MissingTavilyKeyError(RuntimeError):
    pass


def get_tavily_api_key(*, require: bool = True) -> str | None:
    """Read TAVILY_API_KEY from the environment only. Never log the value."""
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key or key == "YOUR_TAVILY_TOKEN_HERE":
        if require:
            raise MissingTavilyKeyError(
                "TAVILY_API_KEY is missing or still set to the placeholder."
            )
        return None
    return key


def get_tavily_client(*, require: bool = True):
    key = get_tavily_api_key(require=require)
    if key is None:
        return None
    try:
        from tavily import TavilyClient
    except ImportError as exc:
        if require:
            raise MissingTavilyKeyError(
                "tavily package is not installed; pip install tavily-python"
            ) from exc
        logger.warning("tavily package not installed")
        return None
    return TavilyClient(api_key=key)


def tavily_search(
    client,
    query: str,
    *,
    max_results: int,
    timeout: int = 30,
    max_retries: int = 3,
    include_raw_content: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Call Tavily search with bounded exponential backoff.

    Returns (results, meta) where meta includes attempts/errors (no API key).
    """
    from pipeline.cementitious.validation_metrics import get_call_metrics

    metrics = get_call_metrics()
    metrics.record_tavily_attempt()
    meta: dict[str, Any] = {"attempts": 0, "errors": [], "ok": False}
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        meta["attempts"] = attempt + 1
        try:
            response = client.search(
                query=query,
                max_results=max_results,
                include_raw_content=include_raw_content,
            )
            results = response.get("results") if isinstance(response, dict) else []
            if not isinstance(results, list):
                results = []
            parsed: list[dict[str, Any]] = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                parsed.append(
                    {
                        "title": str(item.get("title") or ""),
                        "url": url,
                        "snippet": str(item.get("content") or item.get("snippet") or ""),
                        "raw_content": str(item.get("raw_content") or ""),
                        "tavily_score": item.get("score"),
                        "raw_source_type": str(item.get("source") or item.get("type") or ""),
                    }
                )
            meta["ok"] = True
            metrics.record_tavily_success()
            return parsed, meta
        except Exception as exc:
            last_exc = exc
            meta["errors"].append(type(exc).__name__)
            logger.warning(
                "Tavily search failed (attempt %s) for query_id-bound call: %s",
                attempt + 1,
                type(exc).__name__,
            )
            if attempt < max_retries:
                delay = (2**attempt) + random.uniform(0, 0.5)
                time.sleep(min(delay, 20))
    meta["ok"] = False
    meta["final_error"] = type(last_exc).__name__ if last_exc else "unknown"
    metrics.record_tavily_failure(reason=meta["final_error"])
    return [], meta


def guess_source_type(url: str, title: str = "", domain: str = "") -> str:
    """Classify source type via centralized deterministic rules."""
    from pipeline.cementitious.source_classification import classify_source_type

    return classify_source_type(url=url, title=title, domain=domain).source_type


def fetch_url_text(
    url: str,
    *,
    timeout: int = 30,
    page_max_chars: int = 50000,
    opener: Callable[..., Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Best-effort HTTP page retrieval using stdlib urllib (no external scraper deps).

    Returns (text, meta) where meta includes status_code, error, content_type.
    """
    meta: dict[str, Any] = {
        "ok": False,
        "status_code": None,
        "error": "",
        "content_type": "",
        "final_url": url,
    }
    if not (url or "").strip():
        meta["error"] = "empty_url"
        return "", meta
    try:
        import re
        from urllib.request import Request, urlopen

        req = Request(
            url,
            headers={
                "User-Agent": "CementitiousMaterialsBot/1.0 (+research; polite fetch)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        open_fn = opener or urlopen
        with open_fn(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            meta["status_code"] = status
            meta["final_url"] = getattr(resp, "geturl", lambda: url)()
            ctype = ""
            try:
                ctype = resp.headers.get_content_type()  # type: ignore[attr-defined]
            except Exception:
                ctype = str(resp.headers.get("Content-Type", ""))
            meta["content_type"] = ctype
            raw_bytes = resp.read(page_max_chars * 4)
        if status and int(status) >= 400:
            meta["error"] = f"http_{status}"
            return "", meta
        text = raw_bytes.decode("utf-8", errors="replace")
        # Strip scripts/styles then tags
        text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            meta["error"] = "empty_body"
            return "", meta
        meta["ok"] = True
        return text[:page_max_chars], meta
    except Exception as exc:
        meta["error"] = type(exc).__name__
        logger.warning("Page fetch failed for URL (%s): %s", type(exc).__name__, url[:120])
        return "", meta


def extract_page_text(
    *,
    tavily_raw_content: str,
    snippet: str,
    page_max_chars: int,
    url: str = "",
    timeout: int = 30,
    allow_http_fetch: bool = True,
    http_fetcher: Callable[..., tuple[str, dict[str, Any]]] | None = None,
) -> tuple[str, str]:
    """
    Prefer Tavily raw page content; else HTTP fetch; else Tavily snippet.

    Returns (text, content_source).
    """
    raw = (tavily_raw_content or "").strip()
    if raw:
        return raw[:page_max_chars], "Tavily Raw Content"
    if allow_http_fetch and url:
        fetcher = http_fetcher or fetch_url_text
        body, meta = fetcher(url, timeout=timeout, page_max_chars=page_max_chars)
        if meta.get("ok") and body:
            return body[:page_max_chars], "HTTP Page Fetch"
    snip = (snippet or "").strip()
    if snip:
        return snip[:page_max_chars], "Tavily Snippet"
    return "", "Unavailable"
