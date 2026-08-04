"""Live-validation and degraded-run reporting for Cementitious Materials."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

# Controlled run-validation statuses
SUCCESSFUL_LIVE_VALIDATION = "successful_live_validation"
DEGRADED_FALLBACK = "degraded_fallback"
FAILED_LIVE_VALIDATION = "failed_live_validation"
MOCKED_VALIDATION = "mocked_validation"
NOT_ATTEMPTED = "not_attempted"

ALLOWED_RUN_STATUSES = (
    SUCCESSFUL_LIVE_VALIDATION,
    DEGRADED_FALLBACK,
    FAILED_LIVE_VALIDATION,
    MOCKED_VALIDATION,
    NOT_ATTEMPTED,
)


@dataclass
class CallMetrics:
    llm_calls_attempted: int = 0
    llm_calls_succeeded: int = 0
    llm_calls_failed: int = 0
    llm_fallback_count: int = 0
    llm_fallback_reasons: list[str] = field(default_factory=list)
    tavily_calls_attempted: int = 0
    tavily_calls_succeeded: int = 0
    tavily_calls_failed: int = 0
    page_fetch_attempts: int = 0
    page_fetch_successes: int = 0
    page_fetch_failures: int = 0
    validation_mode: str = "not_attempted"  # live_llm | live_web | mocked | keyword_only | mixed
    keyword_only: bool = False
    openai_requested: bool = False
    tavily_requested: bool = False
    mocked: bool = False
    http_error_classes: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_llm_attempt(self) -> None:
        with self._lock:
            self.llm_calls_attempted += 1
            self.openai_requested = True
            if self.validation_mode == NOT_ATTEMPTED:
                self.validation_mode = "live_llm"

    def record_llm_success(self) -> None:
        with self._lock:
            self.llm_calls_succeeded += 1

    def record_llm_failure(self, *, reason: str, http_status: int | None = None) -> None:
        with self._lock:
            self.llm_calls_failed += 1
            safe = _safe_reason(reason)
            if safe and safe not in self.llm_fallback_reasons:
                self.llm_fallback_reasons.append(safe)
            if http_status is not None:
                label = f"http_{http_status}"
                if label not in self.http_error_classes:
                    self.http_error_classes.append(label)
            cls = _classify_api_error(reason)
            if cls and cls not in self.http_error_classes:
                self.http_error_classes.append(cls)

    def record_llm_fallback(self, *, reason: str) -> None:
        with self._lock:
            self.llm_fallback_count += 1
            safe = _safe_reason(reason)
            if safe and safe not in self.llm_fallback_reasons:
                self.llm_fallback_reasons.append(safe)

    def record_tavily_attempt(self) -> None:
        with self._lock:
            self.tavily_calls_attempted += 1
            self.tavily_requested = True
            if self.validation_mode in {NOT_ATTEMPTED, "live_llm"}:
                self.validation_mode = (
                    "mixed" if self.validation_mode == "live_llm" else "live_web"
                )

    def record_tavily_success(self) -> None:
        with self._lock:
            self.tavily_calls_succeeded += 1

    def record_tavily_failure(self, *, reason: str = "") -> None:
        with self._lock:
            self.tavily_calls_failed += 1
            if reason:
                safe = _safe_reason(reason)
                if safe and safe not in self.http_error_classes:
                    self.http_error_classes.append(safe)

    def record_page_fetch(self, *, success: bool) -> None:
        with self._lock:
            self.page_fetch_attempts += 1
            if success:
                self.page_fetch_successes += 1
            else:
                self.page_fetch_failures += 1

    def mark_mocked(self) -> None:
        with self._lock:
            self.mocked = True
            self.validation_mode = MOCKED_VALIDATION

    def mark_keyword_only(self) -> None:
        with self._lock:
            self.keyword_only = True
            if self.validation_mode == NOT_ATTEMPTED:
                self.validation_mode = "keyword_only"

    def to_dict(self) -> dict[str, Any]:
        data = {
            "llm_calls_attempted": self.llm_calls_attempted,
            "llm_calls_succeeded": self.llm_calls_succeeded,
            "llm_calls_failed": self.llm_calls_failed,
            "llm_fallback_count": self.llm_fallback_count,
            "llm_fallback_reasons": list(self.llm_fallback_reasons),
            "tavily_calls_attempted": self.tavily_calls_attempted,
            "tavily_calls_succeeded": self.tavily_calls_succeeded,
            "tavily_calls_failed": self.tavily_calls_failed,
            "page_fetch_attempts": self.page_fetch_attempts,
            "page_fetch_successes": self.page_fetch_successes,
            "page_fetch_failures": self.page_fetch_failures,
            "validation_mode": self.validation_mode,
            "keyword_only": self.keyword_only,
            "openai_requested": self.openai_requested,
            "tavily_requested": self.tavily_requested,
            "mocked": self.mocked,
            "http_error_classes": list(self.http_error_classes),
        }
        status = derive_run_status(self)
        data["run_status"] = status
        data["qualifies_as_live_llm_validation"] = status == SUCCESSFUL_LIVE_VALIDATION
        data["qualifies_as_live_web_validation"] = (
            self.tavily_requested
            and not self.mocked
            and self.tavily_calls_succeeded > 0
            and status in {SUCCESSFUL_LIVE_VALIDATION, DEGRADED_FALLBACK}
            and self.validation_mode in {"live_web", "mixed"}
        )
        return data


def _safe_reason(reason: str) -> str:
    """Strip anything that looks like an API key from error strings."""
    text = str(reason or "")
    # Never echo long token-like strings
    import re

    text = re.sub(r"sk-[A-Za-z0-9_\-]{10,}", "[REDACTED_KEY]", text)
    text = re.sub(r"tvly-[A-Za-z0-9_\-]{10,}", "[REDACTED_KEY]", text)
    return text[:500]


def _classify_api_error(reason: str) -> str:
    lower = str(reason or "").casefold()
    if "credit_balance_exhausted" in lower or "insufficient_quota" in lower:
        return "credit_balance_exhausted"
    if "rate_limit" in lower or "429" in lower:
        return "rate_limit"
    if "timeout" in lower:
        return "timeout"
    if "malformed" in lower or "invalid json" in lower:
        return "malformed_response"
    return ""


def derive_run_status(metrics: CallMetrics) -> str:
    if metrics.mocked:
        return MOCKED_VALIDATION
    if metrics.keyword_only and metrics.llm_calls_attempted == 0 and not metrics.openai_requested:
        return NOT_ATTEMPTED
    if metrics.llm_calls_attempted == 0 and metrics.tavily_calls_attempted == 0:
        if metrics.openai_requested or metrics.tavily_requested:
            return FAILED_LIVE_VALIDATION
        return NOT_ATTEMPTED
    if metrics.llm_calls_attempted > 0:
        if metrics.llm_calls_succeeded == 0:
            return FAILED_LIVE_VALIDATION
        if metrics.llm_fallback_count > 0 or metrics.llm_calls_failed > 0:
            # Any fallback after requesting LLM → degraded, never successful_live
            return DEGRADED_FALLBACK
        return SUCCESSFUL_LIVE_VALIDATION
    # Web-only path without LLM
    if metrics.tavily_calls_attempted > 0:
        if metrics.tavily_calls_succeeded == 0:
            return FAILED_LIVE_VALIDATION
        if metrics.tavily_calls_failed > 0 or metrics.page_fetch_failures > 0:
            return DEGRADED_FALLBACK
        return SUCCESSFUL_LIVE_VALIDATION
    return NOT_ATTEMPTED


# Process-wide metrics for a single local run (tests can reset)
_ACTIVE: CallMetrics | None = None
_ACTIVE_LOCK = threading.Lock()


def reset_call_metrics() -> CallMetrics:
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE = CallMetrics()
        return _ACTIVE


def get_call_metrics() -> CallMetrics:
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE is None:
            _ACTIVE = CallMetrics()
        return _ACTIVE
