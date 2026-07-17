#!/usr/bin/env python3
"""
Carbon capture extraction pipeline with separate literature and web workflows.

Architecture:
    Paper Corpus -> Paper Retrieval -> Paper Extraction -> literature_records.jsonl
    Internet -> Web Search -> Web Extraction -> web_records.jsonl
    literature_records.jsonl + web_records.jsonl -> Conservative Merge
        -> merged_records.jsonl -> final_output.csv

Examples:
    # Full local run
    python pipeline/run_carbon_capture.py --all --start 0 --end 5000 --top-n 25

    # Local test mode (safe defaults, validation report)
    python pipeline/run_carbon_capture.py --methodology oxyfuel_combustion \\
        --test-mode --paper-limit 5 --web-limit 5 --output-dir outputs/test_run

    # Stage-by-stage
    python pipeline/run_carbon_capture.py --stage literature --all --start 0 --end 5000
    python pipeline/run_carbon_capture.py --stage web --all
    python pipeline/run_carbon_capture.py --stage merge
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.carbon_capture_config import list_methodology_slugs, resolve_methodology_slug
from pipeline.carbon_capture_runner import (
    CarbonCaptureRunConfig,
    resolve_output_dir,
    run_carbon_capture_pipeline,
    slugs_from_args,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_carbon_capture")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the carbon capture literature/web extraction pipeline.",
    )
    parser.add_argument(
        "--stage",
        choices=("all", "literature", "web", "merge"),
        default="all",
        help="Pipeline stage to run (default: all)",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--methodology",
        type=str,
        help=f"Methodology slug ({', '.join(list_methodology_slugs())})",
    )
    group.add_argument(
        "--subcategory",
        type=str,
        help='Subcategory display name (e.g. "oxyfuel combustion")',
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all carbon capture methodologies",
    )
    parser.add_argument("--start", type=int, default=0, help="Corpus start index (inclusive)")
    parser.add_argument("--end", type=int, default=5000, help="Corpus end index (exclusive)")
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Number of ranked papers to extract per methodology (default: TOP_N_SOURCES)",
    )
    parser.add_argument(
        "--screening-results",
        type=str,
        default="",
        help="Optional Stage 1 screening JSONL to restrict retrieval",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="",
        help="Optional pickle corpus path (default: PICKLE_PATH from env)",
    )
    parser.add_argument(
        "--out-dir",
        "--output-dir",
        dest="out_dir",
        type=str,
        default="",
        help="Output directory (default: OUTPUT_DIR; test mode defaults to outputs/test_run)",
    )
    parser.add_argument(
        "--retrieve-only",
        action="store_true",
        help="Retrieve and rank only during literature stage",
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
        help="Skip web search and extraction",
    )
    parser.add_argument(
        "--skip-literature",
        action="store_true",
        help="Skip literature retrieval and extraction",
    )
    parser.add_argument(
        "--web-max-results-per-query",
        type=int,
        default=5,
        help="Maximum Tavily results per web search query (default: 5)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.stage in {"literature", "all"} and not args.skip_literature and args.end <= args.start:
        logger.error("--end must be greater than --start for literature retrieval")
        return 1

    try:
        slugs = slugs_from_args(
            subcategory=args.subcategory or "",
            methodology=args.methodology or "",
            run_all=args.all,
        )
    except KeyError as exc:
        logger.error("%s", exc)
        return 1

    config = CarbonCaptureRunConfig(
        slugs=slugs,
        stage=args.stage,
        start=args.start,
        end=args.end,
        top_n=args.top_n,
        paper_limit=args.paper_limit,
        web_limit=args.web_limit,
        screening_results=args.screening_results,
        input_path=args.input,
        output_dir=resolve_output_dir(raw=args.out_dir, test_mode=args.test_mode),
        test_mode=args.test_mode,
        skip_web=args.skip_web,
        skip_literature=args.skip_literature,
        retrieve_only=args.retrieve_only,
        web_max_results_per_query=args.web_max_results_per_query,
    )

    if args.subcategory:
        try:
            resolved = resolve_methodology_slug(args.subcategory)
            logger.info("Resolved subcategory %r -> %s", args.subcategory, resolved)
        except KeyError:
            pass

    run_carbon_capture_pipeline(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
