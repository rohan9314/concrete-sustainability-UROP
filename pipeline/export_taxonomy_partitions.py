#!/usr/bin/env python3
"""
Reusable taxonomy partition exporter CLI.

Examples:
  python -m pipeline.export_taxonomy_partitions --list-taxonomy
  python -m pipeline.export_taxonomy_partitions --input merged.csv --output "${RESULTS_ROOT}/7-30 results"
  python -m pipeline.export_taxonomy_partitions --input merged.csv --subcategory cement_plant_carbon_capture --output out
  python -m pipeline.export_taxonomy_partitions --input merged.csv --sub-subcategory chemical_absorption --output out
  python -m pipeline.export_taxonomy_partitions --input merged.csv --summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.export_partitions import (
    export_taxonomy_partitions,
    print_summary,
    print_taxonomy_listing,
)
from pipeline.cementitious.taxonomy import get_taxonomy, load_taxonomy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.export_taxonomy_partitions",
        description="Export Cementitious Materials taxonomy partition CSVs",
    )
    parser.add_argument("--input", default=None, help="Merged records CSV/JSON/JSONL")
    parser.add_argument("--output", default=None, help="Output directory (7-30 results layout)")
    parser.add_argument("--subcategory", default=None)
    parser.add_argument("--sub-subcategory", default=None)
    parser.add_argument("--taxonomy-path", default=None)
    parser.add_argument("--list-taxonomy", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--allow-missing-citations",
        action="store_true",
        help="Non-production: allow export when accepted rows lack citations",
    )
    args = parser.parse_args(argv)

    taxonomy = load_taxonomy(args.taxonomy_path) if args.taxonomy_path else get_taxonomy()

    if args.list_taxonomy:
        print_taxonomy_listing(taxonomy)
        return 0

    if args.summary:
        if not args.input:
            parser.error("--summary requires --input")
        print_summary(args.input, taxonomy)
        return 0

    if not args.input or not args.output:
        parser.error("--input and --output are required unless --list-taxonomy or --summary")

    summary = export_taxonomy_partitions(
        input_path=args.input,
        output_dir=args.output,
        taxonomy=taxonomy,
        subcategory=args.subcategory,
        sub_subcategory=args.sub_subcategory,
        force=args.force,
        allow_missing_citations=args.allow_missing_citations,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
