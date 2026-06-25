#!/usr/bin/env python3
"""
Run retrieval and 26-question extraction for carbon capture methodologies.

Generates paired answers/citations CSV files under outputs/carbon_capture/.

For full-corpus MIT Engaging runs, use run_carbon_capture_cluster.py instead
(see docs/engaging_carbon_capture.md). This script is for local slices and smoke tests.

Examples:
    python pipeline/run_carbon_capture.py --methodology amine_absorption --start 0 --end 5000
    python pipeline/run_carbon_capture.py --all --start 0 --end 5000 --top-n 25
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.carbon_capture_config import (
    OUTPUT_DIR_NAME,
    all_methodologies,
    get_methodology,
    list_methodology_slugs,
)
from pipeline.carbon_capture_export import write_methodology_csvs
from pipeline.carbon_capture_extraction import extract_methodology_papers_parallel
from pipeline.carbon_capture_retrieval import retrieve_methodology_papers
from pipeline.config import get_output_dir, get_top_n_sources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_carbon_capture")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retrieve and extract carbon capture methodology results to CSV.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--methodology",
        type=str,
        help=f"Methodology slug ({', '.join(list_methodology_slugs())})",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all six carbon capture methodologies",
    )
    parser.add_argument("--start", type=int, required=True, help="Corpus start index (inclusive)")
    parser.add_argument("--end", type=int, required=True, help="Corpus end index (exclusive)")
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
        type=str,
        default="",
        help=f"Output directory (default: OUTPUT_DIR/{OUTPUT_DIR_NAME})",
    )
    parser.add_argument(
        "--retrieve-only",
        action="store_true",
        help="Retrieve and rank only; skip LLM extraction and CSV export",
    )
    return parser.parse_args()


def _output_directory(raw: str) -> Path:
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else (get_output_dir() / path)
    return get_output_dir() / OUTPUT_DIR_NAME


def run_methodology(
    methodology_slug: str,
    *,
    start: int,
    end: int,
    top_n: int | None,
    screening_results: str,
    input_path: str,
    output_dir: Path,
    retrieve_only: bool,
) -> tuple[Path | None, Path | None]:
    methodology = get_methodology(methodology_slug)
    logger.info("Starting methodology=%s (%s)", methodology.slug, methodology.display_name)

    ranked = retrieve_methodology_papers(
        methodology,
        start=start,
        end=end,
        top_n=top_n,
        screening_results=screening_results or None,
        input_path=input_path or None,
        include_full_text=not retrieve_only,
    )
    if retrieve_only:
        logger.info(
            "Retrieve-only mode: ranked %s papers for %s",
            len(ranked),
            methodology.slug,
        )
        return None, None

    if not ranked:
        logger.warning("No ranked papers for methodology=%s; writing empty CSV files", methodology.slug)
        results = []
    else:
        results = extract_methodology_papers_parallel(ranked, methodology)

    answers_path, citations_path = write_methodology_csvs(results, methodology, output_dir)
    logger.info(
        "Wrote %s answers rows and citations for %s -> %s, %s",
        len(results),
        methodology.slug,
        answers_path,
        citations_path,
    )
    return answers_path, citations_path


def main() -> int:
    args = _parse_args()
    if args.start < 0 or args.end <= args.start:
        logger.error("--end must be greater than --start")
        return 1

    output_dir = _output_directory(args.out_dir)
    top_n = args.top_n or get_top_n_sources()
    slugs = list_methodology_slugs() if args.all else [args.methodology.strip().lower()]

    for slug in slugs:
        try:
            get_methodology(slug)
        except KeyError as exc:
            logger.error("%s", exc)
            return 1

    for slug in slugs:
        run_methodology(
            slug,
            start=args.start,
            end=args.end,
            top_n=top_n,
            screening_results=args.screening_results,
            input_path=args.input,
            output_dir=output_dir,
            retrieve_only=args.retrieve_only,
        )

    logger.info("Finished %s methodology run(s)", len(slugs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
