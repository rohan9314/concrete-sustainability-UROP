"""Centralized OpenAI Chat Completions client with retries and configurable timeouts."""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import APIStatusError, APITimeoutError, OpenAI, RateLimitError

load_dotenv()
load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_TIER = "auto"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_INITIAL_RETRY_DELAY_SECONDS = 2.0
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
ALLOWED_SERVICE_TIERS = {"auto", "flex", "default", "priority"}


def get_service_tier() -> str:
    """Return configured OpenAI service tier (default: auto)."""
    tier = os.getenv("OPENAI_SERVICE_TIER", DEFAULT_SERVICE_TIER).strip().lower()
    if tier in ALLOWED_SERVICE_TIERS:
        return tier
    logger.warning("Unknown OPENAI_SERVICE_TIER=%r; using auto", tier)
    return DEFAULT_SERVICE_TIER


def get_timeout_seconds() -> float:
    """Return configured OpenAI request timeout in seconds (default: 900)."""
    raw = os.getenv("OPENAI_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        timeout = float(raw)
    except ValueError:
        logger.warning("Invalid OPENAI_TIMEOUT_SECONDS=%r; using 900", raw)
        timeout = float(DEFAULT_TIMEOUT_SECONDS)
    return max(1.0, timeout)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default).lower()).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def debug_prompt_logging_enabled() -> bool:
    """Log full prompts only when explicitly enabled."""
    return _env_bool("OPENAI_DEBUG_PROMPTS", False)


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (RateLimitError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in RETRYABLE_STATUS_CODES
    return False


def _retry_delay(attempt: int) -> float:
    base = DEFAULT_INITIAL_RETRY_DELAY_SECONDS * (2 ** max(0, attempt - 1))
    jitter = random.uniform(0.0, min(1.0, base * 0.25))
    return base + jitter


def _get_api_key() -> str:
    from llm import validate_api_key

    return validate_api_key()


def _build_client(*, timeout: float) -> OpenAI:
    return OpenAI(api_key=_get_api_key(), timeout=timeout)


def create_chat_completion(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
    service_tier: str | None = None,
    timeout: float | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    extra_create_kwargs: dict[str, Any] | None = None,
):
    """
    Create a chat completion using standard OpenAI processing by default.

    Cost control in this project is achieved primarily through abstract-only
    screening and selective extraction, not through alternate service tiers.
    """
    tier = (service_tier or get_service_tier()).strip().lower()
    timeout_seconds = timeout if timeout is not None else get_timeout_seconds()
    client = _build_client(timeout=timeout_seconds)

    request_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "service_tier": tier,
        "timeout": timeout_seconds,
    }
    if temperature is not None:
        request_kwargs["temperature"] = temperature
    if response_format is not None:
        request_kwargs["response_format"] = response_format
    if extra_create_kwargs:
        request_kwargs.update(extra_create_kwargs)

    if debug_prompt_logging_enabled():
        logger.debug(
            "OpenAI request model=%s tier=%s timeout=%.0fs messages=%s",
            model,
            tier,
            timeout_seconds,
            messages,
        )
    else:
        logger.info(
            "OpenAI request model=%s service_tier=%s timeout_seconds=%.0f",
            model,
            tier,
            timeout_seconds,
        )

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            if attempt > 1:
                logger.info(
                    "OpenAI retry attempt %s/%s model=%s service_tier=%s",
                    attempt,
                    max_attempts,
                    model,
                    tier,
                )
            return client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            last_error = exc
            if not _is_retryable_error(exc) or attempt >= max_attempts:
                break
            delay = _retry_delay(attempt)
            status = getattr(exc, "status_code", None)
            logger.warning(
                "OpenAI transient error (status=%s) on attempt %s/%s; "
                "retrying in %.1fs: %s",
                status,
                attempt,
                max_attempts,
                delay,
                exc,
            )
            time.sleep(delay)

    assert last_error is not None
    raise last_error


def call_openai_flex(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
    service_tier: str | None = None,
    timeout: float | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    extra_create_kwargs: dict[str, Any] | None = None,
) -> str:
    """Call OpenAI chat completions and return the assistant message text."""
    response = create_chat_completion(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format=response_format,
        service_tier=service_tier,
        timeout=timeout,
        max_attempts=max_attempts,
        extra_create_kwargs=extra_create_kwargs,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise ValueError("OpenAI returned an empty response.")
    return content
