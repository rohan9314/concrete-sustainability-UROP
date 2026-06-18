#!/usr/bin/env python3
"""
Process one corpus slice through filter → rank → optional extract.

Designed for large-scale batch processing: each worker task runs one start/end
range and writes shard output. A separate merge step can combine shard JSONL
files into data/technology_database.json.

Example:
    python pipeline/run_batch.py --start 0 --end 10000 --out outputs/batch_0_10000.jsonl
    python pipeline/run_batch.py --start 0 --end 100 --extract --technology "LC3"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.config import get_extraction_concurrency, get_output_dir, get_top_n_sources
from pipeline.extract_structured_fields import (
    ExtractionOptions,
    extract_technology_records_parallel,
)
from pipeline.filter_relevance import filter_relevance, tokenize_query
from pipeline.load_corpus import load_corpus
from pipeline.merge_records import merge_records
from pipeline.rank_sources import rank_sources
from pipeline.schema import RankedPaper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_batch")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one offline corpus pipeline shard.")
    parser.add_argument("--start", type=int, required=True, help="Start index (inclusive)")
    parser.add_argument("--end", type=int, required=True, help="End index (exclusive)")
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output JSONL path (e.g. outputs/batch_0_10000.jsonl)",
    )
    parser.add_argument(
        "--technology",
        type=str,
        default="",
        help="Optional technology hint for extraction",
    )
    parser.add_argument(
        "--query",
        type=str,
        default="",
        help="Optional extra relevance query terms",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Run LLM extraction on ranked sources (costs API calls)",
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

    query_terms = tokenize_query(args.query or args.technology)
    papers = load_corpus(start=args.start, end=args.end)
    filtered = filter_relevance(papers, query_terms=query_terms)
    ranked = rank_sources(filtered, top_n=args.top_n, query_terms=query_terms)

    output_path = Path(args.out)
    if not output_path.is_absolute():
        output_path = get_output_dir() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    shard_meta = {
        "type": "shard_meta",
        "start": args.start,
        "end": args.end,
        "loaded": len(papers),
        "filtered": len(filtered),
        "ranked": len(ranked),
        "concurrency": get_extraction_concurrency(),
        "top_n": args.top_n or get_top_n_sources(),
        "extract": args.extract,
    }

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(shard_meta) + "\n")

        for paper in ranked:
            handle.write(
                json.dumps({"type": "ranked_paper", **paper.model_dump()}) + "\n",
            )

        if args.extract and ranked:
            options = ExtractionOptions(technology_hint=args.technology)
            results = extract_technology_records_parallel(ranked, options=options)
            records = [result.record for result in results if result.success and result.record]
            merged = merge_records(records)

            for result in results:
                if not result.success:
                    handle.write(
                        json.dumps(
                            {
                                "type": "extraction_failure",
                                "paper_id": result.paper_id,
                                "error": result.error,
                            },
                        )
                        + "\n",
                    )

            for record in merged:
                handle.write(
                    json.dumps({"type": "technology_record", **record.model_dump()}) + "\n",
                )

    logger.info("Wrote shard output to %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
