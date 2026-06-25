#!/usr/bin/env python3
"""
Distributed carbon capture pipeline for MIT Engaging / SLURM-style clusters.

Run one stage per array task, then merge on a login node:

  1. screen      — abstract screening shards (title + abstract)
  2. merge-screen — combine screening JSONL shards
  3. retrieve    — methodology ranking shards (no global top_n yet)
  4. merge-rank  — global top-N papers per methodology
  5. extract     — 26-question extraction on ranked papers
  6. merge-extract — combine extraction shards
  7. export-csv  — write final answers/citations CSV files
  8. plan        — print shard ranges for job arrays

Examples:
    python pipeline/run_carbon_capture_cluster.py plan --shard-size 10000
    python pipeline/run_carbon_capture_cluster.py screen --task-id 0 --shard-size 10000
    python pipeline/run_carbon_capture_cluster.py merge-screen --inputs outputs/carbon_capture/shards/screening
    python pipeline/run_carbon_capture_cluster.py retrieve --methodology amine_absorption \\
        --task-id 0 --shard-size 10000 --screening-results outputs/carbon_capture/screening_merged.jsonl
    python pipeline/run_carbon_capture_cluster.py merge-rank --methodology amine_absorption \\
        --inputs outputs/carbon_capture/shards/retrieve/amine_absorption --top-n 50
    python pipeline/run_carbon_capture_cluster.py extract --methodology amine_absorption \\
        --ranked-results outputs/carbon_capture/ranked/amine_absorption_final.jsonl
    python pipeline/run_carbon_capture_cluster.py export-csv --methodology amine_absorption \\
        --extraction-results outputs/carbon_capture/extractions/amine_absorption_merged.jsonl
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.carbon_capture_config import OUTPUT_DIR_NAME, get_methodology, list_methodology_slugs
from pipeline.carbon_capture_export import write_methodology_csvs
from pipeline.carbon_capture_io import glob_shard_files, read_extraction_shard
from pipeline.carbon_capture_stages import (
    corpus_record_count,
    extract_methodology_ranked_list,
    merge_methodology_extractions,
    merge_methodology_ranked_shards,
    merge_screening_outputs,
    retrieve_methodology_shard,
)
from pipeline.cluster_shards import plan_corpus_shards, shard_for_array_task
from pipeline.config import get_output_dir, get_top_n_sources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_carbon_capture_cluster")


def _cluster_root(raw: str = "") -> Path:
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else (get_output_dir() / path)
    return get_output_dir() / OUTPUT_DIR_NAME


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


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cluster-dir", type=str, default="", help="Base output dir")
    parser.add_argument("--input", type=str, default="", help="Pickle corpus path")
    parser.add_argument("--shard-size", type=int, default=10000, help="Records per shard")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Distributed carbon capture cluster runner")
    subparsers = parser.add_subparsers(dest="stage", required=True)

    plan = subparsers.add_parser("plan", help="Print shard ranges")
    _add_common_args(plan)

    screen = subparsers.add_parser("screen", help="Run one abstract screening shard")
    _add_common_args(screen)
    screen.add_argument("--task-id", type=int, default=None)

    merge_screen = subparsers.add_parser("merge-screen", help="Merge screening shards")
    merge_screen.add_argument("--cluster-dir", type=str, default="")
    merge_screen.add_argument("--inputs", type=str, required=True)

    retrieve = subparsers.add_parser("retrieve", help="Retrieve/rank one methodology shard")
    _add_common_args(retrieve)
    retrieve.add_argument("--methodology", type=str, required=True)
    retrieve.add_argument("--task-id", type=int, default=None)
    retrieve.add_argument("--screening-results", type=str, required=True)

    merge_rank = subparsers.add_parser("merge-rank", help="Merge ranked shards to global top-N")
    merge_rank.add_argument("--cluster-dir", type=str, default="")
    merge_rank.add_argument("--methodology", type=str, required=True)
    merge_rank.add_argument("--inputs", type=str, required=True)
    merge_rank.add_argument("--top-n", type=int, default=None)

    extract = subparsers.add_parser("extract", help="Extract one ranked batch")
    extract.add_argument("--cluster-dir", type=str, default="")
    extract.add_argument("--methodology", type=str, required=True)
    extract.add_argument("--ranked-results", type=str, required=True)
    extract.add_argument("--batch-start", type=int, default=0)
    extract.add_argument("--batch-end", type=int, default=None)
    extract.add_argument("--task-id", type=int, default=None)
    extract.add_argument("--input", type=str, default="", help="Pickle corpus path")
    extract.add_argument("--extract-batch-size", type=int, default=5)

    merge_extract = subparsers.add_parser("merge-extract", help="Merge extraction shards")
    merge_extract.add_argument("--cluster-dir", type=str, default="")
    merge_extract.add_argument("--methodology", type=str, required=True)
    merge_extract.add_argument("--inputs", type=str, required=True)

    export_csv = subparsers.add_parser("export-csv", help="Write answers/citations CSV")
    export_csv.add_argument("--cluster-dir", type=str, default="")
    export_csv.add_argument("--methodology", type=str, required=True)
    export_csv.add_argument("--extraction-results", type=str, required=True)

    return parser


def _run_screen(args: argparse.Namespace) -> int:
    task_id = _task_id_from_env(args)
    total = corpus_record_count(args.input or None)
    shards = plan_corpus_shards(total, args.shard_size)
    shard = shard_for_array_task(shards, task_id)
    cluster_dir = _cluster_root(args.cluster_dir)
    out_dir = cluster_dir / "shards" / "screening"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"screening_{shard.label}.jsonl"

    from pipeline.ccs_abstract_classifier import classify_records_parallel
    from pipeline.load_corpus import load_paper_records_slice
    import json

    records, slice_end = load_paper_records_slice(
        path=args.input or None,
        start=shard.start,
        end=shard.end,
    )
    results = classify_records_parallel(records, start_index=shard.start)
    meta = {
        "type": "screening_meta",
        "start": shard.start,
        "end": slice_end,
        "screened": len(results),
        "stage": "abstract_screening",
        "shard_index": shard.index,
    }
    with out_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for result in results:
            handle.write(json.dumps(result.model_dump()) + "\n")

    relevant = sum(1 for row in results if row.is_relevant)
    logger.info(
        "Screening shard %s wrote %s results (%s relevant) -> %s",
        shard.label,
        len(results),
        relevant,
        out_path,
    )
    return 0


def _run_plan(args: argparse.Namespace) -> int:
    total = corpus_record_count(args.input or None)
    shards = plan_corpus_shards(total, args.shard_size)
    print(f"Corpus records: {total}")
    print(f"Shard size: {args.shard_size}")
    print(f"Shard count: {len(shards)}")
    for shard in shards:
        print(f"  task {shard.index}: start={shard.start} end={shard.end}")
    print(f"\nUse SLURM_ARRAY_TASK_ID 0-{len(shards) - 1} for array jobs.")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.stage == "plan":
            return _run_plan(args)

        if args.stage == "screen":
            return _run_screen(args)

        cluster_dir = _cluster_root(getattr(args, "cluster_dir", ""))

        if args.stage == "merge-screen":
            inputs = _resolve_inputs(args.inputs)
            out_path = cluster_dir / "screening_merged.jsonl"
            merge_screening_outputs(inputs, out_path)
            logger.info("Merged %s screening shards -> %s", len(inputs), out_path)
            return 0

        if args.stage == "retrieve":
            methodology = get_methodology(args.methodology)
            task_id = _task_id_from_env(args)
            total = corpus_record_count(args.input or None)
            shards = plan_corpus_shards(total, args.shard_size)
            shard = shard_for_array_task(shards, task_id)
            out_dir = cluster_dir / "shards" / "retrieve" / methodology.slug
            out_path = out_dir / f"ranked_{shard.label}.jsonl"
            retrieve_methodology_shard(
                methodology,
                start=shard.start,
                end=shard.end,
                screening_results=args.screening_results,
                input_path=args.input or None,
                output_path=out_path,
            )
            logger.info("Retrieve shard complete -> %s", out_path)
            return 0

        if args.stage == "merge-rank":
            methodology = get_methodology(args.methodology)
            inputs = _resolve_inputs(args.inputs)
            top_n = args.top_n or get_top_n_sources()
            out_dir = cluster_dir / "ranked"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{methodology.slug}_final.jsonl"
            merge_methodology_ranked_shards(
                methodology.slug,
                inputs,
                top_n=top_n,
                output_path=out_path,
            )
            logger.info("Global ranked list -> %s", out_path)
            return 0

        if args.stage == "extract":
            methodology = get_methodology(args.methodology)
            ranked_path = Path(args.ranked_results)
            out_dir = cluster_dir / "shards" / "extract" / methodology.slug
            out_dir.mkdir(parents=True, exist_ok=True)

            if args.batch_end is not None:
                batch_start, batch_end = args.batch_start, args.batch_end
                label = f"extract_{batch_start}_{batch_end}.jsonl"
            else:
                task_id = _task_id_from_env(args)
                batch_size = args.extract_batch_size
                batch_start = task_id * batch_size
                batch_end = batch_start + batch_size
                label = f"extract_{batch_start}_{batch_end}.jsonl"

            out_path = out_dir / label
            extract_methodology_ranked_list(
                methodology,
                [ranked_path],
                output_path=out_path,
                batch_start=batch_start,
                batch_end=batch_end,
                input_path=args.input or None,
            )
            logger.info("Extraction batch -> %s", out_path)
            return 0

        if args.stage == "merge-extract":
            methodology = get_methodology(args.methodology)
            inputs = _resolve_inputs(args.inputs)
            out_dir = cluster_dir / "extractions"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{methodology.slug}_merged.jsonl"
            merge_methodology_extractions(inputs, output_path=out_path)
            logger.info("Merged extraction shards -> %s", out_path)
            return 0

        if args.stage == "export-csv":
            methodology = get_methodology(args.methodology)
            results = read_extraction_shard(args.extraction_results)
            csv_dir = cluster_dir / "csv"
            answers_path, citations_path = write_methodology_csvs(
                results,
                methodology,
                csv_dir,
            )
            logger.info("CSV export -> %s, %s", answers_path, citations_path)
            return 0

    except (ValueError, FileNotFoundError, KeyError) as exc:
        logger.error("%s", exc)
        return 1

    logger.error("Unknown stage: %s", args.stage)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
