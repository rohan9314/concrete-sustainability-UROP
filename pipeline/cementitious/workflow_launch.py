"""Preflight and dry-run helpers for one-line Concrete Decarbonization Engaging launches.

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
    ESTIMATED_FULL_CORPUS_RECORDS,
    FULL_SHARD_SIZE_DEFAULT,
)
from pipeline.cementitious.taxonomy import load_taxonomy, resolve_taxonomy_path

PILOT_MAX_RECORDS = 50
PILOT_50_MAX_RECORDS = 50
PILOT_1000_MAX_RECORDS = 1000
PILOT_WEB_LEAF = "chemical_absorption"
PILOT_WEB_PARENT = "cement_plant_carbon_capture"
# Legacy smoke (--pilot) nests here. Full-taxonomy pilots use dedicated slugs.
PILOT_RESULTS_SUFFIX = "cementitious_engaging_pilot"
PILOT_50_RESULTS_SUFFIX = "concrete_decarbonization_pilot_50"
PILOT_1000_RESULTS_SUFFIX = "concrete_decarbonization_pilot_1000"
ALL_PILOT_RESULTS_SUFFIXES = frozenset(
    {PILOT_RESULTS_SUFFIX, PILOT_50_RESULTS_SUFFIX, PILOT_1000_RESULTS_SUFFIX}
)
# Unambiguous production nest. Hierarchical CSVs still live under
# ``{output_dir}/concrete_decarbonization_results/`` (L0–L4 tree).
FULL_RESULTS_SUFFIX = "concrete_decarbonization_full_run"
# Also accept the user-facing two-level form: .../concrete_decarbonization_results/full_run
FULL_RESULTS_ALT_PARENT = "concrete_decarbonization_results"
FULL_RESULTS_ALT_SUFFIX = "full_run"
CANONICAL_LAUNCHER = "scripts/engaging/run_concrete_decarbonization_full_workflow.sh"
COMPAT_LAUNCHER = "scripts/engaging/run_cementitious_full_workflow.sh"
# Default --pilot taxonomy scope is a cheap single-branch smoke restriction.
# --pilot-50 / --pilot-1000 always use the full canonical taxonomy unless the
# user explicitly sets SELECTED_SUBCATEGORIES / SELECTED_SUB_SUBCATEGORIES.
PILOT_TAXONOMY_SCOPE_SMOKE = "smoke"
PILOT_TAXONOMY_SCOPE_ALL = "all"
DEFAULT_SAMPLE_SEED = 42
SMOKE_LAUNCH_MODE = "pilot"
PILOT_50_LAUNCH_MODE = "pilot-50"
PILOT_1000_LAUNCH_MODE = "pilot-1000"
FULL_LAUNCH_MODE = "full"
FULL_SHARD_SIZE = FULL_SHARD_SIZE_DEFAULT
FULL_WORKERS = 1
FULL_ARRAY_MAX_CONCURRENCY = 1
FULL_TAXONOMY_PILOT_MODES = frozenset({PILOT_50_LAUNCH_MODE, PILOT_1000_LAUNCH_MODE})
ALL_PILOT_LAUNCH_MODES = frozenset({SMOKE_LAUNCH_MODE}) | FULL_TAXONOMY_PILOT_MODES
LAUNCH_MODES = frozenset(ALL_PILOT_LAUNCH_MODES | {FULL_LAUNCH_MODE})
MODE_ALIASES = {
    "pilot": SMOKE_LAUNCH_MODE,
    "smoke": SMOKE_LAUNCH_MODE,
    "pilot-smoke": SMOKE_LAUNCH_MODE,
    "pilot-50": PILOT_50_LAUNCH_MODE,
    "pilot50": PILOT_50_LAUNCH_MODE,
    "p50": PILOT_50_LAUNCH_MODE,
    "pilot-1000": PILOT_1000_LAUNCH_MODE,
    "pilot1000": PILOT_1000_LAUNCH_MODE,
    "p1000": PILOT_1000_LAUNCH_MODE,
    "full": FULL_LAUNCH_MODE,
}

# Conservative Tavily *depth* caps. Query planner always covers every searchable
# Level-4 node; WEB_MAX_TOTAL_QUERIES must not drop branches. Cap per-node query
# count and retained URL depth instead.
PILOT_50_WEB_DEFAULTS: dict[str, int | float] = {
    "WEB_QUERIES_PER_SUBCATEGORY": 1,
    "WEB_QUERIES_PER_SUB_SUBCATEGORY": 1,
    "WEB_QUERIES_PER_NODE": 1,
    "WEB_RESULTS_PER_QUERY": 2,
    "WEB_MAX_URLS_PER_BRANCH": 3,
    "WEB_MAX_TOTAL_URLS": 900,
    "WEB_LIMIT": 900,
    "WEB_MAX_TOTAL_QUERIES": 0,
    "WEB_SEARCH_SHARD_SIZE": 25,
    "WEB_EXTRACT_SHARD_SIZE": 25,
    "WEB_CONCURRENCY": 1,
    "WEB_RATE_LIMIT_SLEEP_S": 0,
}
PILOT_1000_WEB_DEFAULTS: dict[str, int | float] = {
    "WEB_QUERIES_PER_SUBCATEGORY": 1,
    "WEB_QUERIES_PER_SUB_SUBCATEGORY": 2,
    "WEB_QUERIES_PER_NODE": 2,
    "WEB_RESULTS_PER_QUERY": 3,
    "WEB_MAX_URLS_PER_BRANCH": 6,
    "WEB_MAX_TOTAL_URLS": 2000,
    "WEB_LIMIT": 2000,
    "WEB_MAX_TOTAL_QUERIES": 0,
    "WEB_SEARCH_SHARD_SIZE": 25,
    "WEB_EXTRACT_SHARD_SIZE": 25,
    "WEB_CONCURRENCY": 2,
    "WEB_RATE_LIMIT_SLEEP_S": 0,
}
SMOKE_WEB_DEFAULTS: dict[str, int | float] = {
    "WEB_QUERIES_PER_SUBCATEGORY": 1,
    "WEB_QUERIES_PER_SUB_SUBCATEGORY": 2,
    "WEB_QUERIES_PER_NODE": 2,
    "WEB_RESULTS_PER_QUERY": 3,
    "WEB_MAX_URLS_PER_BRANCH": 6,
    "WEB_MAX_TOTAL_URLS": 6,
    "WEB_LIMIT": 6,
    "WEB_MAX_TOTAL_QUERIES": 12,
    "WEB_SEARCH_SHARD_SIZE": 5,
    "WEB_EXTRACT_SHARD_SIZE": 5,
    "WEB_CONCURRENCY": 1,
    "WEB_RATE_LIMIT_SLEEP_S": 0,
}

REQUIRED_ENGAGING_SCRIPTS = (
    CANONICAL_LAUNCHER,
    COMPAT_LAUNCHER,
    "scripts/engaging/730_cementitious_preprocess_plan.sh",
    "scripts/engaging/run_730_results.sh",
)

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
    mode: str  # pilot (smoke) | pilot-50 | pilot-1000 | full
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
    web_limits: dict[str, int | float] = field(default_factory=dict)
    keyword_only: bool = False
    resume: bool = False
    force: bool = False
    dry_run: bool = False
    require_openai: bool = True
    require_tavily: bool = True
    # Pilot-only: corpus sampling (record cap) vs taxonomy restriction are distinct.
    pilot_corpus_sampling: bool = False
    pilot_taxonomy_scope: str = ""  # smoke | all | "" (full mode)
    web_search_scope: str = "canonical"
    require_literature: bool = True
    sample_seed: int | None = None
    results_suffix: str = ""
    telemetry_enabled: bool = True
    hierarchical_export_enabled: bool = True

    def as_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["literature_record_cap"] = self.max_records if self.max_records is not None else "FULL"
        payload["pilot_behavior"] = {
            "corpus_sampling": {
                "enabled": bool(self.pilot_corpus_sampling),
                "literature_record_cap": self.max_records if self.max_records is not None else "FULL",
                "description": (
                    "Caps how many literature records are processed. "
                    "This does not by itself restrict the taxonomy."
                ),
            },
            "taxonomy_restriction": {
                "enabled": bool(self.selected_subcategories or self.selected_sub_subcategories),
                "scope": self.pilot_taxonomy_scope
                or ("restricted" if self.selected_subcategories else "all"),
                "selected_subcategories": list(self.selected_subcategories),
                "selected_sub_subcategories": list(self.selected_sub_subcategories),
                "description": (
                    "smoke: restrict screening/web/export taxonomy to one branch "
                    f"({PILOT_WEB_PARENT} / {PILOT_WEB_LEAF}) for a cheap test. "
                    "all: exercise the full taxonomy while still applying the record cap. "
                    "Set CEMENTITIOUS_PILOT_TAXONOMY_SCOPE=all to disable the smoke restriction. "
                    "Explicit SELECTED_SUBCATEGORIES / SELECTED_SUB_SUBCATEGORIES still win."
                ),
            },
        }
        payload["web_search_scope"] = self.web_search_scope
        payload["literature_enabled"] = self.literature_enabled
        payload["web_enabled"] = self.web_enabled
        payload["sample_seed"] = self.sample_seed
        payload["results_suffix"] = self.results_suffix
        payload["telemetry_enabled"] = self.telemetry_enabled
        payload["hierarchical_export_enabled"] = self.hierarchical_export_enabled
        payload["taxonomy_restriction"] = taxonomy_restriction_text(self)
        payload["taxonomy_scope"] = taxonomy_scope_label(self)
        payload["literature_taxonomy"] = (
            "runtime"
            if self.selected_subcategories or self.selected_sub_subcategories
            else "canonical"
        )
        payload["literature_record_cap_display"] = (
            "NONE / FULL CORPUS" if self.max_records is None else str(self.max_records)
        )
        payload["export_complete_path"] = str(
            Path(self.output_dir) / "checkpoints" / "export.complete"
        )
        payload["canonical_export_root"] = str(
            Path(self.output_dir) / "concrete_decarbonization_results"
        )
        payload["launch_metadata"] = build_launch_metadata(self)
        payload["pilot_profile"] = (
            "smoke"
            if self.mode == SMOKE_LAUNCH_MODE
            else (
                "50"
                if self.mode == PILOT_50_LAUNCH_MODE
                else ("1000" if self.mode == PILOT_1000_LAUNCH_MODE else "")
            )
        )
        return payload


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "y"}


def _optional_bool(environ: dict[str, str], *names: str) -> bool | None:
    for name in names:
        raw = environ.get(name)
        if raw is None or str(raw).strip() == "":
            continue
        return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}
    return None


def resolve_run_mode_flags(environ: dict[str, str]) -> tuple[str, bool, bool]:
    """Return (run_mode, literature_enabled, web_enabled).

    Full/pilot default is literature-and-web. Explicit RUN_MODE or
    LITERATURE_ENABLED / WEB_SEARCH_ENABLED overrides. A missing Tavily key
    never silently flips web off; preflight must fail instead.
    """
    literature_enabled = True
    web_enabled = True
    raw_mode = (environ.get("RUN_MODE") or "literature-and-web").strip().lower().replace("_", "-")
    lit_flag = _optional_bool(environ, "LITERATURE_ENABLED")
    web_flag = _optional_bool(environ, "WEB_SEARCH_ENABLED", "WEB_ENABLED")
    if raw_mode in {"literature-only"}:
        web_enabled = False
    elif raw_mode in {"web-only"}:
        literature_enabled = False
    elif raw_mode not in {"literature-and-web", "literature-and-web".replace(" ", "")}:
        if raw_mode not in {"", "pilot", "full"}:
            # Unknown mode names still default to combined unless flags say otherwise.
            pass
    if lit_flag is False:
        literature_enabled = False
    elif lit_flag is True:
        literature_enabled = True
    if web_flag is False:
        web_enabled = False
    elif web_flag is True:
        web_enabled = True
    if not literature_enabled and not web_enabled:
        raise ValueError("At least one of literature or web retrieval must be enabled")
    if literature_enabled and web_enabled:
        run_mode = "literature-and-web"
    elif literature_enabled:
        run_mode = "literature-only"
    else:
        run_mode = "web-only"
    return run_mode, literature_enabled, web_enabled


def normalize_launch_mode(mode: str) -> str:
    raw = (mode or "").strip().lower().lstrip("-").replace("_", "-")
    if raw not in MODE_ALIASES:
        raise ValueError(
            "mode must be pilot (smoke), --pilot-50, --pilot-1000, or full, "
            f"got {mode!r}"
        )
    return MODE_ALIASES[raw]


def is_pilot_launch_mode(mode: str) -> bool:
    return mode in ALL_PILOT_LAUNCH_MODES


def is_resolved_full_results_root(root: Path | str) -> bool:
    path = Path(root)
    if path.name == FULL_RESULTS_SUFFIX:
        return True
    if path.name == FULL_RESULTS_ALT_SUFFIX and path.parent.name == FULL_RESULTS_ALT_PARENT:
        return True
    return False


def unwrap_results_root_for_calibration(root: Path | str | None) -> Path | None:
    """Walk from a nested full/pilot slug back to the shared RESULTS_ROOT parent."""
    if root is None:
        return None
    candidate = Path(root)
    if candidate.name == RESULTS_DIR_NAME:
        candidate = candidate.parent
    if is_resolved_full_results_root(candidate):
        if candidate.name == FULL_RESULTS_ALT_SUFFIX:
            return candidate.parent.parent
        return candidate.parent
    if candidate.name in ALL_PILOT_RESULTS_SUFFIXES:
        return candidate.parent
    return candidate


def taxonomy_scope_label(cfg: LaunchConfig) -> str:
    """``FULL`` when literature+web use the canonical Level 0–4 tree."""
    if taxonomy_restriction_text(cfg) != "NONE":
        if cfg.mode == SMOKE_LAUNCH_MODE:
            return "SMOKE"
        return "RESTRICTED"
    return "FULL"


def taxonomy_restriction_text(cfg: LaunchConfig) -> str:
    """Human-readable restriction; ``NONE`` when the full tree is in play."""
    parts: list[str] = []
    if cfg.selected_subcategories:
        parts.append("SELECTED_SUBCATEGORIES=" + ",".join(cfg.selected_subcategories))
    if cfg.selected_sub_subcategories:
        parts.append("SELECTED_SUB_SUBCATEGORIES=" + ",".join(cfg.selected_sub_subcategories))
    if (
        cfg.mode == SMOKE_LAUNCH_MODE
        and cfg.pilot_taxonomy_scope == PILOT_TAXONOMY_SCOPE_SMOKE
        and not parts
    ):
        parts.append(f"smoke branch {PILOT_WEB_PARENT}/{PILOT_WEB_LEAF}")
    if cfg.web_search_scope not in {"", "canonical"} and cfg.mode in {
        FULL_LAUNCH_MODE,
        *FULL_TAXONOMY_PILOT_MODES,
    }:
        parts.append(f"web_search_scope={cfg.web_search_scope}")
    return "; ".join(parts) if parts else "NONE"


def conceptual_dag_stages() -> list[str]:
    """User-facing one-line DAG (maps onto the existing Slurm dependency graph)."""
    return [
        "preflight",
        "preprocess/sharding",
        "literature screening",
        "literature extraction",
        "web retrieval",
        "web screening/extraction",
        "normalization",
        "canonical literature/web merge",
        "deduplication",
        "validation",
        "hierarchical export",
        "resource accounting",
        "final completion checkpoint (export.complete)",
    ]


def _profile_mem(profiles: dict[str, Any], stage: str) -> str:
    info = profiles.get(stage) or {}
    return str(info.get("mem_slurm") or info.get("mem") or "")


def render_preflight_summary(
    report: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
) -> str:
    """Printable preflight block. Never includes secret values."""
    env = dict(os.environ if environ is None else environ)
    cfg = report.get("config") or {}
    tax = report.get("taxonomy") or {}
    canon = tax.get("canonical") or {}
    dry = report.get("dry_run") or {}
    profiles = report.get("stage_memory_profiles") or dry.get("stage_memory_profiles") or {}
    mode = cfg.get("mode") or ""
    restriction = cfg.get("taxonomy_restriction") or dry.get("taxonomy_restriction") or "NONE"
    lit_cap = cfg.get("literature_record_cap_display")
    if not lit_cap:
        raw_cap = cfg.get("max_records")
        lit_cap = "NONE / FULL CORPUS" if raw_cap in (None, "", "FULL") else str(raw_cap)
    web_on = bool(cfg.get("web_enabled", True))
    lit_on = bool(cfg.get("literature_enabled", True))
    web_scope = dry.get("web_search_node_count") or len(tax.get("web_search_nodes") or [])
    web_limit = (cfg.get("web_limits") or {}).get("WEB_MAX_TOTAL_URLS") or (
        dry.get("web_limits") or {}
    ).get("WEB_MAX_TOTAL_URLS")
    estimated = dry.get("estimated_corpus_records")
    if mode == FULL_LAUNCH_MODE:
        title = "Concrete Decarbonization Full Workflow"
    elif mode == PILOT_50_LAUNCH_MODE:
        title = "Concrete Decarbonization Pilot-50 Workflow"
    elif mode == PILOT_1000_LAUNCH_MODE:
        title = "Concrete Decarbonization Pilot-1000 Workflow"
    else:
        title = "Concrete Decarbonization Smoke (--pilot) Workflow"
    openai_state = "set" if env.get("OPENAI_API_KEY", "").strip() else "unset"
    tavily_state = "set" if env.get("TAVILY_API_KEY", "").strip() else "unset"
    lines = [
        f"======== {title} ========",
        "",
        f"mode={mode}",
        f"run_mode={cfg.get('run_mode') or 'literature-and-web'}",
        "",
        f"literature_enabled={'yes' if lit_on else 'no'}",
        (
            "web_search_enabled=yes (Tavily)"
            if web_on
            else "web_search_enabled=no (explicitly disabled)"
        ),
        "",
        f"taxonomy_root={canon.get('taxonomy_root') or 'Concrete Decarbonization'}",
        "",
        f"taxonomy_level_1_nodes={canon.get('level_1_nodes', '')}",
        f"taxonomy_level_2_nodes={canon.get('level_2_nodes', '')}",
        f"taxonomy_level_3_nodes={canon.get('level_3_nodes', '')}",
        f"taxonomy_level_4_nodes={canon.get('level_4_nodes', '')}",
        f"taxonomy_total_nodes={canon.get('total_taxonomy_nodes', '')}",
        "",
        f"taxonomy_scope={cfg.get('taxonomy_scope') or dry.get('taxonomy_scope') or 'FULL'}",
        f"taxonomy_restriction={restriction}",
        f"literature_taxonomy={cfg.get('literature_taxonomy') or dry.get('literature_taxonomy') or 'canonical'}",
        "",
        f"literature_record_cap={lit_cap}",
        f"estimated_literature_records={estimated if estimated is not None else ''}",
        "",
        f"web_scope={web_scope}",
        f"web_searchable_nodes={canon.get('searchable_web_node_count') or web_scope}",
        f"web_result_limit={web_limit}",
        "",
        f"shard_size={cfg.get('shard_size', '')}",
        f"workers={cfg.get('workers', '')}",
        f"array_concurrency={cfg.get('array_max_concurrency', '')}",
        "",
        f"preprocess_mem={_profile_mem(profiles, 'preprocess_plan')}",
        f"worker_mem={_profile_mem(profiles, 'screen')}",
        f"finalize_mem={_profile_mem(profiles, 'export')}",
        "",
        f"RESULTS_ROOT={cfg.get('results_root', '')}",
        f"OUT={cfg.get('output_dir', '')}",
        "",
        f"OPENAI_API_KEY={openai_state}",
        f"TAVILY_API_KEY={tavily_state}",
        f"PICKLE_PATH={cfg.get('pickle_path', '')}",
        f"TAXONOMY_PATH={cfg.get('taxonomy_path', '')}",
        "",
        f"canonical_hierarchical_export={cfg.get('canonical_export_root') or ''}",
        f"export.complete will appear at: {cfg.get('export_complete_path') or ''}",
        "==========================================================",
    ]
    return "\n".join(lines)


def resolve_sample_seed(environ: dict[str, str]) -> int:
    raw = (
        environ.get("CEMENTITIOUS_SAMPLE_SEED")
        or environ.get("SAMPLE_SEED")
        or str(DEFAULT_SAMPLE_SEED)
    ).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid sample seed {raw!r}") from exc


def _int_env(environ: dict[str, str], key: str, default: int) -> int:
    raw = environ.get(key)
    if raw is None or str(raw).strip() == "":
        return int(default)
    return int(raw)


def _float_env(environ: dict[str, str], key: str, default: float) -> float:
    raw = environ.get(key)
    if raw is None or str(raw).strip() == "":
        return float(default)
    return float(raw)


def _web_limits_from_defaults(
    environ: dict[str, str],
    defaults: dict[str, int | float],
) -> dict[str, int | float]:
    out: dict[str, int | float] = {}
    for key, default in defaults.items():
        if isinstance(default, float) and not isinstance(default, bool):
            out[key] = _float_env(environ, key, float(default))
        else:
            out[key] = _int_env(environ, key, int(default))
    if "WEB_QUERIES_PER_NODE" not in environ or not str(environ.get("WEB_QUERIES_PER_NODE") or "").strip():
        out["WEB_QUERIES_PER_NODE"] = out.get(
            "WEB_QUERIES_PER_SUB_SUBCATEGORY", defaults.get("WEB_QUERIES_PER_NODE", 1)
        )
    if "WEB_LIMIT" not in environ or not str(environ.get("WEB_LIMIT") or "").strip():
        out["WEB_LIMIT"] = out.get("WEB_MAX_TOTAL_URLS", defaults.get("WEB_LIMIT", 0))
    return out


def canonical_taxonomy_counts() -> dict[str, Any]:
    from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy
    from pipeline.cementitious.web_scope import searchable_web_nodes

    tax = get_decarbonization_taxonomy()
    return {
        "taxonomy_root": tax.root().label,
        "taxonomy_version": tax.taxonomy_version,
        "taxonomy_source_path": tax.source_path,
        "level_0_nodes": tax.count(0),
        "level_1_nodes": tax.count(1),
        "level_2_nodes": tax.count(2),
        "level_3_nodes": tax.count(3),
        "level_4_nodes": tax.count(4),
        "total_taxonomy_nodes": tax.count(),
        "searchable_web_node_count": len(searchable_web_nodes(tax)),
    }


def _git_commit() -> str | None:
    try:
        import subprocess

        from pipeline.config import REPO_ROOT

        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip() or None
    except Exception:
        return None


def build_launch_metadata(cfg: LaunchConfig) -> dict[str, Any]:
    """Stable preflight/manifest fields for pilots and full mode."""
    from datetime import datetime, timezone

    counts = canonical_taxonomy_counts()
    return {
        "mode": cfg.mode,
        "literature_record_cap": cfg.max_records if cfg.max_records is not None else "FULL",
        "literature_enabled": cfg.literature_enabled,
        "web_enabled": cfg.web_enabled,
        "taxonomy_root": counts["taxonomy_root"],
        "taxonomy_version": counts["taxonomy_version"],
        "taxonomy_node_counts_by_level": {
            "level_0": counts["level_0_nodes"],
            "level_1": counts["level_1_nodes"],
            "level_2": counts["level_2_nodes"],
            "level_3": counts["level_3_nodes"],
            "level_4": counts["level_4_nodes"],
            "total": counts["total_taxonomy_nodes"],
        },
        "searchable_web_node_count": counts["searchable_web_node_count"],
        "web_result_caps": dict(cfg.web_limits),
        "random_seed": cfg.sample_seed,
        "shard_size": cfg.shard_size,
        "workers": cfg.workers,
        "concurrency": cfg.array_max_concurrency,
        "requested_slurm_resources": {
            name: {
                "mem": profile.mem_slurm,
                "mem_gb": profile.mem_gb,
                "cpus": profile.cpus,
                "soft_limit_gb": profile.soft_limit_gb,
            }
            for name, profile in STAGE_MEMORY_PROFILES.items()
        },
        "output_directory": cfg.output_dir,
        "results_root": cfg.results_root,
        "results_suffix": cfg.results_suffix,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "repository_commit_hash": _git_commit(),
        "telemetry_enabled": cfg.telemetry_enabled,
        "hierarchical_export_enabled": cfg.hierarchical_export_enabled,
        "pilot_taxonomy_scope": cfg.pilot_taxonomy_scope,
        "web_search_scope": cfg.web_search_scope,
    }


def resolve_pilot_taxonomy_scope(environ: dict[str, str] | None = None) -> str:
    """Return ``smoke`` (default for --pilot) or ``all``.

    ``smoke`` is a deliberate single-branch taxonomy restriction for a cheap
    Engaging test. It is not the same as corpus sampling (``CEMENTITIOUS_MAX_RECORDS``).
    ``--pilot`` remains the smoke launcher. ``--pilot-50`` / ``--pilot-1000``
    always start from ``all``.
    """
    env = dict(os.environ if environ is None else environ)
    raw = (env.get("CEMENTITIOUS_PILOT_TAXONOMY_SCOPE") or PILOT_TAXONOMY_SCOPE_SMOKE).strip().lower()
    if raw in {"all", "full", "unrestricted", "corpus_only"}:
        return PILOT_TAXONOMY_SCOPE_ALL
    if raw in {"smoke", "restricted", "single_branch", ""}:
        return PILOT_TAXONOMY_SCOPE_SMOKE
    raise ValueError(
        "CEMENTITIOUS_PILOT_TAXONOMY_SCOPE must be 'smoke' (default, one taxonomy branch) "
        f"or 'all' (full taxonomy + record cap), got {raw!r}"
    )


def resolve_pilot_results_root(
    results_root: str | Path | None = None,
    *,
    suffix: str = PILOT_RESULTS_SUFFIX,
) -> Path:
    """Pilot always nests under a dedicated non-production parent."""
    raw = results_root or os.getenv("CEMENTITIOUS_PILOT_RESULTS_ROOT") or os.getenv("RESULTS_ROOT")
    if not raw:
        raise ValueError("RESULTS_ROOT or CEMENTITIOUS_PILOT_RESULTS_ROOT is required")
    root = normalize_path_input(raw)
    if path_contains_legacy_results(root):
        raise ValueError(f"Legacy RESULTS_ROOT refused: {root}")
    if root.name == suffix:
        return root
    # If already pointing at a different dedicated pilot slug, keep it only when
    # it matches this profile; otherwise nest the requested suffix under parent.
    if root.name in ALL_PILOT_RESULTS_SUFFIXES:
        return root.parent / suffix
    if root.name == RESULTS_DIR_NAME:
        return root.parent / suffix
    return root / suffix


def resolve_full_results_root(results_root: str | Path | None = None) -> Path:
    raw = results_root or os.getenv("RESULTS_ROOT")
    if not raw:
        from pipeline.config import REPO_ROOT as _REPO_ROOT

        root = _REPO_ROOT / "results"
    else:
        root = normalize_path_input(raw)
    if path_contains_legacy_results(root):
        raise ValueError(f"Legacy RESULTS_ROOT refused: {root}")
    if root.name in ALL_PILOT_RESULTS_SUFFIXES:
        raise ValueError(
            f"Full production mode refuses pilot results root ({root.name}). "
            "Export a production RESULTS_ROOT."
        )
    if is_resolved_full_results_root(root):
        return root
    if root.name == RESULTS_DIR_NAME:
        return root.parent / FULL_RESULTS_SUFFIX
    if root.name == FULL_RESULTS_ALT_PARENT:
        return root / FULL_RESULTS_ALT_SUFFIX
    return root / FULL_RESULTS_SUFFIX


def describe_pilot_telemetry_source(
    *,
    results_root: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Locate pilot telemetry for full-run sizing. Prefer pilot-1000."""
    env = dict(os.environ if environ is None else environ)
    path = resolve_pilot_output_for_calibration(
        results_root=results_root or env.get("RESULTS_ROOT"),
        explicit_pilot_out=env.get("CEMENTITIOUS_PILOT_OUTPUT_DIR"),
    )
    if path is None:
        return {
            "present": False,
            "path": None,
            "profile": None,
            "preferred_profile": PILOT_1000_RESULTS_SUFFIX,
            "warning": (
                "No pilot telemetry found. Full mode will refuse to submit unless "
                "--allow-uncalibrated-resources is set. Prefer a completed "
                f"{PILOT_1000_RESULTS_SUFFIX} run."
            ),
        }
    parts = Path(path).parts
    if PILOT_1000_RESULTS_SUFFIX in parts:
        profile = "pilot-1000"
        warning = None
    elif PILOT_50_RESULTS_SUFFIX in parts:
        profile = "pilot-50"
        warning = (
            "Using pilot-50 telemetry for full-run sizing. "
            f"{PILOT_1000_RESULTS_SUFFIX} is preferred. Full submit is still allowed "
            "if this pilot's calibration validates."
        )
    elif PILOT_RESULTS_SUFFIX in parts:
        profile = "smoke"
        warning = (
            "Using smoke --pilot telemetry for full-run sizing. "
            f"{PILOT_1000_RESULTS_SUFFIX} is preferred. Full submit is still allowed "
            "if this pilot's calibration validates."
        )
    else:
        profile = "explicit"
        warning = None
    return {
        "present": True,
        "path": str(path),
        "profile": profile,
        "preferred_profile": PILOT_1000_RESULTS_SUFFIX,
        "warning": warning,
    }


