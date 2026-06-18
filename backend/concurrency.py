"""Bounded concurrency helpers for extraction workers.

The live website uses small bounded concurrency for interactive requests.
Parallel batch workers should run the batch script over corpus slices with the
same EXTRACTION_CONCURRENCY limit per worker process.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TypeVar

logger = logging.getLogger(__name__)

DEFAULT_EXTRACTION_CONCURRENCY = 4
MAX_EXTRACTION_CONCURRENCY = 20

T = TypeVar("T")
R = TypeVar("R")


def get_extraction_concurrency() -> int:
    """Read EXTRACTION_CONCURRENCY from the environment with a safe default."""
    raw = os.getenv("EXTRACTION_CONCURRENCY", str(DEFAULT_EXTRACTION_CONCURRENCY))
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_EXTRACTION_CONCURRENCY
    return max(1, min(value, MAX_EXTRACTION_CONCURRENCY))


@dataclass
class ParallelItemResult:
    """Result for one ordered parallel task."""

    index: int
    item: T
    success: bool
    value: R | None = None
    error: str | None = None


def run_parallel_ordered(
    items: list[T],
    worker: Callable[[T], R],
    *,
    concurrency: int | None = None,
    label: str = "parallel",
) -> list[ParallelItemResult]:
    """
    Run worker(item) with bounded concurrency while preserving input order.

    Failures are captured per item; the caller decides how to aggregate.
    """
    if not items:
        return []

    limit = concurrency or get_extraction_concurrency()
    limit = max(1, min(limit, len(items)))
    results: list[ParallelItemResult | None] = [None] * len(items)

    with ThreadPoolExecutor(max_workers=limit) as executor:
        future_map = {
            executor.submit(worker, item): index for index, item in enumerate(items)
        }
        for future in as_completed(future_map):
            index = future_map[future]
            item = items[index]
            try:
                value = future.result()
                results[index] = ParallelItemResult(
                    index=index,
                    item=item,
                    success=True,
                    value=value,
                )
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                logger.warning("[%s] item %s failed: %s", label, index, message)
                results[index] = ParallelItemResult(
                    index=index,
                    item=item,
                    success=False,
                    error=message,
                )

    return [result for result in results if result is not None]
