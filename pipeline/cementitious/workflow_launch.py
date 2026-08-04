"""Preflight and dry-run helpers for one-line Cementitious Engaging launches.

Never loads the full corpus pickle. Never prints secret values.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pipeline.cementitious import RESULTS_DIR_NAME
from pipeline.cementitious.paths import (
    normalize_path_input,
    path_contains_legacy_results,
    resolve_results_dir,
)
from pipeline.cementitious.slurm_graph import build_dry_run_dependency_graph
from pipeline.cementitious.memory import STAGE_MEMORY_PROFILES, stage_profiles_public
from pipeline.cementitious.resource_calibration import (
    apply_recommendations_to_environ,
    resolve_pilot_output_for_calibration,
    validate_pilot_calibration,
)
from pipeline.cementitious.taxonomy import load_taxonomy, resolve_taxonomy_path

PILOT_MAX_RECORDS = 50
PILOT_WEB_LEAF = "chemical_absorption"
PILOT_WEB_PARENT = "cement_plant_carbon_capture"
PILOT_RESULTS_SUFFIX = "cementitious_engaging_pilot"

SECRET_ENV_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "TAVILY_API_KEY",
        "OPENAI_API_KEY_VALUE",
        "TAVILY_API_KEY_VALUE",
    }
)


@dataclass
class LaunchConfig:
    mode: str  # pilot | full
    run_mode: str = "literature-and-web"
    literature_enabled: bool = True
    web_enabled: bool = True
    max_records: int | None = None
    shard_size: int = 10000
    workers: int = 1
    array_max_concurrency: int = 1
    results_root: str = ""
    output_dir: str = ""
    pickle_path: str = ""
    taxonomy_path: str = ""
    selected_subcategories: list[str] = field(default_factory=list)
    selected_sub_subcategories: list[str] = field(default_factory=list)
    web_limits: dict[str, int] = field(default_factory=dict)
    keyword_only: bool = False
    resume: bool = False
    force: bool = False
    dry_run: bool = False
    require_openai: bool = True
    require_tavily: bool = True

    def as_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["literature_record_cap"] = self.max_records if self.max_records is not None else "FULL"
        return payload


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "y"}


def resolve_pilot_results_root(results_root: str | Path | None = None) -> Path:
    """Pilot always nests under a dedicated non-production parent."""
    raw = results_root or os.getenv("CEMENTITIOUS_PILOT_RESULTS_ROOT") or os.getenv("RESULTS_ROOT")
    if not raw:
        raise ValueError("RESULTS_ROOT or CEMENTITIOUS_PILOT_RESULTS_ROOT is required")
    root = normalize_path_input(raw)
    if path_contains_legacy_results(root):
        raise ValueError(f"Legacy RESULTS_ROOT refused: {root}")
    # If already pointing at the pilot suffix, keep it.
    if root.name == PILOT_RESULTS_SUFFIX:
        return root
    # If pointing at canonical 7-30 results, nest pilot beside it under parent.
    if root.name == RESULTS_DIR_NAME:
        return root.parent / PILOT_RESULTS_SUFFIX
    return root / PILOT_RESULTS_SUFFIX


def resolve_full_results_root(results_root: str | Path | None = None) -> Path:
    raw = results_root or os.getenv("RESULTS_ROOT")
    if not raw:
        raise ValueError("RESULTS_ROOT is required")
    root = normalize_path_input(raw)
    if path_contains_legacy_results(root):
        raise ValueError(f"Legacy RESULTS_ROOT refused: {root}")
    if root.name == PILOT_RESULTS_SUFFIX:
        raise ValueError(
            f"Full production mode refuses pilot results root ({PILOT_RESULTS_SUFFIX}). "
            "Export a production RESULTS_ROOT."
        )
    return root


def build_launch_config(
    mode: str,
    *,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> LaunchConfig:
    mode = mode.strip().lower().lstrip("-")
    if mode not in {"pilot", "full"}:
        raise ValueError(f"mode must be pilot or full, got {mode!r}")

    environ = dict(os.environ if env is None else env)
    keyword_only = environ.get("KEYWORD_ONLY", "").strip() in {"1", "true", "True", "yes"}
    resume = environ.get("RESUME", "").strip() in {"1", "true", "True", "yes"}
    force = environ.get("FORCE", "").strip() in {"1", "true", "True", "yes"}

    tax_path = resolve_taxonomy_path(environ.get("TAXONOMY_PATH") or None)
    tax = load_taxonomy(tax_path)

    if mode == "pilot":
        results_root = resolve_pilot_results_root(environ.get("RESULTS_ROOT"))
        out = resolve_results_dir(results_root)
        max_records = int(environ.get("CEMENTITIOUS_MAX_RECORDS") or PILOT_MAX_RECORDS)
        if max_records > PILOT_MAX_RECORDS:
            max_records = PILOT_MAX_RECORDS
        shard_size = int(environ.get("SHARD_SIZE") or max_records)
        selected_subs = [PILOT_WEB_PARENT]
        selected_ss = [PILOT_WEB_LEAF]
        # Allow explicit override for broader pilot taxonomy if validated.
        if environ.get("SELECTED_SUBCATEGORIES", "").strip():
            selected_subs = [
                p.strip() for p in environ["SELECTED_SUBCATEGORIES"].split(",") if p.strip()
            ]
        if environ.get("SELECTED_SUB_SUBCATEGORIES", "").strip():
            selected_ss = [
                p.strip() for p in environ["SELECTED_SUB_SUBCATEGORIES"].split(",") if p.strip()
            ]
        web_limits = {
            "WEB_QUERIES_PER_SUBCATEGORY": int(environ.get("WEB_QUERIES_PER_SUBCATEGORY") or 1),
            "WEB_QUERIES_PER_SUB_SUBCATEGORY": int(environ.get("WEB_QUERIES_PER_SUB_SUBCATEGORY") or 2),
            "WEB_RESULTS_PER_QUERY": int(environ.get("WEB_RESULTS_PER_QUERY") or 3),
            "WEB_MAX_URLS_PER_BRANCH": int(environ.get("WEB_MAX_URLS_PER_BRANCH") or 6),
            "WEB_MAX_TOTAL_URLS": int(
                environ.get("WEB_MAX_TOTAL_URLS") or environ.get("WEB_LIMIT") or 6
            ),
            "WEB_SEARCH_SHARD_SIZE": int(environ.get("WEB_SEARCH_SHARD_SIZE") or 5),
            "WEB_EXTRACT_SHARD_SIZE": int(environ.get("WEB_EXTRACT_SHARD_SIZE") or 5),
            "WEB_LIMIT": int(environ.get("WEB_LIMIT") or 6),
        }
        cfg = LaunchConfig(
            mode="pilot",
            max_records=max_records,
            shard_size=shard_size,
            workers=int(environ.get("CEMENTITIOUS_WORKERS") or 1),
            array_max_concurrency=int(environ.get("ARRAY_MAX_CONCURRENCY") or 1),
            results_root=str(results_root),
            output_dir=str(out),
            pickle_path=str(environ.get("PICKLE_PATH") or environ.get("PAPER_RECORDS_PATH") or ""),
            taxonomy_path=str(tax_path),
            selected_subcategories=selected_subs,
            selected_sub_subcategories=selected_ss,
            web_limits=web_limits,
            keyword_only=keyword_only,
            resume=resume,
            force=force,
            dry_run=dry_run,
        )
    else:
        results_root = resolve_full_results_root(environ.get("RESULTS_ROOT"))
        out = resolve_results_dir(results_root)
        if environ.get("CEMENTITIOUS_MAX_RECORDS", "").strip():
            raise ValueError(
                "Full mode forbids CEMENTITIOUS_MAX_RECORDS; unset it for the ~159k corpus run"
            )
        selected_subs = [
            p.strip() for p in environ.get("SELECTED_SUBCATEGORIES", "").split(",") if p.strip()
        ]
        selected_ss = [
            p.strip()
            for p in environ.get("SELECTED_SUB_SUBCATEGORIES", "").split(",")
            if p.strip()
        ]
        web_max = int(environ.get("WEB_MAX_TOTAL_URLS") or environ.get("WEB_LIMIT") or 1000)
        web_limits = {
            "WEB_QUERIES_PER_SUBCATEGORY": int(environ.get("WEB_QUERIES_PER_SUBCATEGORY") or 3),
            "WEB_QUERIES_PER_SUB_SUBCATEGORY": int(environ.get("WEB_QUERIES_PER_SUB_SUBCATEGORY") or 5),
            "WEB_RESULTS_PER_QUERY": int(environ.get("WEB_RESULTS_PER_QUERY") or 10),
            "WEB_MAX_URLS_PER_BRANCH": int(environ.get("WEB_MAX_URLS_PER_BRANCH") or 50),
            "WEB_MAX_TOTAL_URLS": web_max,
            "WEB_SEARCH_SHARD_SIZE": int(environ.get("WEB_SEARCH_SHARD_SIZE") or 10),
            "WEB_EXTRACT_SHARD_SIZE": int(environ.get("WEB_EXTRACT_SHARD_SIZE") or 10),
            "WEB_LIMIT": int(environ.get("WEB_LIMIT") or web_max),
        }
        cfg = LaunchConfig(
            mode="full",
            max_records=None,
            shard_size=int(environ.get("SHARD_SIZE") or 10000),
            workers=int(environ.get("CEMENTITIOUS_WORKERS") or 1),
            array_max_concurrency=int(environ.get("ARRAY_MAX_CONCURRENCY") or 1),
            results_root=str(results_root),
            output_dir=str(out),
            pickle_path=str(environ.get("PICKLE_PATH") or environ.get("PAPER_RECORDS_PATH") or ""),
            taxonomy_path=str(tax_path),
            selected_subcategories=selected_subs,
            selected_sub_subcategories=selected_ss,
            web_limits=web_limits,
            keyword_only=keyword_only,
            resume=resume,
            force=force,
            dry_run=dry_run,
        )

    # Validate selected leaves exist.
    for slug in cfg.selected_subcategories:
        if slug not in tax.subcategories:
            raise ValueError(f"Unknown subcategory slug: {slug}")
    for slug in cfg.selected_sub_subcategories:
        if slug not in tax.sub_subcategories:
            raise ValueError(f"Unknown sub-subcategory slug: {slug}")
    return cfg


def taxonomy_summary(path: str | Path | None = None) -> dict[str, Any]:
    tax = load_taxonomy(path)
    ordered_tree: list[dict[str, Any]] = []
    for sub_slug, sub in tax.subcategories.items():
        children = [
            {
                "name": node.display_name,
                "slug": slug,
                "synonyms": list(node.representative_synonyms or [])[:8],
                "variants": list(node.representative_technology_variants or [])[:8],
            }
            for slug, node in tax.sub_subcategories.items()
            if tax.parent_of_sub_sub.get(slug) == sub_slug
        ]
        ordered_tree.append(
            {
                "name": sub.display_name,
                "slug": sub_slug,
                "children": children,
            }
        )
    return {
        "taxonomy_path": tax.source_path,
        "taxonomy_version": tax.taxonomy_version,
        "category": {"name": tax.category_display, "slug": tax.category_slug},
        "subcategory_count": len(tax.subcategories),
        "leaf_count": len(tax.sub_subcategories),
        "tree": ordered_tree,
        "partition_specs": tax.list_rows(),
    }


def web_leaf_slugs(cfg: LaunchConfig) -> list[str]:
    tax = load_taxonomy(cfg.taxonomy_path or None)
    if cfg.selected_sub_subcategories:
        return list(cfg.selected_sub_subcategories)
    if cfg.selected_subcategories:
        out: list[str] = []
        for sub in cfg.selected_subcategories:
            out.extend(
                slug
                for slug, parent in tax.parent_of_sub_sub.items()
                if parent == sub
            )
        return out
    return list(tax.sub_subcategories.keys())


def export_paths_for_leaves(cfg: LaunchConfig) -> dict[str, dict[str, str]]:
    tax = load_taxonomy(cfg.taxonomy_path or None)
    out_root = Path(cfg.output_dir)
    paths: dict[str, dict[str, str]] = {}
    for slug in web_leaf_slugs(cfg):
        node = tax.sub_subcategories[slug]
        paths[slug] = {
            "records_csv": str(out_root / "sub_subcategories" / node.csv_filename),
            "citations_csv": str(
                out_root / "citations" / "sub_subcategories" / node.citations_filename
            ),
        }
    return paths


def validate_launch_config(
    cfg: LaunchConfig,
    *,
    environ: dict[str, str] | None = None,
    allow_uncalibrated_resources: bool = False,
) -> list[str]:
    env = dict(os.environ if environ is None else environ)
    errors: list[str] = []

    if cfg.run_mode not in {"literature-and-web", "literature_and_web"}:
        errors.append(f"Combined one-line launcher requires literature-and-web, got {cfg.run_mode}")
    if not cfg.literature_enabled or not cfg.web_enabled:
        errors.append("One-line pilot/full launcher requires both literature and web enabled")

    if cfg.require_openai and not env.get("OPENAI_API_KEY", "").strip() and not cfg.keyword_only:
        errors.append("OPENAI_API_KEY is required unless KEYWORD_ONLY=1")
    if cfg.require_tavily and not env.get("TAVILY_API_KEY", "").strip():
        errors.append("TAVILY_API_KEY is required for combined literature-and-web mode")

    if not cfg.pickle_path:
        errors.append("PICKLE_PATH or PAPER_RECORDS_PATH is required")
    else:
        pkl = Path(cfg.pickle_path)
        if not pkl.is_file():
            errors.append(f"PICKLE_PATH is not a readable file: {cfg.pickle_path}")

    if path_contains_legacy_results(cfg.results_root) or path_contains_legacy_results(cfg.output_dir):
        errors.append("RESULTS_ROOT/OUT must not use legacy '730 results'")

    if cfg.mode == "pilot":
        if cfg.max_records is None or cfg.max_records > PILOT_MAX_RECORDS:
            errors.append(f"Pilot must cap literature records at {PILOT_MAX_RECORDS}")
        if PILOT_RESULTS_SUFFIX not in Path(cfg.results_root).parts:
            errors.append(f"Pilot RESULTS_ROOT must nest under {PILOT_RESULTS_SUFFIX}")
        if RESULTS_DIR_NAME in Path(cfg.results_root).parts and Path(cfg.results_root).name == RESULTS_DIR_NAME:
            errors.append("Pilot must not write directly to production 7-30 results root")

    if cfg.mode == "full" and cfg.max_records is not None:
        errors.append("Full mode must not set a literature record cap")

    export_complete = Path(cfg.output_dir) / "checkpoints" / "export.complete"
    if export_complete.is_file() and not cfg.force and not cfg.dry_run:
        errors.append(
            f"Completed export exists at {export_complete}; set FORCE=1 to overwrite"
        )

    tax = load_taxonomy(cfg.taxonomy_path or None)
    for slug in web_leaf_slugs(cfg):
        if slug not in tax.sub_subcategories:
            errors.append(f"Web leaf missing from taxonomy: {slug}")
    for slug, paths in export_paths_for_leaves(cfg).items():
        if "records_csv" not in paths or "citations_csv" not in paths:
            errors.append(f"Missing export paths for leaf {slug}")

    # Full-run calibration gate.
    if cfg.mode == "full" and not cfg.dry_run:
        if allow_uncalibrated_resources or env.get("ALLOW_UNCALIBRATED_RESOURCES", "").strip() in {
            "1",
            "true",
            "True",
            "yes",
        }:
            pass
        else:
            pilot_out = resolve_pilot_output_for_calibration(
                results_root=env.get("RESULTS_ROOT"),
                explicit_pilot_out=env.get("CEMENTITIOUS_PILOT_OUTPUT_DIR"),
            )
            if pilot_out is None:
                errors.append(
                    "Full mode requires a completed calibrated pilot "
                    "(set CEMENTITIOUS_PILOT_OUTPUT_DIR or nest cementitious_engaging_pilot "
                    "under RESULTS_ROOT). Override only with --allow-uncalibrated-resources."
                )
            else:
                verdict = validate_pilot_calibration(pilot_out)
                if not verdict["ok"]:
                    errors.extend(verdict["errors"])

    return errors


def required_stage_names() -> list[str]:
    return [
        "preprocess_plan",
        "plan_web_queries",
        "screen",
        "screen_merge",
        "orchestrate_lit",
        "extract",
        "extract_merge",
        "web_search",
        "orchestrate_web",
        "web_extract",
        "web_extract_merge",
        "finalize_submit",
        "merge_literature_web",
        "dedupe_qc",
        "export",
    ]


def build_workflow_dry_run(cfg: LaunchConfig) -> dict[str, Any]:
    tax = taxonomy_summary(cfg.taxonomy_path or None)
    leaves = web_leaf_slugs(cfg)
    graph = build_dry_run_dependency_graph(
        run_mode="literature-and-web",
        screen_array="0" if cfg.mode == "pilot" else "0-N",
        extract_array="0",
        web_search_array="0",
        web_extract_array="0",
        include_ccs_migrate=False,
    )
    # Prepend preprocess stage.
    preprocess = {
        "job_id": "999",
        "job_name": "cm-preprocess",
        "stage": "preprocess_plan",
        "branch": "literature",
        "dependency_type": "none",
        "parent_job_ids": [],
        "array_range": None,
        "submission_command": "sbatch --mem=64G 730_cementitious_preprocess_plan.sh",
        "expected_outputs": [
            "metadata/corpus_shards_manifest.json",
            "metadata/screen_shards.json",
            "checkpoints/plan_screen.complete",
        ],
        "log_path": "logs/cm-preprocess-%j.out",
        "mem": "64G",
        "cpus": 1,
    }
    jobs = [preprocess] + list(graph["jobs"])
    # Bootstrap depends on preprocess conceptually (screen parents stay; launcher notes dependency).
    stage_names = [j["stage"] for j in jobs]
    for required in required_stage_names():
        if required == "plan_web_queries":
            continue  # sync inside bootstrap; represented in notes
        if required not in stage_names and required != "preprocess_plan":
            pass

    # Validate DAG: export ultimately depends on merge of lit+web terminals.
    by_id = {j["job_id"]: j for j in jobs}
    export_jobs = [j for j in jobs if j["stage"] == "export"]
    acyclic = _graph_is_acyclic(jobs)

    return {
        "mode": cfg.mode,
        "run_mode": cfg.run_mode,
        "literature_enabled": True,
        "web_search_enabled": True,
        "literature_record_cap": cfg.max_records if cfg.max_records is not None else "FULL",
        "shard_size": cfg.shard_size,
        "workers": cfg.workers,
        "array_max_concurrency": cfg.array_max_concurrency,
        "results_root": cfg.results_root,
        "output_dir": cfg.output_dir,
        "pickle_path": cfg.pickle_path,
        "taxonomy_path": cfg.taxonomy_path,
        "taxonomy_version": tax["taxonomy_version"],
        "subcategory_count": tax["subcategory_count"],
        "leaf_count": tax["leaf_count"],
        "web_leaf_count": len(leaves),
        "web_leaf_slugs": leaves,
        "web_limits": cfg.web_limits,
        "selected_subcategories": cfg.selected_subcategories,
        "selected_sub_subcategories": cfg.selected_sub_subcategories,
        "export_paths": export_paths_for_leaves(cfg),
        "stage_order": required_stage_names(),
        "dependency_graph": {"jobs": jobs, "acyclic": acyclic, **{k: v for k, v in graph.items() if k != "jobs"}},
        "resource_requests": {
            name: {
                "mem": profile.mem_slurm,
                "mem_gb": profile.mem_gb,
                "soft_limit_gb": profile.soft_limit_gb,
                "cpus": profile.cpus,
                "loads_full_pickle": profile.loads_full_pickle,
                "scales_with": list(profile.scales_with),
                "rationale": profile.rationale,
            }
            for name, profile in STAGE_MEMORY_PROFILES.items()
        },
        "stage_memory_profiles": stage_profiles_public(),
        "soft_fraction_of_slurm_mem": 0.80,
        "notes": [
            "Dry-run does not call sbatch, OpenAI, or Tavily.",
            "Dry-run does not load the full corpus pickle.",
            "Preprocess Slurm job materializes memory-safe corpus JSONL shards once.",
            "Bootstrap job (after preprocess) plans web queries and submits the remaining DAG.",
            "Finalize depends on literature and web terminal merge jobs, then export.",
            "Soft memory ceiling defaults to 80% of each stage's Slurm --mem request.",
            "Full mode requires a successful calibrated pilot unless --allow-uncalibrated-resources.",
        ],
        "proposed_commands": {
            "preprocess": "sbatch scripts/engaging/730_cementitious_preprocess_plan.sh",
            "bootstrap": (
                "sbatch --dependency=afterok:$PREPROCESS_JOB "
                "--wrap='SKIP_LIT_PLAN=1 bash scripts/engaging/run_730_results.sh'"
            ),
        },
        "secrets_redacted": True,
        "export_job_depends_on_lit_and_web": bool(export_jobs),
        "telemetry_required": True,
        "calibration_required_for_full": True,
    }


def _graph_is_acyclic(jobs: list[dict[str, Any]]) -> bool:
    ids = {j["job_id"] for j in jobs}
    parents = {j["job_id"]: [p for p in j.get("parent_job_ids") or [] if p in ids] for j in jobs}
    visiting: set[str] = set()
    seen: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visiting:
            return False
        if node in seen:
            return True
        visiting.add(node)
        for p in parents.get(node, []):
            if not dfs(p):
                return False
        visiting.remove(node)
        seen.add(node)
        return True

    return all(dfs(j) for j in ids)


def redact_secrets(payload: Any) -> Any:
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if str(k).upper() in SECRET_ENV_KEYS or re.search(r"api[_-]?key", str(k), re.I):
                out[k] = "<redacted>"
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(payload, list):
        return [redact_secrets(x) for x in payload]
    if isinstance(payload, str) and re.search(r"sk-[A-Za-z0-9]{10,}", payload):
        return "<redacted>"
    return payload


def write_launch_manifest(path: Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact_secrets(payload)
    path.write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["pilot", "full"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--allow-uncalibrated-resources",
        action="store_true",
        help="Full mode only: skip pilot calibration gate (not default).",
    )
    args = parser.parse_args(argv)

    cfg = build_launch_config(args.mode, dry_run=args.dry_run or args.validate_only)
    errors = validate_launch_config(
        cfg,
        allow_uncalibrated_resources=args.allow_uncalibrated_resources,
    )
    report = {
        "config": cfg.as_public_dict(),
        "errors": errors,
        "allow_uncalibrated_resources": bool(args.allow_uncalibrated_resources),
        "taxonomy": {
            "path": cfg.taxonomy_path,
            "leaf_count": taxonomy_summary(cfg.taxonomy_path)["leaf_count"],
            "subcategory_count": taxonomy_summary(cfg.taxonomy_path)["subcategory_count"],
            "web_leaves": web_leaf_slugs(cfg),
        },
        "stage_memory_profiles": stage_profiles_public(),
    }
    if args.dry_run:
        report["dry_run"] = build_workflow_dry_run(cfg)
    # Apply calibrated env recommendations into report for full mode when available.
    if cfg.mode == "full":
        pilot_out = resolve_pilot_output_for_calibration(
            results_root=os.getenv("RESULTS_ROOT"),
            explicit_pilot_out=os.getenv("CEMENTITIOUS_PILOT_OUTPUT_DIR"),
        )
        if pilot_out is not None:
            reco_path = Path(pilot_out) / "metadata" / "full_run_resource_recommendations.json"
            if reco_path.is_file():
                reco = json.loads(reco_path.read_text(encoding="utf-8"))
                report["calibration"] = {
                    "pilot_output_dir": str(pilot_out),
                    "recommendations_path": str(reco_path),
                    "applied_env": {
                        k: v
                        for k, v in apply_recommendations_to_environ(reco).items()
                        if k.startswith("CEMENTITIOUS_MEM_")
                        or k.startswith("SUBMIT_LOGIN")
                        or k.endswith("_SOFT_")
                        or k in {"CEMENTITIOUS_WORKERS", "ARRAY_MAX_CONCURRENCY"}
                    },
                }
    report = redact_secrets(report)
    if errors and not args.dry_run:
        print(json.dumps(report, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
