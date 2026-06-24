#!/usr/bin/env python3
"""
Stage 1: Run CCS abstract screening over a corpus slice.

Screens papers using title + abstract only and writes JSONL results.

Example:
    python pipeline/run_ccs_abstract_screening.py \\
      --input data/filtered_records_rohan.pkl \\
      --out outputs/ccs_abstract_screening_results.jsonl \\
      --start 0 --end 5000
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.ccs_abstract_classifier import ClassifierOptions, classify_records_parallel
from pipeline.config import get_output_dir, resolve_data_path
from pipeline.load_corpus import load_paper_records_slice
from pipeline.screening import CCS_SUBPATHS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_ccs_abstract_screening")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 1 CCS abstract screening (title + abstract only).",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="",
        help="Path to pickle corpus (default: PICKLE_PATH from env)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="outputs/ccs_abstract_screening_results.jsonl",
        help="Output JSONL path",
    )
    parser.add_argument("--start", type=int, default=0, help="Start index (inclusive)")
    parser.add_argument(
        "--end",
        type=int,
        default=None,
        help="End index (exclusive). Omit to screen through corpus end.",
    )
    parser.add_argument(
        "--keyword-only",
        action="store_true",
        help="Use offline keyword heuristics instead of LLM (for tests)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Parallel screening workers (LLM mode only)",
    )
    return parser.parse_args()


def print_summary(results: list[dict]) -> None:
    screened = len(results)
    relevant = [row for row in results if row.get("is_relevant")]
    subpath_counts = Counter()
    for row in relevant:
        for subpath in row.get("relevant_subpaths") or []:
            subpath_counts[subpath] += 1

    confidences = [float(row.get("confidence") or 0) for row in relevant]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    print("\nScreening summary")
    print(f"  Papers screened: {screened}")
    print(f"  Marked relevant: {len(relevant)}")
    print("  Count per CCS subpath:")
    for subpath in CCS_SUBPATHS:
        print(f"    {subpath}: {subpath_counts.get(subpath, 0)}")
    print(f"  Average confidence (relevant only): {avg_confidence:.3f}")


def main() -> int:
    args = _parse_args()
    if args.start < 0:
        logger.error("--start must be >= 0")
        return 1

    input_path = resolve_data_path(args.input) if args.input else None
    records, slice_end = load_paper_records_slice(
        path=input_path,
        start=args.start,
        end=args.end,
    )
    if args.end is not None and args.end <= args.start:
        logger.error("--end must be greater than --start")
        return 1

    options = ClassifierOptions(keyword_only=args.keyword_only)
    results = classify_records_parallel(
        records,
        start_index=args.start,
        options=options,
        concurrency=args.concurrency,
    )

    output_path = Path(args.out)
    if not output_path.is_absolute():
        output_path = get_output_dir() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    meta = {
        "type": "screening_meta",
        "start": args.start,
        "end": slice_end,
        "screened": len(results),
        "keyword_only": args.keyword_only,
        "stage": "abstract_screening",
    }

    rows = [result.model_dump() for result in results]
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    logger.info("Wrote %s screening results to %s", len(rows), output_path)
    print_summary(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
