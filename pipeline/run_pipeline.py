#!/usr/bin/env python3
"""Run a small end-to-end pipeline test on a corpus slice (no frontend required)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.export_database import export_database
from pipeline.extract_structured_fields import ExtractionOptions, extract_technology_records_parallel
from pipeline.filter_relevance import filter_relevance, tokenize_query
from pipeline.load_corpus import load_corpus
from pipeline.merge_records import merge_records
from pipeline.rank_sources import rank_sources

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_pipeline")


def main() -> int:
    parser = argparse.ArgumentParser(description="Small local pipeline test.")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=500)
    parser.add_argument("--technology", type=str, default="")
    parser.add_argument("--query", type=str, default="cement decarbonization")
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--out", type=str, default="data/technology_database.json")
    args = parser.parse_args()

    query_terms = tokenize_query(args.query)
    papers = load_corpus(start=args.start, end=args.end)
    filtered = filter_relevance(papers, query_terms=query_terms)
    ranked = rank_sources(filtered, query_terms=query_terms)
    logger.info("Loaded=%s filtered=%s ranked=%s", len(papers), len(filtered), len(ranked))

    records = []
    if args.extract and ranked:
        results = extract_technology_records_parallel(
            ranked,
            options=ExtractionOptions(technology_hint=args.technology),
        )
        records = merge_records(
            [result.record for result in results if result.success and result.record],
        )

    path = export_database(records, args.out)
    logger.info("Exported %s records to %s", len(records), path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
