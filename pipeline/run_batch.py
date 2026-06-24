#!/usr/bin/env python3
"""
Process one corpus slice through filter → rank → optional extract.

Two-stage design:
  Stage 1 — CCS abstract screening (run_ccs_abstract_screening.py): title + abstract only.
  Stage 2 — Keyword rank + optional LLM extraction on screened relevant papers.

Example:
    python pipeline/run_batch.py --start 0 --end 10000 --out outputs/batch_0_10000.jsonl
    python pipeline/run_batch.py --start 0 --end 100 --extract --technology "LC3" \\
        --screening-results outputs/ccs_abstract_screening_results.jsonl
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
from pipeline.filter_relevance import filter_relevance
from pipeline.load_corpus import load_corpus
from pipeline.merge_records import merge_records
from pipeline.query_scoring import build_query_context
from pipeline.rank_sources import rank_sources
from pipeline.screening_results import relevant_paper_ids

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
        help="Optional targeted relevance query (e.g. 'chemical absorption carbon capture cement')",
    )
    parser.add_argument(
        "--technology-name",
        type=str,
        default="",
        help="Optional CCS technology name; expands built-in synonyms for filtering/ranking",
    )
    parser.add_argument(
        "--screening-results",
        type=str,
        default="",
        help="Optional Stage 1 screening JSONL; restricts processing to is_relevant papers",
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


def run_batch_shard(
    *,
    start: int,
    end: int,
    out: str | Path,
    query: str = "",
    technology_name: str = "",
    technology: str = "",
    extract: bool = False,
    top_n: int | None = None,
    screening_results: str = "",
    input_path: str | Path | None = None,
) -> Path:
    """Run one corpus slice and write JSONL output."""
    query_context = build_query_context(query=query, technology_name=technology_name)

    paper_ids: set[str] | None = None
    if screening_results:
        screening_path = Path(screening_results)
        if not screening_path.is_absolute():
            screening_path = get_output_dir() / screening_path
        paper_ids = relevant_paper_ids(screening_path)
        logger.info("Restricting to %s papers from screening results", len(paper_ids))

    papers = load_corpus(
        start=start,
        end=end,
        path=input_path,
        paper_ids=paper_ids,
        include_full_text=extract,
    )
    filtered = filter_relevance(papers, query_context=query_context)
    ranked = rank_sources(filtered, top_n=top_n, query_context=query_context)

    output_path = Path(out)
    if not output_path.is_absolute():
        output_path = get_output_dir() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    shard_meta = {
        "type": "shard_meta",
        "start": start,
        "end": end,
        "loaded": len(papers),
        "filtered": len(filtered),
        "ranked": len(ranked),
        "concurrency": get_extraction_concurrency(),
        "top_n": top_n or get_top_n_sources(),
        "extract": extract,
        "query": query_context.query,
        "technology_name": query_context.technology_name,
        "screening_results": screening_results or None,
    }

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(shard_meta) + "\n")

        for paper in ranked:
            handle.write(
                json.dumps({"type": "ranked_paper", **paper.model_dump()}) + "\n",
            )

        if extract and ranked:
            if not screening_results:
                logger.warning(
                    "Running extraction without --screening-results; "
                    "prefer Stage 1 abstract screening before extraction.",
                )
            options = ExtractionOptions(technology_hint=technology)
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
    return output_path


def main() -> int:
    args = _parse_args()
    if args.start < 0 or args.end <= args.start:
        logger.error("--end must be greater than --start")
        return 1

    run_batch_shard(
        start=args.start,
        end=args.end,
        out=args.out,
        query=args.query,
        technology_name=args.technology_name,
        technology=args.technology,
        extract=args.extract,
        top_n=args.top_n,
        screening_results=args.screening_results,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
