#!/usr/bin/env python3
"""Run one SCM seed category literature-only against the shared 100-paper sample.

Safety constraints enforced here:
- Uses pipeline.scm only (never carbon_capture)
- skip_web=True
- run_discovery=False
- input is the 100-paper sample pickle
- output is under outputs/test/scm/run_100_seed_categories
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
load_dotenv(REPO / "backend" / ".env")

corpus = REPO / "filtered_records_rohan.pkl"
os.environ["PICKLE_PATH"] = str(corpus)
os.environ["PAPER_RECORDS_PATH"] = str(corpus)
os.environ["OUTPUT_DIR"] = str(REPO / "outputs")
os.environ.setdefault("EXTRACTION_CONCURRENCY", "2")

assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

from pipeline.scm.runner import ScmRunConfig, run_seed_category  # noqa: E402
from pipeline.scm.seed_categories import list_seed_category_ids  # noqa: E402

OUT = REPO / "outputs" / "test" / "scm" / "run_100_seed_categories"
SAMPLE = OUT / "manifests" / "paper_sample_100.pkl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--subcategory",
        required=True,
        choices=list_seed_category_ids(),
        help="Single SCM seed category to run",
    )
    args = parser.parse_args()
    slug = args.subcategory

    if not SAMPLE.is_file():
        print(f"missing sample pickle: {SAMPLE}", file=sys.stderr)
        return 2

    results_csv = OUT / "csv" / f"{slug}_results.csv"
    if results_csv.is_file() and results_csv.stat().st_size > 0:
        print(f"SKIP {slug}: existing {results_csv}", flush=True)
        return 0

    config = ScmRunConfig(
        slugs=[slug],
        stage="run-all-seed-categories",
        start=0,
        end=100,
        top_n=20,
        paper_limit=100,
        input_path=str(SAMPLE),
        output_dir=OUT,
        test_mode=True,
        skip_web=True,
        skip_literature=False,
        run_discovery=False,
    )
    print(
        f"SCM-only literature run | subcategory={slug} | web=False | "
        f"discovery=False | top_n={config.effective_top_n()} | "
        f"input={SAMPLE.name}",
        flush=True,
    )
    t0 = time.time()
    summary = run_seed_category(config, slug)
    print(
        f"DONE {slug} lit={summary.literature_records} "
        f"merged={summary.merged_records} "
        f"results={summary.results_path} "
        f"elapsed={time.time() - t0:.1f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
