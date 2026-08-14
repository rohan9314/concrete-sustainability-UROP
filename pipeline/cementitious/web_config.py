"""Web search configuration limits for Cementitious Materials."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid integer for {name}={raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}, got {value}")
    return value


def _csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    return tuple(part.strip().casefold() for part in raw.split(",") if part.strip())


def _float_env(name: str, default: float, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        value = default
    else:
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid number for {name}={raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}, got {value}")
    return value


@dataclass(frozen=True)
class WebLimits:
    queries_per_subcategory: int = 3
    queries_per_sub_subcategory: int = 5
    results_per_query: int = 10
    max_urls_per_branch: int = 50
    max_total_urls: int = 1000
    max_total_queries: int = 0
    search_shard_size: int = 10
    extract_shard_size: int = 10
    concurrency: int = 4
    request_timeout: int = 30
    max_retries: int = 3
    page_max_chars: int = 50000
    rate_limit_sleep_s: float = 0.0
    domain_allowlist: tuple[str, ...] = ()
    domain_denylist: tuple[str, ...] = ()

    @property
    def queries_per_node(self) -> int:
        """Per searchable taxonomy node (Level 3/4). Same knob as sub-subcategory."""
        return self.queries_per_sub_subcategory

    def to_dict(self) -> dict[str, object]:
        return {
            "WEB_QUERIES_PER_SUBCATEGORY": self.queries_per_subcategory,
            "WEB_QUERIES_PER_SUB_SUBCATEGORY": self.queries_per_sub_subcategory,
            "WEB_QUERIES_PER_NODE": self.queries_per_node,
            "WEB_RESULTS_PER_QUERY": self.results_per_query,
            "WEB_MAX_URLS_PER_BRANCH": self.max_urls_per_branch,
            "WEB_MAX_TOTAL_URLS": self.max_total_urls,
            "WEB_MAX_TOTAL_QUERIES": self.max_total_queries,
            "WEB_SEARCH_SHARD_SIZE": self.search_shard_size,
            "WEB_EXTRACT_SHARD_SIZE": self.extract_shard_size,
            "WEB_CONCURRENCY": self.concurrency,
            "WEB_REQUEST_TIMEOUT": self.request_timeout,
            "WEB_MAX_RETRIES": self.max_retries,
            "WEB_PAGE_MAX_CHARS": self.page_max_chars,
            "WEB_RATE_LIMIT_SLEEP_S": self.rate_limit_sleep_s,
            "WEB_DOMAIN_ALLOWLIST": list(self.domain_allowlist),
            "WEB_DOMAIN_DENYLIST": list(self.domain_denylist),
        }


def load_web_limits() -> WebLimits:
    per_leaf_default = 5
    if os.getenv("WEB_QUERIES_PER_NODE", "").strip():
        per_leaf = _int_env("WEB_QUERIES_PER_NODE", per_leaf_default, minimum=0, maximum=50)
    else:
        per_leaf = _int_env("WEB_QUERIES_PER_SUB_SUBCATEGORY", per_leaf_default, minimum=0, maximum=50)
    return WebLimits(
        queries_per_subcategory=_int_env("WEB_QUERIES_PER_SUBCATEGORY", 3, minimum=0, maximum=50),
        queries_per_sub_subcategory=per_leaf,
        results_per_query=_int_env("WEB_RESULTS_PER_QUERY", 10, minimum=1, maximum=50),
        max_urls_per_branch=_int_env("WEB_MAX_URLS_PER_BRANCH", 50, minimum=1, maximum=5000),
        max_total_urls=_int_env("WEB_MAX_TOTAL_URLS", 1000, minimum=1, maximum=50000),
        max_total_queries=_int_env("WEB_MAX_TOTAL_QUERIES", 0, minimum=0, maximum=100000),
        search_shard_size=_int_env("WEB_SEARCH_SHARD_SIZE", 10, minimum=1, maximum=500),
        extract_shard_size=_int_env("WEB_EXTRACT_SHARD_SIZE", 10, minimum=1, maximum=500),
        concurrency=_int_env("WEB_CONCURRENCY", 4, minimum=1, maximum=20),
        request_timeout=_int_env("WEB_REQUEST_TIMEOUT", 30, minimum=1, maximum=600),
        max_retries=_int_env("WEB_MAX_RETRIES", 3, minimum=0, maximum=10),
        page_max_chars=_int_env("WEB_PAGE_MAX_CHARS", 50000, minimum=1000, maximum=500000),
        rate_limit_sleep_s=_float_env("WEB_RATE_LIMIT_SLEEP_S", 0.0, minimum=0.0, maximum=60.0),
        domain_allowlist=_csv_env("WEB_DOMAIN_ALLOWLIST"),
        domain_denylist=_csv_env("WEB_DOMAIN_DENYLIST"),
    )
