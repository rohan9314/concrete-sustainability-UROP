#!/usr/bin/env python3
"""Run the offline pipeline for all mentor-requested CCS technologies."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.query_scoring import TARGET_TECHNOLOGIES
from pipeline.run_batch import run_batch_shard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_target_technologies")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run targeted CCS technology batches over one corpus slice.",
    )
    parser.add_argument("--start", type=int, required=True, help="Start index (inclusive)")
    parser.add_argument("--end", type=int, required=True, help="End index (exclusive)")
    parser.add_argument(
        "--out-dir",
        type=str,
        default="outputs",
        help="Output directory for per-technology JSONL files",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Override TOP_N_SOURCES for ranking",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.start < 0 or args.end <= args.start:
        logger.error("--end must be greater than --start")
        return 1

    out_dir = Path(args.out_dir)
    for technology_name, slug in TARGET_TECHNOLOGIES:
        output_name = f"{slug}_{args.start}_{args.end}.jsonl"
        output_path = out_dir / output_name
        logger.info("Running technology batch: %s -> %s", technology_name, output_path)
        run_batch_shard(
            start=args.start,
            end=args.end,
            out=output_path,
            technology_name=technology_name,
            top_n=args.top_n,
        )

    logger.info("Finished %s technology batches", len(TARGET_TECHNOLOGIES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
