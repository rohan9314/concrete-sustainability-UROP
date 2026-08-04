#!/usr/bin/env python3
"""
Cementitious Materials pipeline CLI.

Examples:
  python -m pipeline.run_cementitious_materials plan
  python -m pipeline.run_cementitious_materials run --mode literature-and-web --sample-size 100 --seed 42
  python -m pipeline.run_cementitious_materials run --subcategory cement_plant_carbon_capture
  python -m pipeline.run_cementitious_materials run --sub-subcategory chemical_absorption
  python -m pipeline.run_cementitious_materials export --input merged.csv --output "${RESULTS_ROOT}/7-30 results"
  python -m pipeline.run_cementitious_materials migrate-carbon-capture --input <ccs-results> --output <out>
"""

from __future__ import annotations

import argparse
import json
import logging
import os
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
from pipeline.cementitious.migrate_carbon_capture import migrate_carbon_capture
from pipeline.cementitious.paths import get_730_results_dir, get_results_root, resolve_output_dir
from pipeline.cementitious.runner import RunConfig, build_plan, run_pipeline
from pipeline.cementitious.taxonomy import get_taxonomy, load_taxonomy, resolve_taxonomy_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline.run_cementitious_materials")


def _split_csv_arg(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        default=os.getenv("RUN_MODE", "literature-and-web"),
        choices=[
            "literature-and-web",
            "literature-only",
            "web-only",
            "literature_and_web",
            "literature_only",
            "web_only",
        ],
    )
    parser.add_argument("--sample-size", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--web-limit", type=int, default=None)
    parser.add_argument("--web-queries-per-subcategory", type=int, default=None)
    parser.add_argument("--web-queries-per-sub-subcategory", type=int, default=None)
    parser.add_argument("--web-results-per-query", type=int, default=None)
    parser.add_argument("--web-max-total-urls", type=int, default=None)
    parser.add_argument("--web-max-urls-per-branch", type=int, default=None)
    parser.add_argument("--web-search-shard-size", type=int, default=None)
    parser.add_argument("--web-extract-shard-size", type=int, default=None)
    parser.add_argument("--subcategory", default=None)
    parser.add_argument("--subcategories", default=None, help="Comma-separated slugs or display names")
    parser.add_argument("--sub-subcategory", default=None)
    parser.add_argument(
        "--sub-subcategories",
        default=None,
        help="Comma-separated slugs or display names",
    )
    parser.add_argument("--output", "--out-dir", dest="output", default=None)
    parser.add_argument("--input", default=None, help="Corpus pickle path override")
    parser.add_argument("--taxonomy-path", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keyword-only", action="store_true", help="Skip LLM for local smoke tests")
    parser.add_argument("--open-discovery", action="store_true")
    parser.add_argument("--literature-only", action="store_true")
    parser.add_argument("--web-only", action="store_true")
    parser.add_argument("--migrate-ccs-input", default=None)
    parser.add_argument("--qc", action="store_true")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument(
        "--allow-missing-citations",
        action="store_true",
        help="Non-production: allow export when accepted rows lack citations",
    )


def _config_from_args(args: argparse.Namespace, *, planning: bool = False) -> RunConfig:
    mode = args.mode
    if getattr(args, "literature_only", False):
        mode = "literature-only"
    if getattr(args, "web_only", False):
        mode = "web-only"
    # Propagate web limit CLI overrides into the environment before stages load limits
    for cli_name, env_name in (
        ("web_queries_per_subcategory", "WEB_QUERIES_PER_SUBCATEGORY"),
        ("web_queries_per_sub_subcategory", "WEB_QUERIES_PER_SUB_SUBCATEGORY"),
        ("web_results_per_query", "WEB_RESULTS_PER_QUERY"),
        ("web_max_total_urls", "WEB_MAX_TOTAL_URLS"),
        ("web_max_urls_per_branch", "WEB_MAX_URLS_PER_BRANCH"),
        ("web_search_shard_size", "WEB_SEARCH_SHARD_SIZE"),
        ("web_extract_shard_size", "WEB_EXTRACT_SHARD_SIZE"),
        ("web_limit", "WEB_LIMIT"),
    ):
        value = getattr(args, cli_name, None)
        if value is not None:
            os.environ[env_name] = str(value)
            if cli_name == "web_limit":
                os.environ.setdefault("WEB_MAX_TOTAL_URLS", str(value))
    # Env-selected lists if CLI not provided
    subcategories = _split_csv_arg(args.subcategories) or _split_csv_arg(
        os.getenv("SELECTED_SUBCATEGORIES")
    )
    sub_subcategories = _split_csv_arg(args.sub_subcategories) or _split_csv_arg(
        os.getenv("SELECTED_SUB_SUBCATEGORIES")
    )
    return RunConfig(
        mode=mode,
        sample_size=args.sample_size,
        seed=args.seed,
        start=args.start,
        end=args.end,
        top_n=args.top_n,
        web_limit=args.web_limit,
        subcategory=args.subcategory,
        subcategories=subcategories,
        sub_subcategory=args.sub_subcategory,
        sub_subcategories=sub_subcategories,
        output_dir=args.output,
        input_path=args.input,
        taxonomy_path=args.taxonomy_path or os.getenv("TAXONOMY_PATH") or None,
        dry_run=bool(args.dry_run),
        planning=planning,
        resume=bool(args.resume),
        force=bool(args.force),
        keyword_only=bool(args.keyword_only),
        open_discovery=bool(args.open_discovery),
        migrate_ccs_input=args.migrate_ccs_input,
        run_qc=bool(args.qc),
        model=args.model,
        concurrency=args.concurrency,
        allow_missing_citations=bool(getattr(args, "allow_missing_citations", False)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run_cementitious_materials",
        description="Unified Cementitious Materials retrieval and extraction workflow",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan", help="Print and write a machine-readable job plan")
    _add_common_run_args(plan_p)

    run_p = sub.add_parser("run", help="Run screening + extraction + export")
    _add_common_run_args(run_p)

    export_p = sub.add_parser("export", help="Export taxonomy partitions from merged records")
    export_p.add_argument("--input", required=True)
    export_p.add_argument("--output", required=True)
    export_p.add_argument("--subcategory", default=None)
    export_p.add_argument("--sub-subcategory", default=None)
    export_p.add_argument("--taxonomy-path", default=None)
    export_p.add_argument("--force", action="store_true")
    export_p.add_argument("--allow-missing-citations", action="store_true")

    mig_p = sub.add_parser(
        "migrate-carbon-capture",
        help="Normalize existing carbon-capture results into the new taxonomy",
    )
    mig_p.add_argument("--input", required=True)
    mig_p.add_argument("--output", required=True)
    mig_p.add_argument("--methodology-slug", default="")

    list_p = sub.add_parser("list-taxonomy", help="List taxonomy nodes")
    list_p.add_argument("--taxonomy-path", default=None)

    validate_p = sub.add_parser("validate-taxonomy", help="Validate taxonomy config")
    validate_p.add_argument("--taxonomy-path", default=None)

    args = parser.parse_args(argv)

    if args.command == "list-taxonomy":
        tax = load_taxonomy(args.taxonomy_path) if args.taxonomy_path else get_taxonomy()
        print_taxonomy_listing(tax)
        return 0

    if args.command == "validate-taxonomy":
        path = resolve_taxonomy_path(args.taxonomy_path)
        tax = load_taxonomy(path)
        print(f"OK: {path}")
        print(f"version={tax.taxonomy_version}")
        print(f"subcategories={len(tax.subcategories)}")
        print(f"sub_subcategories={len(tax.sub_subcategories)}")
        return 0

    if args.command == "plan":
        config = _config_from_args(args, planning=True)
        taxonomy = (
            load_taxonomy(config.taxonomy_path) if config.taxonomy_path else get_taxonomy()
        )
        plan = build_plan(config, taxonomy)
        out = resolve_output_dir(config.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        meta = out / "metadata"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "job_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(json.dumps(plan, indent=2))
        print(f"RESULTS_ROOT={get_results_root()}")
        print(f"output_dir={out}")
        return 0

    if args.command == "run":
        config = _config_from_args(args)
        result = run_pipeline(config)
        print(json.dumps({k: v for k, v in result.items() if k != "plan"}, indent=2, default=str))
        return 0

    if args.command == "export":
        taxonomy = (
            load_taxonomy(args.taxonomy_path) if args.taxonomy_path else get_taxonomy()
        )
        summary = export_taxonomy_partitions(
            input_path=args.input,
            output_dir=args.output,
            taxonomy=taxonomy,
            subcategory=args.subcategory,
            sub_subcategory=args.sub_subcategory,
            force=args.force,
            allow_missing_citations=bool(args.allow_missing_citations),
        )
        print(json.dumps(summary, indent=2, default=str))
        return 0

    if args.command == "migrate-carbon-capture":
        report = migrate_carbon_capture(
            input_path=args.input,
            output_dir=args.output,
            methodology_slug=args.methodology_slug,
        )
        print(json.dumps(report, indent=2))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
