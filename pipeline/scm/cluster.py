#!/usr/bin/env python3
"""
Distributed SCM pipeline stages for MIT Engaging / SLURM-style clusters.

Mirrors carbon-capture cluster conventions while writing under outputs/scm/.
Does not hardcode absolute repository paths — uses PICKLE_PATH / OUTPUT_DIR.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cluster_shards import plan_corpus_shards, shard_for_array_task
from pipeline.config import get_top_n_sources
from pipeline.corpus_loader import validate_pickle_corpus
from pipeline.scm.config import assert_scm_output_isolated, scm_output_root
from pipeline.scm.export import export_seed_category_outputs, read_jsonl_evidence
from pipeline.scm.io import glob_shard_files, read_evidence_shard
from pipeline.scm.seed_categories import OUTPUT_DIR_NAME, get_seed_category, list_seed_category_ids
from pipeline.scm.stages import (
    extract_seed_ranked,
    extract_seed_web,
    merge_screening,
    merge_seed_extractions,
    merge_seed_ranked,
    retrieve_seed_shard,
    screen_shard,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline.scm.cluster")


def _cluster_root(raw: str = "") -> Path:
    """Resolve SCM cluster root via SCM_OUTPUT_ROOT / explicit path (never CC)."""
    if raw:
        path = Path(raw)
        if path.is_absolute():
            return assert_scm_output_isolated(path)
        # Absolute-looking env paths or relative under OUTPUT_DIR/scm
        return scm_output_root(str(path))
    return scm_output_root()


def _task_id_from_env(args: argparse.Namespace) -> int:
    if args.task_id is not None:
        return args.task_id
    env = os.getenv("SLURM_ARRAY_TASK_ID") or os.getenv("WORKER_ID")
    if env is not None:
        return int(env)
    raise ValueError("Provide --task-id or set SLURM_ARRAY_TASK_ID / WORKER_ID")


def _resolve_inputs(raw: str, pattern: str = "*.jsonl") -> list[Path]:
    path = Path(raw)
    if path.is_file():
        return [path]
    if path.is_dir():
        return glob_shard_files(path, pattern)
    raise FileNotFoundError(f"No inputs found at {raw}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Distributed SCM cluster runner")
    sub = parser.add_subparsers(dest="stage", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--cluster-dir", type=str, default="")
    plan.add_argument("--input", type=str, default="")
    plan.add_argument("--shard-size", type=int, default=10000)

    screen = sub.add_parser("screen")
    screen.add_argument("--cluster-dir", type=str, default="")
    screen.add_argument("--input", type=str, default="")
    screen.add_argument("--shard-size", type=int, default=10000)
    screen.add_argument("--task-id", type=int, default=None)
    screen.add_argument("--keyword-only", action="store_true")

    merge_screen = sub.add_parser("merge-screen")
    merge_screen.add_argument("--cluster-dir", type=str, default="")
    merge_screen.add_argument("--inputs", type=str, required=True)

    retrieve = sub.add_parser("retrieve")
    retrieve.add_argument("--cluster-dir", type=str, default="")
    retrieve.add_argument("--input", type=str, default="")
    retrieve.add_argument("--shard-size", type=int, default=10000)
    retrieve.add_argument("--task-id", type=int, default=None)
    retrieve.add_argument("--subcategory", type=str, required=True)
    retrieve.add_argument("--screening-results", type=str, required=True)

    merge_rank = sub.add_parser("merge-rank")
    merge_rank.add_argument("--cluster-dir", type=str, default="")
    merge_rank.add_argument("--subcategory", type=str, required=True)
    merge_rank.add_argument("--inputs", type=str, required=True)
    merge_rank.add_argument("--top-n", type=int, default=None)

    extract = sub.add_parser("extract")
    extract.add_argument("--cluster-dir", type=str, default="")
    extract.add_argument("--subcategory", type=str, required=True)
    extract.add_argument("--ranked-results", type=str, required=True)
    extract.add_argument("--batch-start", type=int, default=0)
    extract.add_argument("--batch-end", type=int, default=None)
    extract.add_argument("--input", type=str, default="")

    merge_extract = sub.add_parser("merge-extract")
    merge_extract.add_argument("--cluster-dir", type=str, default="")
    merge_extract.add_argument("--subcategory", type=str, required=True)
    merge_extract.add_argument("--inputs", type=str, required=True)

    web = sub.add_parser("web")
    web.add_argument("--cluster-dir", type=str, default="")
    web.add_argument("--subcategory", type=str, required=True)
    web.add_argument("--literature-results", type=str, required=True)
    web.add_argument("--web-limit", type=int, default=None)
    web.add_argument("--web-max-results-per-query", type=int, default=5)

    export_csv = sub.add_parser("export-csv")
    export_csv.add_argument("--cluster-dir", type=str, default="")
    export_csv.add_argument("--subcategory", type=str, required=True)
    export_csv.add_argument("--extraction-results", type=str, required=True)
    export_csv.add_argument("--web-results", type=str, default="")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    cluster_dir = _cluster_root(getattr(args, "cluster_dir", ""))

    if args.stage == "plan":
        _, total = validate_pickle_corpus(args.input or None)
        shards = plan_corpus_shards(total, args.shard_size)
        print(f"Corpus records: {total}")
        print(f"Shard size: {args.shard_size}")
        print(f"Shard count: {len(shards)}")
        print(f"SCM output root: {cluster_dir} (category={OUTPUT_DIR_NAME})")
        print(f"Seed categories: {', '.join(list_seed_category_ids())}")
        for shard in shards:
            print(f"  task {shard.index}: start={shard.start} end={shard.end}")
        return 0

    if args.stage == "screen":
        task_id = _task_id_from_env(args)
        _, total = validate_pickle_corpus(args.input or None)
        shards = plan_corpus_shards(total, args.shard_size)
        shard = shard_for_array_task(shards, task_id)
        out_dir = cluster_dir / "shards" / "screening"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"screening_{shard.label}.jsonl"
        if out_path.is_file() and out_path.stat().st_size > 0:
            logger.info("Resume: screening shard already complete -> %s", out_path)
            return 0
        screen_shard(
            start=shard.start,
            end=shard.end,
            input_path=args.input or None,
            output_path=out_path,
            keyword_only=args.keyword_only,
        )
        return 0

    if args.stage == "merge-screen":
        paths = _resolve_inputs(args.inputs)
        out_path = cluster_dir / "screening_merged.jsonl"
        merge_screening(paths, out_path)
        return 0

    if args.stage == "retrieve":
        task_id = _task_id_from_env(args)
        _, total = validate_pickle_corpus(args.input or None)
        shards = plan_corpus_shards(total, args.shard_size)
        shard = shard_for_array_task(shards, task_id)
        out_dir = cluster_dir / "shards" / "retrieve" / args.subcategory
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"ranked_{shard.label}.jsonl"
        if out_path.is_file() and out_path.stat().st_size > 0:
            logger.info("Resume: retrieve shard already complete -> %s", out_path)
            return 0
        retrieve_seed_shard(
            args.subcategory,
            start=shard.start,
            end=shard.end,
            screening_results=args.screening_results,
            input_path=args.input or None,
            output_path=out_path,
        )
        return 0

    if args.stage == "merge-rank":
        paths = _resolve_inputs(args.inputs)
        top_n = args.top_n or get_top_n_sources()
        out_dir = cluster_dir / "ranked"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.subcategory}_final.jsonl"
        merge_seed_ranked(args.subcategory, paths, top_n=top_n, output_path=out_path)
        return 0

    if args.stage == "extract":
        out_dir = cluster_dir / "shards" / "extract" / args.subcategory
        out_dir.mkdir(parents=True, exist_ok=True)
        label = f"{args.batch_start}_{args.batch_end or 'end'}"
        out_path = out_dir / f"extract_{label}.jsonl"
        if out_path.is_file() and out_path.stat().st_size > 0:
            logger.info("Resume: extract shard already complete -> %s", out_path)
            return 0
        extract_seed_ranked(
            args.subcategory,
            [Path(args.ranked_results)],
            output_path=out_path,
            batch_start=args.batch_start,
            batch_end=args.batch_end,
            input_path=args.input or None,
        )
        return 0

    if args.stage == "merge-extract":
        paths = _resolve_inputs(args.inputs)
        out_dir = cluster_dir / "extractions"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.subcategory}_merged.jsonl"
        merge_seed_extractions(args.subcategory, paths, output_path=out_path)
        return 0

    if args.stage == "web":
        out_dir = cluster_dir / "web"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.subcategory}_web.jsonl"
        if out_path.is_file() and out_path.stat().st_size > 0:
            logger.info("Resume: web extraction already complete -> %s", out_path)
            return 0
        web_limit = args.web_limit
        if web_limit is None:
            env = os.getenv("WEB_LIMIT", "").strip()
            web_limit = int(env) if env else get_top_n_sources()
        extract_seed_web(
            args.subcategory,
            literature_rows_path=args.literature_results,
            output_path=out_path,
            max_results_per_query=args.web_max_results_per_query,
            max_total_sources=web_limit,
        )
        return 0

    if args.stage == "export-csv":
        literature = read_evidence_shard(args.extraction_results)
        if not literature:
            literature = read_jsonl_evidence(args.extraction_results)
        web_path = args.web_results or str(cluster_dir / "web" / f"{args.subcategory}_web.jsonl")
        web_rows = read_evidence_shard(web_path) or read_jsonl_evidence(web_path)
        csv_dir = cluster_dir / "csv"
        export_seed_category_outputs(
            literature_rows=literature,
            web_rows=web_rows,
            category=get_seed_category(args.subcategory),
            output_dir=csv_dir,
        )
        return 0

    raise ValueError(f"Unknown stage: {args.stage}")


if __name__ == "__main__":
    raise SystemExit(main())
