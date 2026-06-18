#!/usr/bin/env python3
"""
Process a slice of the local paper corpus with bounded parallel extraction.

This script is not wired to the live frontend. It supports large-scale batch
processing, where each worker task can run one slice:

    python scripts/process_batch.py --start 0 --end 100 --out outputs/batch_0_100.json \\
        --technology "carbon capture"

Launch multiple independent batch jobs over index ranges rather than depending
on the live web server for large corpus processing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from concurrency import get_extraction_concurrency, run_parallel_ordered
from paper_records import load_paper_records, record_to_source
from schemas.technology_intelligence import ResearchFilters
from source_extraction import (
    SourceExtractionOptions,
    SourceExtractionResult,
    aggregate_source_extractions,
    extract_from_source,
)
from timing import PipelineTimer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("process_batch")


def _default_output_dir() -> Path:
    configured = os.getenv("OUTPUT_DIR", "").strip()
    if configured:
        return Path(configured)
    return BACKEND_ROOT / "outputs"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract structured intelligence from a pickle corpus slice."
    )
    parser.add_argument("--start", type=int, required=True, help="Start index (inclusive)")
    parser.add_argument(
        "--end",
        type=int,
        required=True,
        help="End index (exclusive)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output JSON path (e.g. outputs/batch_0_100.json)",
    )
    parser.add_argument(
        "--technology",
        type=str,
        required=True,
        help="Technology name to extract against each paper/source",
    )
    parser.add_argument(
        "--question-set",
        type=str,
        default="structured_intelligence",
        help="Question set label stored in cache keys",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable per-source extraction cache reads/writes",
    )
    return parser.parse_args()


def _worker(args: tuple[int, dict, SourceExtractionOptions]) -> SourceExtractionResult:
    index, record, options = args
    source = record_to_source(record, score=0.0)
    return extract_from_source(source, options, source_index=index)


def main() -> int:
    args = _parse_args()
    if args.start < 0 or args.end <= args.start:
        logger.error("--end must be greater than --start")
        return 1

    timer = PipelineTimer(label="process_batch")
    technology_name = args.technology.strip()
    if not technology_name:
        logger.error("--technology cannot be empty")
        return 1

    with timer.stage("pickle_load"):
        records = load_paper_records()

    slice_records = records[args.start : args.end]
    if not slice_records:
        logger.error("No records in slice [%s, %s)", args.start, args.end)
        return 1

    options = SourceExtractionOptions(
        technology_name=technology_name,
        filters=ResearchFilters(),
        question_set=args.question_set,
        use_cache=not args.no_cache,
    )

    worker_args = [
        (args.start + offset, record, options)
        for offset, record in enumerate(slice_records)
    ]

    with timer.stage("per_source_extraction"):
        parallel = run_parallel_ordered(
            worker_args,
            _worker,
            concurrency=get_extraction_concurrency(),
            label="batch_source_extraction",
        )

    results: list[SourceExtractionResult] = []
    failures: list[dict] = []
    for item in parallel:
        if item.success and item.value is not None:
            results.append(item.value)
            if not item.value.success and item.value.error:
                failures.append(
                    {
                        "index": item.index + args.start,
                        "source_id": item.value.source_id,
                        "error": item.value.error,
                    }
                )
        else:
            failures.append(
                {
                    "index": item.index + args.start,
                    "error": item.error or "Worker failed",
                }
            )

    with timer.stage("aggregation"):
        intelligence, extraction_errors = aggregate_source_extractions(
            results,
            technology_name=technology_name,
        )

    output_path = Path(args.out)
    if not output_path.is_absolute():
        output_path = _default_output_dir() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "technology": technology_name,
        "slice": {"start": args.start, "end": args.end, "count": len(slice_records)},
        "concurrency": get_extraction_concurrency(),
        "intelligence": intelligence.model_dump(),
        "failures": failures + [{"source_id": e.split(":")[0], "error": e} for e in extraction_errors],
        "processed": sum(1 for result in results if result.success),
        "failed": len(failures) + len(extraction_errors),
    }

    with timer.stage("write_output"):
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    timer.log_total()
    logger.info("Wrote batch output to %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
