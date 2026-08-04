#!/usr/bin/env python3
"""Cluster stage CLI for genuinely sharded Cementitious Materials runs."""

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

from pipeline.cementitious.migrate_carbon_capture import migrate_carbon_capture
from pipeline.cementitious.paths import (
    get_730_results_dir,
    migrate_legacy_results,
    resolve_output_dir,
)
from pipeline.cementitious.stages import (
    DEFAULT_EXTRACT_SHARD_SIZE,
    DEFAULT_SHARD_SIZE,
    dedupe_and_qc,
    extract_shard,
    export_final,
    merge_extractions,
    merge_screening,
    missing_extraction_shards,
    missing_screen_shards,
    plan_screen_shards,
    rank_and_plan_extraction,
    screen_shard,
)
from pipeline.cementitious.web_config import load_web_limits
from pipeline.cementitious.web_stages import (
    merge_literature_and_web,
    merge_web_extractions,
    merge_web_search,
    missing_web_extraction_shards,
    missing_web_search_shards,
    plan_web_extraction,
    plan_web_query_shards,
    web_extract_shard,
    web_search_shard,
)
from pipeline.llm_utils import DEFAULT_MODEL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline.cementitious.cluster")


def _output_dir(explicit: str | None = None) -> Path:
    if explicit:
        return resolve_output_dir(explicit)
    checkpoint = os.getenv("CHECKPOINT_DIR", "").strip()
    if checkpoint:
        path = Path(checkpoint)
        if path.name == "checkpoints":
            return path.parent
        return path
    return get_730_results_dir()


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip() in {"1", "true", "True", "yes", "YES"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.cementitious.cluster")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan-screen", aliases=["plan"], help="Plan screening shards (no LLM)")
    plan.add_argument("--input", default="")
    plan.add_argument("--output", default="")
    plan.add_argument("--shard-size", type=int, default=int(os.getenv("SHARD_SIZE", str(DEFAULT_SHARD_SIZE))))

    migrate_legacy = sub.add_parser(
        "migrate-legacy-results",
        help="Migrate legacy '7-30 results' output into '7-30 results'",
    )
    migrate_legacy.add_argument("--results-root", default="")
    migrate_legacy.add_argument("--mode", choices=["copy", "move"], default="copy")

    screen = sub.add_parser("screen", help="Screen one corpus shard")
    screen.add_argument("--shard-id", type=int, required=True)
    screen.add_argument("--manifest", default="")
    screen.add_argument("--output", default="")
    screen.add_argument("--keyword-only", action="store_true")
    screen.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    screen.add_argument("--resume", action="store_true")

    merge_screen = sub.add_parser("merge-screen", help="Verify and merge screening shards")
    merge_screen.add_argument("--output", default="")

    rank = sub.add_parser("rank-and-plan-extraction", help="Rank candidates and plan extract shards")
    rank.add_argument("--output", default="")
    rank.add_argument("--top-n", type=int, default=None)
    rank.add_argument("--extract-shard-size", type=int, default=None)
    rank.add_argument("--top-n-per-subcategory", type=int, default=None)
    rank.add_argument("--top-n-per-sub-subcategory", type=int, default=None)

    extract = sub.add_parser("extract", help="Extract one ranked-candidate shard")
    extract.add_argument("--shard-id", type=int, required=True)
    extract.add_argument("--manifest", default="")
    extract.add_argument("--output", default="")
    extract.add_argument("--keyword-only", action="store_true")
    extract.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    extract.add_argument("--resume", action="store_true")

    merge_extract = sub.add_parser("merge-extract", help="Verify and merge extraction shards")
    merge_extract.add_argument("--output", default="")

    # ── Web stages ───────────────────────────────────────────────────────────
    plan_web = sub.add_parser("plan-web-queries", help="Plan taxonomy-scoped web queries")
    plan_web.add_argument("--output", default="")

    web_search = sub.add_parser("web-search", help="Run one web-search shard (Tavily)")
    web_search.add_argument("--shard-id", type=int, required=True)
    web_search.add_argument("--manifest", default="")
    web_search.add_argument("--output", default="")
    web_search.add_argument("--resume", action="store_true")

    merge_web_s = sub.add_parser("merge-web-search", help="Verify/merge web search shards + screen")
    merge_web_s.add_argument("--output", default="")

    plan_web_ex = sub.add_parser("plan-web-extract", help="Plan web extraction shards")
    plan_web_ex.add_argument("--output", default="")

    web_extract = sub.add_parser("web-extract", help="Extract one web-source shard")
    web_extract.add_argument("--shard-id", type=int, required=True)
    web_extract.add_argument("--manifest", default="")
    web_extract.add_argument("--output", default="")
    web_extract.add_argument("--keyword-only", action="store_true")
    web_extract.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    web_extract.add_argument("--resume", action="store_true")

    merge_web_e = sub.add_parser("merge-web-extract", help="Verify and merge web extraction shards")
    merge_web_e.add_argument("--output", default="")

    merge_lw = sub.add_parser("merge-literature-web", help="Merge literature and web records")
    merge_lw.add_argument("--output", default="")

    miss_ws = sub.add_parser("missing-web-search-shards", help="Slurm array for incomplete web search")
    miss_ws.add_argument("--output", default="")

    miss_we = sub.add_parser(
        "missing-web-extraction-shards",
        help="Slurm array for incomplete web extraction",
    )
    miss_we.add_argument("--output", default="")

    dedupe = sub.add_parser("dedupe-qc", help="Deduplicate and QC merged extractions")
    dedupe.add_argument("--output", default="")
    dedupe.add_argument("--skip-qc", action="store_true")
    dedupe.add_argument("--keyword-only", action="store_true")
    dedupe.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL))

    export = sub.add_parser("export", help="Final taxonomy partition export")
    export.add_argument("--output", default="")
    export.add_argument("--force", action="store_true")

    fin = sub.add_parser(
        "finalize-metadata",
        help="Write metadata/run_manifest.json + validation_report.json for an existing output dir (no LLM/web)",
    )
    fin.add_argument("--output", default="")
    fin.add_argument("--force", action="store_true", help="Rewrite metadata even if export.complete exists")
    fin.add_argument(
        "--allow-fail",
        action="store_true",
        help="Write metadata even when validation fails (does not write export.complete)",
    )

    migrate = sub.add_parser("migrate-carbon-capture")
    migrate.add_argument("--input", required=True)
    migrate.add_argument("--output", default="")

    miss_s = sub.add_parser("missing-screen-shards", help="Print Slurm array spec for incomplete screen shards")
    miss_s.add_argument("--output", default="")

    miss_e = sub.add_parser("missing-extraction-shards", help="Print Slurm array spec for incomplete extract shards")
    miss_e.add_argument("--output", default="")

    args = parser.parse_args(argv)
    resume = bool(getattr(args, "resume", False) or _bool_env("RESUME"))
    keyword_only = bool(getattr(args, "keyword_only", False) or _bool_env("KEYWORD_ONLY"))

    if args.command in {"plan-screen", "plan"}:
        pickle_path = args.input or os.getenv("PICKLE_PATH") or os.getenv("PAPER_RECORDS_PATH")
        if not pickle_path:
            raise SystemExit("PICKLE_PATH / PAPER_RECORDS_PATH required")
        result = plan_screen_shards(
            input_path=pickle_path,
            output_dir=_output_dir(args.output or None),
            shard_size=args.shard_size,
            selected_subcategories=_csv_env("SELECTED_SUBCATEGORIES") or None,
            selected_sub_subcategories=_csv_env("SELECTED_SUB_SUBCATEGORIES") or None,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "migrate-legacy-results":
        result = migrate_legacy_results(
            results_root=args.results_root or None,
            mode=args.mode,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "screen":
        out = _output_dir(args.output or None)
        result = screen_shard(
            shard_id=args.shard_id,
            output_dir=out,
            manifest_path=args.manifest or None,
            keyword_only=keyword_only,
            model=args.model,
            resume=resume,
            focus_sub_slugs=_csv_env("SELECTED_SUBCATEGORIES") or None,
            focus_ss_slugs=_csv_env("SELECTED_SUB_SUBCATEGORIES") or None,
        )
        print(json.dumps(result, indent=2, default=str))
        if result.get("status") == "soft_memory_stop":
            return 75
        return 0

    if args.command == "merge-screen":
        result = merge_screening(output_dir=_output_dir(args.output or None))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "rank-and-plan-extraction":
        top_n = args.top_n
        if top_n is None:
            top_n = int(os.getenv("TOP_N", os.getenv("TOP_N_SOURCES", "50")))
        extract_size = args.extract_shard_size
        if extract_size is None:
            extract_size = int(os.getenv("EXTRACT_SHARD_SIZE", str(DEFAULT_EXTRACT_SHARD_SIZE)))
        per_sub = args.top_n_per_subcategory
        if per_sub is None and os.getenv("TOP_N_PER_SUBCATEGORY"):
            per_sub = int(os.getenv("TOP_N_PER_SUBCATEGORY"))
        per_ss = args.top_n_per_sub_subcategory
        if per_ss is None and os.getenv("TOP_N_PER_SUB_SUBCATEGORY"):
            per_ss = int(os.getenv("TOP_N_PER_SUB_SUBCATEGORY"))
        result = rank_and_plan_extraction(
            output_dir=_output_dir(args.output or None),
            top_n=top_n,
            top_n_per_subcategory=per_sub,
            top_n_per_sub_subcategory=per_ss,
            extract_shard_size=extract_size,
            selected_subcategories=_csv_env("SELECTED_SUBCATEGORIES") or None,
            selected_sub_subcategories=_csv_env("SELECTED_SUB_SUBCATEGORIES") or None,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "extract":
        out = _output_dir(args.output or None)
        result = extract_shard(
            shard_id=args.shard_id,
            output_dir=out,
            manifest_path=args.manifest or None,
            model=args.model,
            resume=resume,
            keyword_only=keyword_only,
            selected_sub_slugs=_csv_env("SELECTED_SUBCATEGORIES") or None,
            selected_ss_slugs=_csv_env("SELECTED_SUB_SUBCATEGORIES") or None,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "merge-extract":
        result = merge_extractions(output_dir=_output_dir(args.output or None))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "plan-web-queries":
        result = plan_web_query_shards(
            output_dir=_output_dir(args.output or None),
            limits=load_web_limits(),
            selected_subcategories=_csv_env("SELECTED_SUBCATEGORIES") or None,
            selected_sub_subcategories=_csv_env("SELECTED_SUB_SUBCATEGORIES") or None,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "web-search":
        result = web_search_shard(
            shard_id=args.shard_id,
            output_dir=_output_dir(args.output or None),
            manifest_path=args.manifest or None,
            resume=resume,
            limits=load_web_limits(),
        )
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "merge-web-search":
        result = merge_web_search(output_dir=_output_dir(args.output or None))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "plan-web-extract":
        result = plan_web_extraction(
            output_dir=_output_dir(args.output or None),
            limits=load_web_limits(),
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "web-extract":
        result = web_extract_shard(
            shard_id=args.shard_id,
            output_dir=_output_dir(args.output or None),
            manifest_path=args.manifest or None,
            resume=resume,
            keyword_only=keyword_only,
            model=args.model,
            limits=load_web_limits(),
        )
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "merge-web-extract":
        result = merge_web_extractions(output_dir=_output_dir(args.output or None))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "merge-literature-web":
        result = merge_literature_and_web(output_dir=_output_dir(args.output or None))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "missing-web-search-shards":
        missing_web_search_shards(output_dir=_output_dir(args.output or None))
        return 0

    if args.command == "missing-web-extraction-shards":
        missing_web_extraction_shards(output_dir=_output_dir(args.output or None))
        return 0

    if args.command == "dedupe-qc":
        result = dedupe_and_qc(
            output_dir=_output_dir(args.output or None),
            run_qc=not args.skip_qc,
            model=args.model,
            keyword_only=keyword_only,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "export":
        from pipeline.cementitious.final_metadata import FinalMetadataError

        try:
            result = export_final(
                output_dir=_output_dir(args.output or None),
                force=bool(args.force or _bool_env("FORCE")),
            )
        except FinalMetadataError as exc:
            print(json.dumps({"status": "validation_failed", "error": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "finalize-metadata":
        from pipeline.cementitious.final_metadata import FinalMetadataError, finalize_metadata

        try:
            result = finalize_metadata(
                output_dir=_output_dir(args.output or None),
                force=bool(args.force or _bool_env("FORCE")),
                write_export_complete=not bool(args.allow_fail),
                require_pass=not bool(args.allow_fail),
            )
        except FinalMetadataError as exc:
            print(json.dumps({"status": "validation_failed", "error": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "migrate-carbon-capture":
        report = migrate_carbon_capture(
            input_path=args.input,
            output_dir=_output_dir(args.output or None),
        )
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "missing-screen-shards":
        missing_screen_shards(output_dir=_output_dir(args.output or None))
        return 0

    if args.command == "missing-extraction-shards":
        missing_extraction_shards(output_dir=_output_dir(args.output or None))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
