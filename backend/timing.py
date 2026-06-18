"""Lightweight stage timing for the research pipeline."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PipelineTimer:
    """Collect per-stage durations for a single pipeline run."""

    label: str = "pipeline"
    stages: dict[str, float] = field(default_factory=dict)
    _start: float = field(default_factory=time.perf_counter, repr=False)

    @contextmanager
    def stage(self, name: str):
        started = time.perf_counter()
        logger.info("[%s] stage start: %s", self.label, name)
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self.stages[name] = elapsed
            logger.info("[%s] stage done: %s (%.2fs)", self.label, name, elapsed)

    def log_total(self) -> None:
        total = time.perf_counter() - self._start
        self.stages["total"] = total
        parts = ", ".join(f"{k}={v:.2f}s" for k, v in self.stages.items())
        logger.info("[%s] timing summary: %s", self.label, parts)
