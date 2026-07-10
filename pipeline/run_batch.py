#!/usr/bin/env python3
"""
Process one corpus slice through filter → rank → optional extract.

Two-stage design:
  Stage 1 — CCS abstract screening (run_ccs_abstract_screening.py): title + abstract only.
  Stage 2 — Keyword rank + optional LLM extraction on screened relevant papers.

Carbon capture canonical extraction (literature + web + merge):
  When --subcategory is provided, runs the carbon capture pipeline using the same
  extraction/validation logic as run_carbon_capture.py. Use --test-mode for
  lightweight local verification before cluster jobs.

Examples:
    python pipeline/run_batch.py --start 0 --end 10000 --out outputs/batch_0_10000.jsonl
    python pipeline/run_batch.py --start 0 --end 100 --extract --technology "LC3" \\
        --screening-results outputs/ccs_abstract_screening_results.jsonl

    python pipeline/run_batch.py \\
        --subcategory "oxyfuel combustion" \\
        --test-mode \\
        --paper-limit 5 \\
        --web-limit 5 \\
        --output-dir outputs/test_run

    python pipeline/run_batch.py \\
        --subcategory "oxyfuel combustion" \\
        --test-mode \\
        --paper-limit 5 \\
        --skip-web \\
        --output-dir outputs/test_literature_only
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
    parser.add_argument("--start", type=int, default=0, help="Start index (inclusive)")
    parser.add_argument("--end", type=int, default=None, help="End index (exclusive)")
    parser.add_argument(
        "--out",
        type=str,
        default="",
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
    parser.add_argument(
        "--input",
        type=str,
        default="",
        help="Optional pickle corpus path (default: PICKLE_PATH from env)",
    )

    # Carbon capture pipeline options (shared with run_carbon_capture.py)
    parser.add_argument(
        "--subcategory",
        type=str,
        default="",
        help='Run carbon capture pipeline for one subcategory (e.g. "oxyfuel combustion")',
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Lightweight local test run with small limits and validation report",
    )
    parser.add_argument(
        "--paper-limit",
        type=int,
        default=None,
        help="Max papers to extract per subcategory (default: 5 in test mode)",
    )
    parser.add_argument(
        "--web-limit",
        type=int,
        default=None,
        help="Max web sources to extract per subcategory (default: 5 in test mode)",
    )
    parser.add_argument(
        "--skip-web",
        action="store_true",
        help="Skip web search and extraction (carbon capture mode)",
    )
    parser.add_argument(
        "--skip-literature",
        action="store_true",
        help="Skip literature retrieval and extraction (carbon capture mode)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="",
        help="Output directory for carbon capture mode (default: outputs/test_run in test mode)",
    )
    parser.add_argument(
        "--stage",
        choices=("all", "literature", "web", "merge"),
        default="all",
        help="Carbon capture pipeline stage (default: all)",
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


def _run_carbon_capture_mode(args: argparse.Namespace) -> int:
    from pipeline.carbon_capture_runner import (
        CarbonCaptureRunConfig,
        resolve_output_dir,
        run_carbon_capture_pipeline,
        slugs_from_args,
    )

    try:
        slugs = slugs_from_args(subcategory=args.subcategory)
    except KeyError as exc:
        logger.error("%s", exc)
        return 1

    end = args.end if args.end is not None else 5000
    if not args.skip_literature and end <= args.start:
        logger.error("--end must be greater than --start for literature retrieval")
        return 1

    config = CarbonCaptureRunConfig(
        slugs=slugs,
        stage=args.stage,
        start=args.start,
        end=end,
        top_n=args.top_n,
        paper_limit=args.paper_limit,
        web_limit=args.web_limit,
        screening_results=args.screening_results,
        input_path=args.input,
        output_dir=resolve_output_dir(raw=args.output_dir, test_mode=args.test_mode),
        test_mode=args.test_mode,
        skip_web=args.skip_web,
        skip_literature=args.skip_literature,
        web_max_results_per_query=5,
    )
    run_carbon_capture_pipeline(config)
    return 0


def main() -> int:
    args = _parse_args()

    if args.subcategory:
        return _run_carbon_capture_mode(args)

    if args.end is None:
        logger.error("--end is required for standard batch shard mode")
        return 1
    if not args.out:
        logger.error("--out is required for standard batch shard mode")
        return 1
    if args.start < 0 or args.end <= args.start:
        logger.error("--end must be greater than --start")
        return 1

    logger.info("Running standard batch shard in FULL MODE")
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
        input_path=args.input or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
