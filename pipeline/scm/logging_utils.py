"""Stage timing / resume logging helpers for SCM pipelines."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class StageLog:
    category: str
    subcategory_or_discovery: str
    stage: str
    input_count: int = 0
    output_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    retry_count: int = 0
    output_path: str = ""
    elapsed_time: float = 0.0
    extra: dict = field(default_factory=dict)

    def emit(self) -> None:
        logger.info(
            "SCM stage log | category=%s subcategory_or_discovery=%s stage=%s "
            "input=%s output=%s skipped=%s failed=%s retry=%s path=%s elapsed=%.2fs",
            self.category,
            self.subcategory_or_discovery,
            self.stage,
            self.input_count,
            self.output_count,
            self.skipped_count,
            self.failed_count,
            self.retry_count,
            self.output_path,
            self.elapsed_time,
        )


@contextmanager
def stage_timer(
    *,
    category: str,
    subcategory_or_discovery: str,
    stage: str,
) -> Iterator[StageLog]:
    log = StageLog(
        category=category,
        subcategory_or_discovery=subcategory_or_discovery,
        stage=stage,
    )
    start = time.perf_counter()
    try:
        yield log
    finally:
        log.elapsed_time = time.perf_counter() - start
        log.emit()


def checkpoint_exists(path) -> bool:
    from pathlib import Path

    return Path(path).is_file() and Path(path).stat().st_size > 0


def as_log_dict(log: StageLog) -> dict:
    return asdict(log)