def build_launch_config(
    mode: str,
    *,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> LaunchConfig:
    mode = normalize_launch_mode(mode)
    environ = dict(os.environ if env is None else env)
    keyword_only = environ.get("KEYWORD_ONLY", "").strip() in {"1", "true", "True", "yes"}
    resume = environ.get("RESUME", "").strip() in {"1", "true", "True", "yes"}
    force = environ.get("FORCE", "").strip() in {"1", "true", "True", "yes"}
    sample_seed = resolve_sample_seed(environ)

    tax_path = resolve_taxonomy_path(environ.get("TAXONOMY_PATH") or None)
    tax = load_taxonomy(tax_path)

    explicit_subs = [
        p.strip() for p in environ.get("SELECTED_SUBCATEGORIES", "").split(",") if p.strip()
    ]
    explicit_ss = [
        p.strip()
        for p in environ.get("SELECTED_SUB_SUBCATEGORIES", "").split(",")
        if p.strip()
    ]

    if is_pilot_launch_mode(mode):
        if mode == PILOT_50_LAUNCH_MODE:
            cap = PILOT_50_MAX_RECORDS
            suffix = PILOT_50_RESULTS_SUFFIX
            taxonomy_scope = PILOT_TAXONOMY_SCOPE_ALL
            web_defaults = PILOT_50_WEB_DEFAULTS
            default_workers = 1
            default_conc = 1
            default_shard = 50
        elif mode == PILOT_1000_LAUNCH_MODE:
            cap = PILOT_1000_MAX_RECORDS
            suffix = PILOT_1000_RESULTS_SUFFIX
            taxonomy_scope = PILOT_TAXONOMY_SCOPE_ALL
            web_defaults = PILOT_1000_WEB_DEFAULTS
            default_workers = 1
            default_conc = 2
            default_shard = 250
        else:
            cap = PILOT_MAX_RECORDS
            suffix = PILOT_RESULTS_SUFFIX
            taxonomy_scope = resolve_pilot_taxonomy_scope(environ)
            web_defaults = SMOKE_WEB_DEFAULTS
            default_workers = 1
            default_conc = 1
            default_shard = 0  # filled after max_records

        results_root = resolve_pilot_results_root(environ.get("RESULTS_ROOT"), suffix=suffix)
        out = resolve_results_dir(results_root)
        max_records = _int_env(environ, "CEMENTITIOUS_MAX_RECORDS", cap)
        if max_records > cap:
            max_records = cap
        shard_size = _int_env(
            environ, "SHARD_SIZE", default_shard if default_shard else max_records
        )
        if taxonomy_scope == PILOT_TAXONOMY_SCOPE_ALL:
            selected_subs: list[str] = []
            selected_ss: list[str] = []
        else:
            selected_subs = [PILOT_WEB_PARENT]
            selected_ss = [PILOT_WEB_LEAF]
        if explicit_subs:
            selected_subs = explicit_subs
        if explicit_ss:
            selected_ss = explicit_ss
        web_limits = _web_limits_from_defaults(environ, web_defaults)
        cfg = LaunchConfig(
            mode=mode,
            max_records=max_records,
            shard_size=shard_size,
            workers=_int_env(environ, "CEMENTITIOUS_WORKERS", default_workers),
            array_max_concurrency=_int_env(environ, "ARRAY_MAX_CONCURRENCY", default_conc),
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
            pilot_corpus_sampling=True,
            pilot_taxonomy_scope=taxonomy_scope,
            sample_seed=sample_seed,
            results_suffix=suffix,
            telemetry_enabled=True,
        )
    else:
        results_root = resolve_full_results_root(environ.get("RESULTS_ROOT"))
        out = resolve_results_dir(results_root)
        if environ.get("CEMENTITIOUS_MAX_RECORDS", "").strip():
            raise ValueError(
                "Full mode forbids CEMENTITIOUS_MAX_RECORDS; unset it for the ~159k corpus run"
            )
        web_max = _int_env(
            environ,
            "WEB_MAX_TOTAL_URLS",
            _int_env(environ, "WEB_LIMIT", 1000),
        )
        web_limits = {
            "WEB_QUERIES_PER_SUBCATEGORY": _int_env(environ, "WEB_QUERIES_PER_SUBCATEGORY", 3),
            "WEB_QUERIES_PER_SUB_SUBCATEGORY": _int_env(
                environ, "WEB_QUERIES_PER_SUB_SUBCATEGORY", 5
            ),
            "WEB_RESULTS_PER_QUERY": _int_env(environ, "WEB_RESULTS_PER_QUERY", 10),
            "WEB_MAX_URLS_PER_BRANCH": _int_env(environ, "WEB_MAX_URLS_PER_BRANCH", 50),
            "WEB_MAX_TOTAL_URLS": web_max,
            "WEB_SEARCH_SHARD_SIZE": _int_env(environ, "WEB_SEARCH_SHARD_SIZE", 10),
            "WEB_EXTRACT_SHARD_SIZE": _int_env(environ, "WEB_EXTRACT_SHARD_SIZE", 10),
            "WEB_LIMIT": _int_env(environ, "WEB_LIMIT", web_max),
            "WEB_MAX_TOTAL_QUERIES": _int_env(environ, "WEB_MAX_TOTAL_QUERIES", 0),
            "WEB_RATE_LIMIT_SLEEP_S": _float_env(environ, "WEB_RATE_LIMIT_SLEEP_S", 0),
            "WEB_CONCURRENCY": _int_env(environ, "WEB_CONCURRENCY", 1),
            "WEB_QUERIES_PER_NODE": _int_env(
                environ,
                "WEB_QUERIES_PER_NODE",
                _int_env(environ, "WEB_QUERIES_PER_SUB_SUBCATEGORY", 5),
            ),
        }
        cfg = LaunchConfig(
            mode=FULL_LAUNCH_MODE,
            max_records=None,
            shard_size=_int_env(environ, "SHARD_SIZE", FULL_SHARD_SIZE),
            workers=min(
                _int_env(environ, "CEMENTITIOUS_WORKERS", FULL_WORKERS),
                _int_env(environ, "CEMENTITIOUS_MAX_WORKERS", 4),
            ),
            array_max_concurrency=_int_env(
                environ, "ARRAY_MAX_CONCURRENCY", FULL_ARRAY_MAX_CONCURRENCY
            ),
            results_root=str(results_root),
            output_dir=str(out),
            pickle_path=str(environ.get("PICKLE_PATH") or environ.get("PAPER_RECORDS_PATH") or ""),
            taxonomy_path=str(tax_path),
            selected_subcategories=explicit_subs,
            selected_sub_subcategories=explicit_ss,
            web_limits=web_limits,
            keyword_only=keyword_only,
            resume=resume,
            force=force,
            dry_run=dry_run,
            sample_seed=None,
            results_suffix=FULL_RESULTS_SUFFIX,
            telemetry_enabled=True,
        )

    for slug in cfg.selected_subcategories:
        if slug not in tax.subcategories:
            raise ValueError(f"Unknown subcategory slug: {slug}")
    for slug in cfg.selected_sub_subcategories:
        if slug not in tax.sub_subcategories:
            raise ValueError(f"Unknown sub-subcategory slug: {slug}")

    run_mode, literature_enabled, web_enabled = resolve_run_mode_flags(environ)
    cfg.run_mode = run_mode
    cfg.literature_enabled = literature_enabled
    cfg.web_enabled = web_enabled
    cfg.require_tavily = web_enabled
    cfg.require_openai = (literature_enabled or web_enabled) and not cfg.keyword_only
    from pipeline.cementitious.web_scope import resolve_web_search_scope

    cfg.web_search_scope = resolve_web_search_scope(
        selected_subcategories=cfg.selected_subcategories,
        selected_sub_subcategories=cfg.selected_sub_subcategories,
        environ=environ,
    )
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
    """Runtime 9×58 leaves in literature/export scope (compatibility)."""
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


def web_search_node_summaries_for_launch(cfg: LaunchConfig) -> list[dict[str, Any]]:
    """Canonical (or runtime-restricted) Tavily search nodes for this launch."""
    from pipeline.cementitious.web_scope import searchable_node_summaries

    if cfg.web_search_scope != "canonical":
        summaries = []
        tax = load_taxonomy(cfg.taxonomy_path or None)
        for slug in web_leaf_slugs(cfg):
            node = tax.sub_subcategories.get(slug)
            if node is None:
                continue
            summaries.append(
                {
                    "path": "",
                    "path_labels": [tax.category_display, "", node.display_name],
                    "slug": slug,
                    "label": node.display_name,
                    "level": 3,
                    "role": "searchable_technology",
                    "aliases": list(node.representative_synonyms or [])[:8],
                    "level_1": "Cementitious Materials",
                    "runtime_sub_subcategory_slug": slug,
                }
            )
        return summaries
    return searchable_node_summaries()


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

    if cfg.run_mode not in {
        "literature-and-web",
        "literature_and_web",
        "literature-only",
        "literature_only",
        "web-only",
        "web_only",
    }:
        errors.append(f"Unsupported run_mode {cfg.run_mode}")
    if cfg.mode in ALL_PILOT_LAUNCH_MODES | {FULL_LAUNCH_MODE} and cfg.run_mode in {
        "literature-and-web",
        "literature_and_web",
    }:
        if not cfg.literature_enabled or not cfg.web_enabled:
            errors.append(
                "literature-and-web mode requires both literature_enabled and web_enabled; "
                "set RUN_MODE=literature-only or WEB_SEARCH_ENABLED=0 to disable web explicitly"
            )

    if cfg.require_openai and not env.get("OPENAI_API_KEY", "").strip() and not cfg.keyword_only:
        errors.append("OPENAI_API_KEY is required unless KEYWORD_ONLY=1")
    if cfg.web_enabled and cfg.require_tavily and not env.get("TAVILY_API_KEY", "").strip():
        errors.append(
            "TAVILY_API_KEY is required for web retrieval. Full literature-and-web mode "
            "will not silently fall back to literature-only."
        )
    if cfg.run_mode in {"literature-and-web", "literature_and_web"} and not env.get(
        "TAVILY_API_KEY", ""
    ).strip():
        if "TAVILY_API_KEY is required" not in " ".join(errors):
            errors.append(
                "TAVILY_API_KEY is required for combined literature-and-web mode"
            )

    if not cfg.pickle_path:
        errors.append("PICKLE_PATH or PAPER_RECORDS_PATH is required")
    else:
        pkl = Path(cfg.pickle_path)
        if not pkl.is_file():
            errors.append(f"PICKLE_PATH is not a readable file: {cfg.pickle_path}")

    if path_contains_legacy_results(cfg.results_root) or path_contains_legacy_results(cfg.output_dir):
        errors.append("RESULTS_ROOT/OUT must not use legacy '730 results'")

    if cfg.mode == SMOKE_LAUNCH_MODE:
        if cfg.max_records is None or cfg.max_records > PILOT_MAX_RECORDS:
            errors.append(f"Smoke --pilot must cap literature records at {PILOT_MAX_RECORDS}")
        if PILOT_RESULTS_SUFFIX not in Path(cfg.results_root).parts:
            errors.append(f"Smoke --pilot RESULTS_ROOT must nest under {PILOT_RESULTS_SUFFIX}")
        if RESULTS_DIR_NAME in Path(cfg.results_root).parts and Path(cfg.results_root).name == RESULTS_DIR_NAME:
            errors.append("Pilot must not write directly to production 7-30 results root")
    elif cfg.mode == PILOT_50_LAUNCH_MODE:
        if cfg.max_records != PILOT_50_MAX_RECORDS and (
            cfg.max_records is None or cfg.max_records > PILOT_50_MAX_RECORDS
        ):
            errors.append(f"--pilot-50 must cap literature records at {PILOT_50_MAX_RECORDS}")
        if PILOT_50_RESULTS_SUFFIX not in Path(cfg.results_root).parts:
            errors.append(f"--pilot-50 RESULTS_ROOT must nest under {PILOT_50_RESULTS_SUFFIX}")
        if PILOT_1000_RESULTS_SUFFIX in Path(cfg.results_root).parts:
            errors.append("--pilot-50 must not share the 1000-paper output root")
    elif cfg.mode == PILOT_1000_LAUNCH_MODE:
        if cfg.max_records is None or cfg.max_records > PILOT_1000_MAX_RECORDS:
            errors.append(
                f"--pilot-1000 must cap literature records at {PILOT_1000_MAX_RECORDS}"
            )
        if cfg.max_records != PILOT_1000_MAX_RECORDS and not env.get("CEMENTITIOUS_MAX_RECORDS"):
            errors.append("--pilot-1000 default literature cap must be 1000")
        if PILOT_1000_RESULTS_SUFFIX not in Path(cfg.results_root).parts:
            errors.append(f"--pilot-1000 RESULTS_ROOT must nest under {PILOT_1000_RESULTS_SUFFIX}")
        if PILOT_50_RESULTS_SUFFIX in Path(cfg.results_root).parts:
            errors.append("--pilot-1000 must not share the 50-paper output root")

    if is_pilot_launch_mode(cfg.mode):
        if RESULTS_DIR_NAME in Path(cfg.results_root).parts and Path(cfg.results_root).name == RESULTS_DIR_NAME:
            errors.append("Pilot must not write directly to production 7-30 results root")
        other = ALL_PILOT_RESULTS_SUFFIXES - {cfg.results_suffix}
        for suffix in other:
            if suffix and suffix in Path(cfg.output_dir).parts and cfg.results_suffix not in Path(cfg.output_dir).parts:
                errors.append(f"Pilot output_dir mixed with another pilot suffix {suffix}")

    if cfg.mode == "full" and cfg.max_records is not None:
        errors.append("Full mode must not set a literature record cap")
    if cfg.mode == FULL_LAUNCH_MODE:
        if any(suffix in Path(cfg.results_root).parts for suffix in ALL_PILOT_RESULTS_SUFFIXES):
            errors.append("Full mode must not write into a pilot output root")
        if not is_resolved_full_results_root(cfg.results_root):
            errors.append(
                "Full mode RESULTS_ROOT must nest under "
                f"{FULL_RESULTS_SUFFIX} (or {FULL_RESULTS_ALT_PARENT}/{FULL_RESULTS_ALT_SUFFIX})"
            )

    export_complete = Path(cfg.output_dir) / "checkpoints" / "export.complete"
    if export_complete.is_file() and not cfg.force and not cfg.dry_run:
        errors.append(
            f"Completed export exists at {export_complete}; set FORCE=1 to overwrite"
        )

    tax = load_taxonomy(cfg.taxonomy_path or None)
    for slug in web_leaf_slugs(cfg):
        if slug not in tax.sub_subcategories:
            errors.append(f"Runtime literature leaf missing from taxonomy: {slug}")
    if cfg.web_enabled and cfg.web_search_scope == "canonical":
        from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy

        decarb = get_decarbonization_taxonomy()
        nodes = web_search_node_summaries_for_launch(cfg)
        if cfg.mode in {FULL_LAUNCH_MODE} | FULL_TAXONOMY_PILOT_MODES and len(nodes) < 50:
            errors.append(
                f"{cfg.mode} canonical web scope produced only {len(nodes)} searchable nodes; "
                "expected the complete Level-3/4 technology set"
            )
        slugs = {n.get("slug") for n in nodes}
        if cfg.mode in {FULL_LAUNCH_MODE} | FULL_TAXONOMY_PILOT_MODES and slugs <= {
            PILOT_WEB_LEAF,
            "amine_absorption",
        }:
            errors.append(f"{cfg.mode} must not restrict web search to chemical_absorption")
        for node in nodes:
            path = node.get("path") or ""
            if path and path not in decarb.nodes_by_path:
                errors.append(f"Web search node missing from canonical taxonomy: {path}")
    for slug, paths in export_paths_for_leaves(cfg).items():
        if "records_csv" not in paths or "citations_csv" not in paths:
            errors.append(f"Missing export paths for leaf {slug}")

    if cfg.mode in FULL_TAXONOMY_PILOT_MODES:
        if cfg.pilot_taxonomy_scope != PILOT_TAXONOMY_SCOPE_ALL and not (
            cfg.selected_subcategories or cfg.selected_sub_subcategories
        ):
            errors.append(f"{cfg.mode} must use the full canonical taxonomy")
        if not cfg.literature_enabled:
            errors.append(f"{cfg.mode} requires literature retrieval")
        if not cfg.web_enabled:
            errors.append(f"{cfg.mode} requires Tavily/web retrieval")
        if cfg.web_search_scope != "canonical" and not (
            cfg.selected_subcategories or cfg.selected_sub_subcategories
        ):
            errors.append(f"{cfg.mode} web search must use the canonical taxonomy scope")
        if cfg.sample_seed is None:
            errors.append(f"{cfg.mode} requires a deterministic sample seed")
        if not cfg.telemetry_enabled:
            errors.append(f"{cfg.mode} requires resource telemetry")

    from pipeline.config import REPO_ROOT as _REPO_ROOT

    from pipeline.cementitious.decarbonization_taxonomy import (
        DEFAULT_DECARBONIZATION_TAXONOMY_PATH,
        validate_decarbonization_payload,
    )

    decarb_path = Path(DEFAULT_DECARBONIZATION_TAXONOMY_PATH)
    if not decarb_path.is_file():
        errors.append(f"Canonical taxonomy config missing: {decarb_path}")
    else:
        try:
            payload = json.loads(decarb_path.read_text(encoding="utf-8"))
            tax_errors = validate_decarbonization_payload(payload)
            errors.extend(f"canonical taxonomy: {e}" for e in tax_errors)
        except Exception as exc:
            errors.append(f"canonical taxonomy could not be loaded: {exc}")

    for rel in REQUIRED_ENGAGING_SCRIPTS:
        script = _REPO_ROOT / rel
        if not script.is_file():
            errors.append(f"Required Engaging script missing: {script}")

    try:
        out_path = Path(cfg.output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        probe = out_path / ".preflight_write_probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        errors.append(f"Output directory is not writable: {cfg.output_dir} ({exc})")

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
                    f"(prefer {PILOT_1000_RESULTS_SUFFIX}; set CEMENTITIOUS_PILOT_OUTPUT_DIR "
                    "or nest a pilot folder under RESULTS_ROOT). "
                    "Override only with --allow-uncalibrated-resources."
                )
            else:
                verdict = validate_pilot_calibration(pilot_out)
                if not verdict["ok"]:
                    errors.extend(verdict["errors"])
                source = describe_pilot_telemetry_source(
                    results_root=env.get("RESULTS_ROOT"), environ=env
                )
                if source.get("warning") and source.get("profile") != "pilot-1000":
                    # Prominent but non-blocking: missing pilot-1000 is a warning.
                    pass

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
    search_nodes = web_search_node_summaries_for_launch(cfg)
    from pipeline.cluster_shards import estimated_shard_count

    estimated_corpus = (
        int(cfg.max_records)
        if cfg.max_records is not None
        else ESTIMATED_FULL_CORPUS_RECORDS
    )
    n_screen = estimated_shard_count(estimated_corpus, int(cfg.shard_size) or FULL_SHARD_SIZE)
    if n_screen <= 0:
        screen_array = "0"
    elif n_screen == 1:
        screen_array = "0"
    else:
        screen_array = f"0-{n_screen - 1}"
    n_web_q = int(cfg.web_limits.get("WEB_MAX_TOTAL_QUERIES") or 0)
    n_web_shard = int(cfg.web_limits.get("WEB_SEARCH_SHARD_SIZE") or 10) or 10
    if n_web_q > 0:
        import math as _math

        n_web = max(1, _math.ceil(n_web_q / n_web_shard))
        web_search_array = "0" if n_web == 1 else f"0-{n_web - 1}"
    else:
        web_search_array = "0" if cfg.mode in ALL_PILOT_LAUNCH_MODES else "0-N"
    graph = build_dry_run_dependency_graph(
        run_mode=cfg.run_mode,
        screen_array=screen_array,
        extract_array="0",
        web_search_array=web_search_array,
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
        "literature_enabled": cfg.literature_enabled,
        "web_search_enabled": cfg.web_enabled,
        "web_search_scope": cfg.web_search_scope,
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
        "web_search_node_count": len(search_nodes),
        "web_search_node_slugs": [n.get("slug") for n in search_nodes],
        "web_search_level_1_branches": sorted(
            {n.get("level_1") for n in search_nodes if n.get("level_1")}
        ),
        "web_search_restricted_to_chemical_absorption": (
            {n.get("slug") for n in search_nodes} <= {PILOT_WEB_LEAF, "amine_absorption"}
        ),
        "web_limits": cfg.web_limits,
        "selected_subcategories": cfg.selected_subcategories,
        "selected_sub_subcategories": cfg.selected_sub_subcategories,
        "pilot_corpus_sampling": cfg.pilot_corpus_sampling,
        "pilot_taxonomy_scope": cfg.pilot_taxonomy_scope,
        "sample_seed": cfg.sample_seed,
        "results_suffix": cfg.results_suffix,
        "telemetry_enabled": cfg.telemetry_enabled,
        "git_commit": _git_commit(),
        "canonical_taxonomy": canonical_taxonomy_counts(),
        "taxonomy_restriction": taxonomy_restriction_text(cfg),
        "taxonomy_scope": taxonomy_scope_label(cfg),
        "literature_taxonomy": (
            "runtime"
            if cfg.selected_subcategories or cfg.selected_sub_subcategories
            else "canonical"
        ),
        "literature_record_cap_display": (
            "NONE / FULL CORPUS" if cfg.max_records is None else str(cfg.max_records)
        ),
        "export_complete_path": str(Path(cfg.output_dir) / "checkpoints" / "export.complete"),
        "export_complete_written_when": (
            "after hierarchical export and validation pass (final stage only)"
        ),
        "conceptual_dag": conceptual_dag_stages(),
        "launch_metadata": build_launch_metadata(cfg),
        "hierarchical_export": {
            "root": str(Path(cfg.output_dir) / "concrete_decarbonization_results"),
            "master_csv": str(
                Path(cfg.output_dir)
                / "concrete_decarbonization_results"
                / "concrete_decarbonization.csv"
            ),
        },
        "user_facing_export": {
            "root": str(Path(cfg.output_dir) / "cementitious_materials_results"),
            "master_csv": str(
                Path(cfg.output_dir)
                / "cementitious_materials_results"
                / "cementitious_materials_all_records.csv"
            ),
            "category_csvs": str(
                Path(cfg.output_dir) / "cementitious_materials_results" / "category_csvs"
            ),
            "subcategory_csvs": str(
                Path(cfg.output_dir) / "cementitious_materials_results" / "subcategory_csvs"
            ),
            "taxonomy_mapping": {
                "user_facing_category": "internal subcategory_slug",
                "user_facing_subcategory": "internal sub_subcategory_slug (taxonomy leaf)",
            },
            "empty_partition_policy": "omit empty user-facing CSVs",
        },
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
        "estimated_corpus_records": estimated_corpus,
        "estimated_literature_shard_count": n_screen,
        "pilot_telemetry_source": describe_pilot_telemetry_source(results_root=cfg.results_root),
        "concurrency_memory_note": (
            "Peak RSS scales approximately with ARRAY_MAX_CONCURRENCY × per-shard RSS. "
            f"Full defaults: SHARD_SIZE={FULL_SHARD_SIZE}, WORKERS={FULL_WORKERS}, "
            f"ARRAY_MAX_CONCURRENCY={FULL_ARRAY_MAX_CONCURRENCY}. "
            "Do not raise concurrency without calibrated MaxRSS headroom; "
            "CEMENTITIOUS_WORKERS does not fork the corpus in the sharded Engaging path."
        ),
        "notes": [
            "Dry-run does not call sbatch, OpenAI, or Tavily.",
            "Dry-run does not load the full corpus pickle.",
            "Preprocess Slurm job materializes memory-safe corpus JSONL shards once.",
            "Bootstrap job (after preprocess) plans web queries and submits the remaining DAG.",
            "Finalize depends on literature and web terminal merge jobs, then export.",
            "Soft memory ceiling defaults to 80% of each stage's Slurm --mem request.",
            "Full mode requires a successful calibrated pilot unless --allow-uncalibrated-resources.",
            "User-facing CSVs live under cementitious_materials_results/ (master + category_csvs + nested subcategory_csvs).",
            "Canonical hierarchical CSVs live under concrete_decarbonization_results/ (L0–L4).",
            "Internal all_records/, subcategories/ (9), and sub_subcategories/ (58, including empty) are retained for compatibility.",
            (
                "Smoke --pilot: corpus sampling (max 50 literature records) AND a single-branch "
                f"taxonomy restriction ({PILOT_WEB_PARENT} / {PILOT_WEB_LEAF}). "
                "Set CEMENTITIOUS_PILOT_TAXONOMY_SCOPE=all to keep the record cap without restricting taxonomy."
                if cfg.mode == SMOKE_LAUNCH_MODE
                else (
                    f"{cfg.mode}: literature_record_cap={cfg.max_records}; literature+web enabled; "
                    "full canonical Concrete Decarbonization taxonomy (L0–L4); not restricted to chemical_absorption."
                    if cfg.mode in FULL_TAXONOMY_PILOT_MODES
                    else "Full mode: uncapped literature corpus; canonical five-level web search; not limited to chemical_absorption."
                )
            ),
            "Missing TAVILY_API_KEY fails preflight for literature-and-web; it does not silently become literature-only.",
            "Literature sampling is deterministic Random.sample with CEMENTITIOUS_SAMPLE_SEED (default 42), not first-N.",
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
    parser.add_argument(
        "--mode",
        choices=["pilot", "smoke", "pilot-50", "pilot-1000", "full"],
        required=True,
        help="smoke/--pilot=one taxonomy branch; --pilot-50/--pilot-1000=full taxonomy caps; --full=production.",
    )
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
    warnings: list[str] = []
    if cfg.mode == FULL_LAUNCH_MODE:
        source = describe_pilot_telemetry_source(results_root=cfg.results_root)
        if source.get("warning"):
            warnings.append(source["warning"])
    report = {
        "config": cfg.as_public_dict(),
        "errors": errors,
        "warnings": warnings,
        "allow_uncalibrated_resources": bool(args.allow_uncalibrated_resources),
        "taxonomy": {
            "path": cfg.taxonomy_path,
            "leaf_count": taxonomy_summary(cfg.taxonomy_path)["leaf_count"],
            "subcategory_count": taxonomy_summary(cfg.taxonomy_path)["subcategory_count"],
            "web_leaves": web_leaf_slugs(cfg),
            "web_search_scope": cfg.web_search_scope,
            "web_search_nodes": web_search_node_summaries_for_launch(cfg),
            "canonical": canonical_taxonomy_counts(),
        },
        "launch_metadata": build_launch_metadata(cfg),
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
