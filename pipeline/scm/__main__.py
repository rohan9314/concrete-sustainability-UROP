#!/usr/bin/env python3
"""
SCM pipeline CLI.

Examples:
    python -m pipeline.scm plan
    python -m pipeline.scm run-seed-category --subcategory slag_cement --test-mode
    python -m pipeline.scm run-all-seed-categories --test-mode --paper-limit 5
    python -m pipeline.scm run-discovery --test-mode --paper-limit 50 --top-n 10 --web-limit 5
    python -m pipeline.scm generate-category-config --category "Rice Husk Ash" \\
        --output config/scm_candidates/rice_husk_ash.yaml
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cluster_shards import plan_corpus_shards
from pipeline.corpus_loader import validate_pickle_corpus
from pipeline.scm.classification import cluster_categories_with_llm, heuristic_groupings
from pipeline.scm.config import candidate_config_dir, get_promotion_thresholds, scm_output_root
from pipeline.scm.discovery import (
    aggregate_discovery_candidates,
    aggregated_for_llm_prompt,
    build_discovered_category_rows,
)
from pipeline.scm.export import (
    export_discovered_categories_csv,
    export_normalization_csv,
    read_jsonl_discovery,
)
from pipeline.scm.normalize import load_alias_overrides, normalize_discovery_records
from pipeline.scm.outputs import (
    DISCOVERED_CATEGORIES_CSV,
    DISCOVERY_RECORDS,
    NORMALIZATION_CSV,
    discovered_categories_path,
    discovery_records_path,
    normalization_path,
    screening_merged_path,
)
from pipeline.scm.postprocess import build_category_config_payload, write_category_config
from pipeline.scm.runner import (
    ScmRunConfig,
    merge_all_evidence,
    resolve_scm_output_dir,
    run_all_seed_categories,
    run_discovery,
    run_seed_category,
    run_scm_pipeline,
    slugs_from_args,
)
from pipeline.scm.seed_categories import list_seed_category_ids
from pipeline.scm.stages import merge_screening, screen_shard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline.scm")


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=5000)
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--paper-limit", type=int, default=None)
    parser.add_argument("--web-limit", type=int, default=None)
    parser.add_argument("--screening-results", type=str, default="")
    parser.add_argument("--input", type=str, default="")
    parser.add_argument("--out-dir", "--output-dir", dest="out_dir", type=str, default="")
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--skip-literature", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip stages whose checkpoints already exist (works with --test-mode)",
    )
    parser.add_argument("--web-max-results-per-query", type=int, default=5)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SCM plan only; do not process papers, call APIs, or write CSVs",
    )


def _config_from_args(args: argparse.Namespace, *, slugs: list[str] | None = None) -> ScmRunConfig:
    return ScmRunConfig(
        slugs=slugs or [],
        start=getattr(args, "start", 0),
        end=getattr(args, "end", 5000),
        top_n=getattr(args, "top_n", None),
        paper_limit=getattr(args, "paper_limit", None),
        web_limit=getattr(args, "web_limit", None),
        screening_results=getattr(args, "screening_results", ""),
        input_path=getattr(args, "input", ""),
        output_dir=resolve_scm_output_dir(
            raw=getattr(args, "out_dir", ""),
            test_mode=getattr(args, "test_mode", False),
        ),
        test_mode=getattr(args, "test_mode", False),
        skip_web=getattr(args, "skip_web", False),
        skip_literature=getattr(args, "skip_literature", False),
        web_max_results_per_query=getattr(args, "web_max_results_per_query", 5),
        dry_run=getattr(args, "dry_run", False),
        resume=getattr(args, "resume", False),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.scm",
        description="Supplementary Cementitious Materials (SCM) pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Print corpus shard ranges")
    plan.add_argument("--shard-size", type=int, default=10000)
    plan.add_argument("--input", type=str, default="")

    screen = sub.add_parser("screen", help="Screen one corpus shard for SCM relevance")
    screen.add_argument("--start", type=int, required=True)
    screen.add_argument("--end", type=int, required=True)
    screen.add_argument("--input", type=str, default="")
    screen.add_argument("--out-dir", type=str, default="")
    screen.add_argument("--keyword-only", action="store_true")

    merge_screen = sub.add_parser("merge-screening", help="Merge SCM screening shards")
    merge_screen.add_argument("--inputs", type=str, required=True)
    merge_screen.add_argument("--out-dir", type=str, default="")

    retrieve = sub.add_parser("retrieve", help="Retrieve/rank papers for a seed category")
    _add_run_args(retrieve)
    retrieve.add_argument("--subcategory", type=str, required=True)
    retrieve.add_argument("--retrieve-only", action="store_true")

    extract_lit = sub.add_parser("extract-literature", help="Literature extraction for a seed category")
    _add_run_args(extract_lit)
    extract_lit.add_argument("--subcategory", type=str, required=True)

    extract_web = sub.add_parser("extract-web", help="Web extraction for a seed category")
    _add_run_args(extract_web)
    extract_web.add_argument("--subcategory", type=str, required=True)

    merge_ev = sub.add_parser("merge-evidence", help="Merge seed + discovery evidence")
    merge_ev.add_argument("--out-dir", type=str, default="")
    merge_ev.add_argument("--test-mode", action="store_true")

    discover = sub.add_parser("discover", help="Open-ended SCM discovery extraction")
    _add_run_args(discover)

    normalize = sub.add_parser("normalize-materials", help="Normalize discovery material names")
    normalize.add_argument("--out-dir", type=str, default="")
    normalize.add_argument("--overrides", type=str, default="")

    cluster = sub.add_parser("cluster-categories", help="Corpus-level category clustering")
    cluster.add_argument("--out-dir", type=str, default="")
    cluster.add_argument("--heuristic-only", action="store_true")

    summarize = sub.add_parser("summarize-categories", help="Write discovered-category recommendations")
    summarize.add_argument("--out-dir", type=str, default="")
    summarize.add_argument("--heuristic-only", action="store_true")

    run_seed = sub.add_parser("run-seed-category", help="Run one seed category end-to-end")
    _add_run_args(run_seed)
    run_seed.add_argument("--subcategory", type=str, required=True)

    run_all_seeds = sub.add_parser("run-all-seed-categories", help="Run all seed categories")
    _add_run_args(run_all_seeds)

    run_disc = sub.add_parser("run-discovery", help="Run discovery branch end-to-end")
    _add_run_args(run_disc)

    run_all = sub.add_parser("run-all", help="Run all seed categories + discovery + merge")
    _add_run_args(run_all)

    gen = sub.add_parser("generate-category-config", help="Draft proposed category YAML")
    gen.add_argument("--category", type=str, required=True)
    gen.add_argument("--output", type=str, default="")
    gen.add_argument("--out-dir", type=str, default="")

    sample = sub.add_parser(
        "sample-papers",
        help="Create a reproducible SCM paper sample pickle + manifest",
    )
    sample.add_argument("--size", type=int, default=100)
    sample.add_argument("--seed", type=int, default=42)
    sample.add_argument("--input", type=str, default="")
    sample.add_argument("--out-dir", type=str, required=True)

    return parser


def _cmd_plan(args: argparse.Namespace) -> int:
    _, total = validate_pickle_corpus(args.input or None)
    shards = plan_corpus_shards(total, args.shard_size)
    print(f"Corpus records: {total}")
    print(f"Shard size: {args.shard_size}")
    print(f"Shard count: {len(shards)}")
    for shard in shards:
        print(f"  task {shard.index}: start={shard.start} end={shard.end}")
    return 0


def _cmd_screen(args: argparse.Namespace) -> int:
    out_dir = resolve_scm_output_dir(raw=args.out_dir, test_mode=False)
    shard_dir = out_dir / "shards" / "screening"
    screening_dir = out_dir / "screening"
    shard_dir.mkdir(parents=True, exist_ok=True)
    screening_dir.mkdir(parents=True, exist_ok=True)
    out_path = shard_dir / f"screening_{args.start}_{args.end}.jsonl"
    screen_shard(
        start=args.start,
        end=args.end,
        input_path=args.input or None,
        output_path=out_path,
        keyword_only=args.keyword_only,
    )
    logger.info("Wrote SCM screening shard -> %s", out_path)
    return 0


def _cmd_merge_screening(args: argparse.Namespace) -> int:
    from pipeline.scm.io import glob_shard_files

    out_dir = resolve_scm_output_dir(raw=args.out_dir, test_mode=False)
    inputs = Path(args.inputs)
    paths = [inputs] if inputs.is_file() else glob_shard_files(inputs)
    out_path = screening_merged_path(out_dir)
    # Flat convenience copy retained for older docs/scripts.
    flat = out_dir / "screening_merged.jsonl"
    merge_screening(paths, out_path)
    merge_screening(paths, flat)
    logger.info("Merged %s SCM screening shards -> %s", len(paths), out_path)
    return 0


def _normalize_and_cluster(out_dir: Path, *, heuristic_only: bool) -> list[dict]:
    records_path = discovery_records_path(out_dir)
    discovery_rows = read_jsonl_discovery(records_path)
    if not discovery_rows:
        discovery_rows = read_jsonl_discovery(out_dir / DISCOVERY_RECORDS)
    records = [row.to_discovery_dict() for row in discovery_rows]
    overrides = load_alias_overrides()
    normalization = normalize_discovery_records(records, overrides=overrides)
    export_normalization_csv(normalization_path(out_dir), normalization)
    export_normalization_csv(out_dir / NORMALIZATION_CSV, normalization)

    by_raw = {row["raw_material_name"]: row for row in normalization}
    aggregated = aggregate_discovery_candidates(discovery_rows, normalization_by_raw=by_raw)
    if heuristic_only:
        groupings = heuristic_groupings(aggregated)
    else:
        groupings = cluster_categories_with_llm(aggregated_for_llm_prompt(aggregated))
        if not groupings:
            groupings = heuristic_groupings(aggregated)

    rows = build_discovered_category_rows(
        aggregated,
        llm_groupings=groupings,
        thresholds=get_promotion_thresholds(),
    )
    export_discovered_categories_csv(discovered_categories_path(out_dir), rows)
    export_discovered_categories_csv(out_dir / DISCOVERED_CATEGORIES_CSV, rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command

    if command == "plan":
        return _cmd_plan(args)
    if command == "screen":
        return _cmd_screen(args)
    if command == "merge-screening":
        return _cmd_merge_screening(args)

    if command == "retrieve":
        config = _config_from_args(args, slugs=slugs_from_args(subcategory=args.subcategory))
        config.stage = "literature"
        config.retrieve_only = True
        run_seed_category(config, config.slugs[0])
        return 0

    if command == "extract-literature":
        config = _config_from_args(args, slugs=slugs_from_args(subcategory=args.subcategory))
        config.stage = "extract-literature"
        config.skip_web = True
        run_seed_category(config, config.slugs[0])
        return 0

    if command == "extract-web":
        config = _config_from_args(args, slugs=slugs_from_args(subcategory=args.subcategory))
        config.stage = "extract-web"
        config.skip_literature = True
        run_seed_category(config, config.slugs[0])
        return 0

    if command == "merge-evidence":
        config = _config_from_args(args)
        config.stage = "merge-evidence"
        merge_all_evidence(config)
        return 0

    if command in {"discover", "run-discovery"}:
        config = _config_from_args(args)
        config.run_discovery = True
        config.stage = "discover"
        run_discovery(config)
        return 0

    if command == "normalize-materials":
        out_dir = resolve_scm_output_dir(raw=args.out_dir, test_mode=False)
        discovery_rows = read_jsonl_discovery(out_dir / DISCOVERY_RECORDS)
        overrides = load_alias_overrides(Path(args.overrides) if args.overrides else None)
        normalization = normalize_discovery_records(
            [row.to_discovery_dict() for row in discovery_rows],
            overrides=overrides,
        )
        path = export_normalization_csv(out_dir / NORMALIZATION_CSV, normalization)
        logger.info("Wrote normalization CSV -> %s (%s rows)", path, len(normalization))
        return 0

    if command in {"cluster-categories", "summarize-categories"}:
        out_dir = resolve_scm_output_dir(raw=args.out_dir, test_mode=False)
        rows = _normalize_and_cluster(out_dir, heuristic_only=args.heuristic_only)
        logger.info(
            "Wrote %s discovered categories -> %s",
            len(rows),
            out_dir / DISCOVERED_CATEGORIES_CSV,
        )
        return 0

    if command == "run-seed-category":
        config = _config_from_args(args, slugs=slugs_from_args(subcategory=args.subcategory))
        config.stage = "run-seed-category"
        run_seed_category(config, config.slugs[0])
        return 0

    if command == "run-all-seed-categories":
        config = _config_from_args(args, slugs=list_seed_category_ids())
        config.stage = "run-all-seed-categories"
        config.run_discovery = False
        run_all_seed_categories(config)
        return 0

    if command == "run-all":
        config = _config_from_args(args, slugs=list_seed_category_ids())
        config.stage = "run-all"
        config.run_discovery = True
        if config.dry_run:
            from pipeline.scm.runner import print_dry_run

            print_dry_run(config)
            return 0
        run_scm_pipeline(config)
        _normalize_and_cluster(config.output_dir, heuristic_only=True)
        return 0

    if command == "generate-category-config":
        out_dir = resolve_scm_output_dir(raw=args.out_dir, test_mode=False)
        discovered_path = out_dir / DISCOVERED_CATEGORIES_CSV
        discovered_row = {}
        if discovered_path.is_file():
            with discovered_path.open(encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    if row.get("proposed_category", "").lower() == args.category.lower():
                        discovered_row = row
                        break
        payload = build_category_config_payload(
            category=args.category,
            discovered_row=discovered_row,
        )
        if args.output:
            output = Path(args.output)
            if not output.is_absolute():
                output = REPO_ROOT / output
        else:
            output = candidate_config_dir(REPO_ROOT) / f"{payload['category_id']}.yaml"
        write_category_config(payload, output)
        logger.info("Wrote proposed category config (status=proposed) -> %s", output)
        logger.info("This config is inactive until manually approved.")
        return 0

    if command == "sample-papers":
        from pipeline.scm.sample import write_sample_artifacts

        out_dir = Path(args.out_dir)
        if not out_dir.is_absolute():
            out_dir = (REPO_ROOT / out_dir).resolve()
        pickle_path, manifest_path = write_sample_artifacts(
            output_dir=out_dir,
            sample_size=args.size,
            random_seed=args.seed,
            input_path=args.input or None,
        )
        logger.info("Sample pickle -> %s", pickle_path)
        logger.info("Sample manifest -> %s", manifest_path)
        return 0

    parser.error(f"Unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
