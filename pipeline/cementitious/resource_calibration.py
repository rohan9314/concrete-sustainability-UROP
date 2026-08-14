"""Pilot telemetry consolidation and full-run memory calibration."""

from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.cementitious.memory import (
    DEFAULT_SAFETY_FACTOR,
    DEFAULT_SOFT_FRACTION,
    STAGE_MEMORY_PROFILES,
)

OOM_EXIT_CODES = {"137", "OUT_OF_MEMORY"}
POSSIBLE_CGROUP_KILL_MARKERS = frozenset({"9", "killed", "SIGKILL", "signal 9", "sigkill"})
NON_MEMORY_FAILURE_MARKERS = frozenset(
    {"TIMEOUT", "NODE_FAIL", "timeout", "node_failure", "NODE_FAIL", "Cancelled", "DEADLINE"}
)
UTILIZATION_WARN_PCT = 80.0
ESTIMATED_FULL_CORPUS_RECORDS = 159_000
FULL_SHARD_SIZE_DEFAULT = 10000
FULL_WORKERS_DEFAULT = 1
FULL_ARRAY_CONCURRENCY_DEFAULT = 1


def classify_job_failure(
    *,
    exit_code: str | int | None = None,
    state: str | None = None,
    completion_status: str | None = None,
    utilization_pct: float | None = None,
    maxrss_mb: float | None = None,
    requested_mem_gb: float | None = None,
) -> dict[str, Any]:
    """Classify a job/task ending without labeling every signal 9 as OOM.

    Definite OOM: Slurm OUT_OF_MEMORY, exit 137, or explicit oom status.
    Possible cgroup kill: signal 9 / killed — only treated as OOM when
    corroborated by high MaxRSS utilization or an OUT_OF_MEMORY state.
    TIMEOUT / NODE_FAIL are non-memory failures.
    """
    status = str(completion_status or "").strip()
    state_s = str(state or "").strip()
    code = str(exit_code or "").strip()
    code_major = code.split(":")[0].strip() if code else ""
    blob = " ".join([status, state_s, code]).strip()
    blob_cf = blob.casefold()

    if any(m.casefold() in blob_cf for m in NON_MEMORY_FAILURE_MARKERS):
        return {
            "kind": "non_memory",
            "label": f"non-memory failure ({blob or status or state_s or code})",
            "is_oom": False,
            "definite": False,
        }
    if status == "soft_memory_stop" or "soft_memory_stop" in blob_cf:
        return {
            "kind": "soft_memory_stop",
            "label": "soft_memory_stop (resumable; not a cgroup OOM)",
            "is_oom": False,
            "definite": False,
        }

    util = utilization_pct
    if util is None and maxrss_mb is not None and requested_mem_gb:
        util = 100.0 * float(maxrss_mb) / (float(requested_mem_gb) * 1024.0)
    high_util = util is not None and float(util) >= UTILIZATION_WARN_PCT

    definite = (
        code_major == "137"
        or "OUT_OF_MEMORY" in blob
        or status.casefold() in {"oom", "out_of_memory"}
        or state_s == "OUT_OF_MEMORY"
    )
    if definite:
        return {
            "kind": "oom",
            "label": f"definite OOM ({blob or status or code})",
            "is_oom": True,
            "definite": True,
        }

    possible_kill = (
        code_major == "9"
        or status.casefold() in POSSIBLE_CGROUP_KILL_MARKERS
        or "signal 9" in blob_cf
        or "sigkill" in blob_cf
    )
    if possible_kill:
        if high_util or state_s == "OUT_OF_MEMORY":
            return {
                "kind": "oom",
                "label": (
                    f"signal 9/killed corroborated as OOM "
                    f"(util={util}%, state={state_s})"
                ),
                "is_oom": True,
                "definite": True,
            }
        return {
            "kind": "possible_cgroup_kill",
            "label": (
                "possible cgroup kill (signal 9/killed); not labeled definite OOM "
                "without MaxRSS>=80% ReqMem or Slurm OUT_OF_MEMORY"
            ),
            "is_oom": False,
            "definite": False,
        }
    return {
        "kind": "other",
        "label": blob or status or "unknown",
        "is_oom": False,
        "definite": False,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_slurm_gb(gb: float) -> int:
    """Round upward to a practical Slurm memory request in whole GiB."""
    if gb <= 1:
        return 1
    if gb <= 4:
        return int(math.ceil(gb))
    if gb <= 16:
        # Round up to even GiB
        return int(math.ceil(gb / 2.0) * 2)
    if gb <= 64:
        return int(math.ceil(gb / 4.0) * 4)
    return int(math.ceil(gb / 8.0) * 8)


def discover_telemetry_files(output_dir: str | Path) -> list[Path]:
    root = Path(output_dir)
    logs = root / "logs" / "resource_telemetry"
    files: list[Path] = []
    if logs.is_dir():
        files.extend(sorted(logs.glob("*.json")))
    # Legacy screen paths
    for path in sorted((root / "logs").glob("*_memory.json")):
        files.append(path)
    for path in sorted((root / "metadata" / "screening_shards").glob("*_memory.json")):
        files.append(path)
    # Deduplicate
    seen: set[str] = set()
    unique: list[Path] = []
    for path in files:
        key = str(path.resolve())
        if key in seen or path.name == "telemetry_index.jsonl":
            continue
        # Skip index-like non-telemetry
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict) or "peak_rss_bytes" not in payload and "peak_rss_mb" not in payload:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def load_telemetry_rows(output_dir: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in discover_telemetry_files(output_dir):
        payload = json.loads(path.read_text(encoding="utf-8"))
        peak_bytes = int(payload.get("peak_rss_bytes") or 0)
        if not peak_bytes and payload.get("peak_rss_mb"):
            peak_bytes = int(float(payload["peak_rss_mb"]) * 1024 * 1024)
        stage = str(payload.get("stage") or path.stem.split("_")[0])
        profile = STAGE_MEMORY_PROFILES.get(stage)
        req = payload.get("requested_mem_gb")
        if req is None and profile:
            req = profile.mem_gb
        util = payload.get("utilization_pct_of_request")
        if util is None and req:
            util = round(100.0 * peak_bytes / (float(req) * (1024**3)), 2)
        rows.append(
            {
                "telemetry_path": str(path),
                "stage": stage,
                "job_id": str(payload.get("job_id") or payload.get("slurm_job_id") or ""),
                "array_task_id": str(
                    payload.get("array_task_id") or payload.get("slurm_array_task_id") or ""
                ),
                "hostname": str(payload.get("hostname") or ""),
                "shard_id": payload.get("shard_id"),
                "requested_mem_gb": req,
                "allocated_cpus": payload.get("allocated_cpus"),
                "input_record_count": payload.get("input_record_count"),
                "shard_file_bytes": payload.get("shard_file_bytes"),
                "worker_count": payload.get("worker_count") or payload.get("workers") or 1,
                "batch_size": payload.get("batch_size"),
                "peak_rss_bytes": peak_bytes,
                "peak_rss_mb": round(peak_bytes / (1024 * 1024), 2),
                "utilization_pct_of_request": util,
                "soft_limit_gb": payload.get("soft_limit_gb"),
                "elapsed_seconds": payload.get("elapsed_seconds"),
                "records_processed": payload.get("records_processed")
                or payload.get("actual_processed_count"),
                "completion_status": payload.get("completion_status")
                or payload.get("status")
                or "unknown",
            }
        )
    return rows


def write_resource_usage_summary(output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    meta = out / "metadata"
    meta.mkdir(parents=True, exist_ok=True)
    rows = load_telemetry_rows(out)
    csv_path = meta / "resource_usage_summary.csv"
    json_path = meta / "resource_usage_summary.json"
    fieldnames = [
        "stage",
        "job_id",
        "array_task_id",
        "hostname",
        "shard_id",
        "requested_mem_gb",
        "allocated_cpus",
        "input_record_count",
        "shard_file_bytes",
        "worker_count",
        "batch_size",
        "peak_rss_mb",
        "utilization_pct_of_request",
        "soft_limit_gb",
        "elapsed_seconds",
        "records_processed",
        "completion_status",
        "telemetry_path",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    payload = {
        "created_at": _now(),
        "output_dir": str(out),
        "row_count": len(rows),
        "rows": rows,
        "secrets_included": False,
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _peak_by_stage(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        stage = row["stage"]
        prev = best.get(stage)
        if prev is None or float(row.get("peak_rss_mb") or 0) > float(prev.get("peak_rss_mb") or 0):
            best[stage] = row
    return best


def estimate_full_run_peak_mb(
    stage: str,
    pilot_peak_mb: float,
    *,
    pilot_leaf_count: int = 1,
    full_leaf_count: int = 58,
    pilot_max_records: int = 50,
    estimated_full_accepted: int | None = None,
    shard_size_pilot: int = 50,
    shard_size_full: int = 10000,
) -> tuple[float, str, str]:
    """
    Return (estimated_peak_mb, confidence, explanation).

    Scaling is stage-class specific — not a naive linear corpus multiplier.
    """
    profile = STAGE_MEMORY_PROFILES.get(stage)
    scales = set(profile.scales_with) if profile else set()

    if stage == "preprocess_plan" or (profile and profile.loads_full_pickle):
        # Pilot still deserializes the full pickle before truncating.
        return (
            pilot_peak_mb,
            "high",
            "Preprocessing deserializes the full pickle in both pilot and full; "
            "pilot peak is a direct estimate of full preprocessing cost.",
        )

    if stage in {"screen", "extract", "web_search", "web_extract"}:
        # Shard-local: scale with shard payload size / page bounds, not shard count.
        ratio = max(1.0, float(shard_size_full) / max(1, shard_size_pilot))
        # For web_extract, page size bound is fixed; mild growth with URLs per shard.
        if stage.startswith("web"):
            leaf_ratio = max(1.0, float(full_leaf_count) / max(1, pilot_leaf_count))
            # Concurrent leaves are serialized by array concurrency=1; per-task memory
            # stays near pilot, but total wall-time and merge inputs grow with leaves.
            est = pilot_peak_mb * 1.2
            return (
                est,
                "medium",
                "Web/array tasks are shard-local with concurrency 1; per-task RSS stays "
                f"near pilot (~×1.2 headroom). Aggregate work scales with {leaf_ratio:.1f}× leaves.",
            )
        est = pilot_peak_mb * min(ratio, 4.0)  # cap pathological extrapolation
        # Prefer interpreting pilot shard of 50 vs full shard of 10000 carefully:
        # screening loads one shard; full shards are larger so scale by size ratio with cap.
        return (
            est,
            "medium",
            f"Shard-local stage: estimate scales with shard_size ratio "
            f"({shard_size_pilot}→{shard_size_full}, capped) rather than total corpus size.",
        )

    if stage in {
        "screen_merge",
        "extract_merge",
        "web_search_merge",
        "web_extract_merge",
        "merge_literature_web",
        "dedupe_qc",
        "export",
    }:
        accepted = estimated_full_accepted
        if accepted is None:
            # Conservative heuristic: pilot acceptance rate × full corpus is unknown;
            # use leaf-scaled URL budget for web-heavy merges and a cautious multiplier.
            accepted = max(pilot_max_records * 20, full_leaf_count * 25)
        growth = max(1.0, float(accepted) / max(1, pilot_max_records))
        # Sublinear-ish due to streaming: use sqrt growth + linear key-set term.
        est = pilot_peak_mb * (1.0 + math.sqrt(growth)) * 0.5 + pilot_peak_mb * 0.5 * min(growth, 50) / 10.0
        est = max(pilot_peak_mb * 1.5, est)
        return (
            est,
            "low" if estimated_full_accepted is None else "medium",
            "Merge/dedupe/export scale with accepted-record/URL volume; streaming reduces "
            f"but does not eliminate growth (heuristic accepted≈{accepted}).",
        )

    return (
        pilot_peak_mb * DEFAULT_SAFETY_FACTOR,
        "low",
        f"Generic ×{DEFAULT_SAFETY_FACTOR} safety projection for unclassified stage.",
    )


def build_full_run_recommendations(
    output_dir: str | Path,
    *,
    safety_factor: float = DEFAULT_SAFETY_FACTOR,
    pilot_leaf_count: int = 1,
    full_leaf_count: int = 58,
    fixed_headroom_mb: float = 512.0,
) -> dict[str, Any]:
    if safety_factor < DEFAULT_SAFETY_FACTOR:
        raise ValueError(f"safety_factor must be >= {DEFAULT_SAFETY_FACTOR}")
    out = Path(output_dir)
    summary = write_resource_usage_summary(out)
    by_stage = _peak_by_stage(summary["rows"])
    stages: dict[str, Any] = {}
    for name, profile in STAGE_MEMORY_PROFILES.items():
        row = by_stage.get(name)
        pilot_req = profile.mem_gb
        pilot_peak_mb = float(row["peak_rss_mb"]) if row else 0.0
        util = float(row["utilization_pct_of_request"]) if row and row.get("utilization_pct_of_request") is not None else None
        est_mb, confidence, explanation = estimate_full_run_peak_mb(
            name,
            pilot_peak_mb or (profile.mem_gb * 1024 * 0.2),
            pilot_leaf_count=pilot_leaf_count,
            full_leaf_count=full_leaf_count,
        )
        recommended_mb = est_mb * safety_factor + fixed_headroom_mb
        # If pilot utilization was high, bump further.
        if util is not None and util >= UTILIZATION_WARN_PCT:
            recommended_mb = max(recommended_mb, pilot_req * 1024 * 1.5 + fixed_headroom_mb)
            explanation += (
                f" Pilot utilization {util}% >= {UTILIZATION_WARN_PCT}% → inflated full request."
            )
        recommended_gb = _round_slurm_gb(recommended_mb / 1024.0)
        if pilot_peak_mb > 0:
            observed_gb = int(math.ceil(pilot_peak_mb / 1024.0))
            recommended_gb = max(recommended_gb, observed_gb)
        # Never recommend below pilot request for preprocess.
        if name == "preprocess_plan":
            recommended_gb = max(recommended_gb, int(math.ceil(pilot_req)))
        soft_gb = round(recommended_gb * DEFAULT_SOFT_FRACTION, 3)
        stages[name] = {
            "pilot_requested_memory_gb": pilot_req,
            "pilot_observed_peak_rss_mb": pilot_peak_mb,
            "utilization_pct_of_request": util,
            "safety_factor": safety_factor,
            "fixed_headroom_mb": fixed_headroom_mb,
            "estimated_full_run_peak_rss_mb": round(est_mb, 2),
            "recommended_slurm_memory_gb": recommended_gb,
            "recommended_slurm_memory": f"{recommended_gb}G",
            "recommended_soft_ceiling_gb": soft_gb,
            "recommended_shard_size": FULL_SHARD_SIZE_DEFAULT
            if name in {"screen", "preprocess_plan"}
            else None,
            "recommended_worker_count": FULL_WORKERS_DEFAULT,
            "recommended_array_concurrency": FULL_ARRAY_CONCURRENCY_DEFAULT,
            "confidence": confidence if row else "none",
            "explanation": explanation if row else "No pilot telemetry for stage; using profile defaults inflated by safety factor.",
            "loads_full_pickle": profile.loads_full_pickle,
            "pilot_telemetry_present": row is not None,
            "completion_status": (row or {}).get("completion_status"),
        }
    missing = [name for name, info in stages.items() if not info["pilot_telemetry_present"]]
    warnings = []
    if missing:
        warnings.append(
            "Insufficient pilot telemetry for stages: " + ", ".join(missing) + ". "
            "Recommendations for those stages use profile defaults × safety factor."
        )
    from pipeline.cluster_shards import estimated_shard_count

    worker_gb = int(stages.get("screen", {}).get("recommended_slurm_memory_gb") or 8)
    preprocess_gb = int(stages.get("preprocess_plan", {}).get("recommended_slurm_memory_gb") or 64)
    finalize_gb = max(
        int(stages.get(s, {}).get("recommended_slurm_memory_gb") or 16)
        for s in ("dedupe_qc", "export", "screen_merge", "extract_merge", "merge_literature_web")
    )
    payload = {
        "created_at": _now(),
        "pilot_output_dir": str(out),
        "evidence_source_pilot": str(out),
        "safety_factor": safety_factor,
        "soft_fraction_of_request": DEFAULT_SOFT_FRACTION,
        "pilot_leaf_count": pilot_leaf_count,
        "full_leaf_count": full_leaf_count,
        "recommended_preprocess_memory": f"{preprocess_gb}G",
        "recommended_worker_memory": f"{worker_gb}G",
        "recommended_finalize_export_memory": f"{finalize_gb}G",
        "shard_size": FULL_SHARD_SIZE_DEFAULT,
        "workers": FULL_WORKERS_DEFAULT,
        "array_concurrency": FULL_ARRAY_CONCURRENCY_DEFAULT,
        "expected_shard_count": estimated_shard_count(
            ESTIMATED_FULL_CORPUS_RECORDS, FULL_SHARD_SIZE_DEFAULT
        ),
        "estimated_full_corpus_records": ESTIMATED_FULL_CORPUS_RECORDS,
        "observed_pilot_maxrss_mb_by_stage": {
            name: info.get("pilot_observed_peak_rss_mb") for name, info in stages.items()
        },
        "warnings": warnings,
        "stages": stages,
        "secrets_included": False,
    }
    path = out / "metadata" / "full_run_resource_recommendations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _scan_job_states(output_dir: Path) -> list[str]:
    """Best-effort scan of local manifests for OOM / soft-stop markers (no sacct)."""
    problems: list[str] = []
    for path in (output_dir / "metadata").glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        verdict = classify_job_failure(
            exit_code=payload.get("ExitCode") or payload.get("exit_code"),
            state=payload.get("State") or payload.get("state"),
            completion_status=payload.get("completion_status") or payload.get("status"),
        )
        if verdict["kind"] in {"oom", "possible_cgroup_kill", "soft_memory_stop"}:
            problems.append(f"{verdict['label']} in {path.name}")
        elif verdict["kind"] == "non_memory":
            problems.append(f"{verdict['label']} in {path.name}")
    for row in load_telemetry_rows(output_dir):
        verdict = classify_job_failure(
            completion_status=row.get("completion_status"),
            utilization_pct=row.get("utilization_pct_of_request"),
            maxrss_mb=row.get("peak_rss_mb"),
            requested_mem_gb=row.get("requested_mem_gb"),
        )
        if verdict["kind"] == "non_memory":
            continue
        if verdict["kind"] in {"oom", "possible_cgroup_kill", "soft_memory_stop"}:
            problems.append(f"{verdict['label']} in stage {row['stage']}")
    return problems


REQUIRED_PILOT_STAGES = (
    "preprocess_plan",
    "screen",
    "extract",
    "web_search",
    "web_extract",
    "dedupe_qc",
    "export",
)


def validate_pilot_calibration(
    pilot_output_dir: str | Path,
    *,
    require_all_stages: bool = True,
) -> dict[str, Any]:
    out = Path(pilot_output_dir)
    errors: list[str] = []
    warnings: list[str] = []

    export_marker = out / "checkpoints" / "export.complete"
    if not export_marker.is_file():
        errors.append(f"Missing export completion marker: {export_marker}")

    summary_path = out / "metadata" / "resource_usage_summary.json"
    reco_path = out / "metadata" / "full_run_resource_recommendations.json"
    if not summary_path.is_file():
        # Try to build from telemetry.
        try:
            write_resource_usage_summary(out)
        except Exception as exc:
            errors.append(f"Unable to build resource_usage_summary: {exc}")
    if not reco_path.is_file():
        try:
            build_full_run_recommendations(out)
        except Exception as exc:
            errors.append(f"Unable to build full_run_resource_recommendations: {exc}")

    rows = load_telemetry_rows(out) if out.is_dir() else []
    if not rows:
        errors.append("No pilot RSS telemetry rows found")
    by_stage = _peak_by_stage(rows)
    if require_all_stages:
        for stage in REQUIRED_PILOT_STAGES:
            if stage not in by_stage:
                errors.append(f"Missing peak RSS telemetry for required stage: {stage}")
            else:
                peak = float(by_stage[stage].get("peak_rss_mb") or 0)
                if peak <= 0:
                    errors.append(f"Non-positive peak RSS for stage: {stage}")
                status = str(by_stage[stage].get("completion_status") or "")
                if status not in {"complete", "skipped_resume", "ok", "success", "unknown", ""}:
                    if status == "soft_memory_stop":
                        errors.append(f"Unresolved soft-memory stop for stage: {stage}")
                    else:
                        warnings.append(f"Unusual completion_status for {stage}: {status}")

    for problem in _scan_job_states(out):
        if "possible cgroup kill" in problem:
            warnings.append(problem)
        elif "non-memory failure" in problem:
            warnings.append(problem)
        else:
            errors.append(problem)

    # High utilization is OK if recommendations bump memory.
    reco = {}
    if reco_path.is_file():
        reco = json.loads(reco_path.read_text(encoding="utf-8"))
    for stage, row in by_stage.items():
        util = row.get("utilization_pct_of_request")
        if util is None:
            continue
        if float(util) >= UTILIZATION_WARN_PCT:
            stage_reco = (reco.get("stages") or {}).get(stage) or {}
            pilot_req = float(row.get("requested_mem_gb") or 0)
            full_req = float(stage_reco.get("recommended_slurm_memory_gb") or 0)
            if full_req <= pilot_req:
                errors.append(
                    f"Stage {stage} used {util}% of request but full recommendation "
                    f"({full_req}G) did not increase above pilot ({pilot_req}G)"
                )
            else:
                warnings.append(
                    f"Stage {stage} used {util}% of pilot request; full recommends {full_req}G"
                )

    if reco_path.is_file():
        for stage, info in (reco.get("stages") or {}).items():
            soft = float(info.get("recommended_soft_ceiling_gb") or 0)
            hard = float(info.get("recommended_slurm_memory_gb") or 0)
            if hard and soft and soft > hard * DEFAULT_SOFT_FRACTION + 1e-6:
                errors.append(f"Soft ceiling for {stage} exceeds {DEFAULT_SOFT_FRACTION:.0%} of hard request")
            if float(info.get("safety_factor") or 0) < DEFAULT_SAFETY_FACTOR:
                errors.append(f"Safety factor for {stage} below {DEFAULT_SAFETY_FACTOR}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "pilot_output_dir": str(out),
        "telemetry_rows": len(rows),
        "recommendations_path": str(reco_path) if reco_path.is_file() else "",
        "summary_path": str(summary_path) if summary_path.is_file() else "",
    }


def apply_recommendations_to_environ(
    recommendations: dict[str, Any],
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map calibrated stage memory into env vars consumed by Slurm wrappers."""
    env = dict(os.environ if environ is None else environ)
    stages = recommendations.get("stages") or {}
    mapping = {
        "preprocess_plan": "CEMENTITIOUS_MEM_PREPROCESS_GB",
        "screen": "CEMENTITIOUS_MEM_SCREEN_GB",
        "extract": "CEMENTITIOUS_MEM_EXTRACT_GB",
        "web_search": "CEMENTITIOUS_MEM_WEB_SEARCH_GB",
        "web_extract": "CEMENTITIOUS_MEM_WEB_EXTRACT_GB",
        "screen_merge": "CEMENTITIOUS_MEM_MERGE_GB",
        "extract_merge": "CEMENTITIOUS_MEM_MERGE_GB",
        "merge_literature_web": "CEMENTITIOUS_MEM_MERGE_GB",
        "dedupe_qc": "CEMENTITIOUS_MEM_DEDUPE_GB",
        "export": "CEMENTITIOUS_MEM_EXPORT_GB",
    }
    # Prefer max across merge-like stages for SUBMIT_LOGIN_MEM.
    merge_gb = 16
    for stage, env_key in mapping.items():
        info = stages.get(stage) or {}
        gb = int(info.get("recommended_slurm_memory_gb") or STAGE_MEMORY_PROFILES[stage].mem_gb)
        env[env_key] = str(gb)
        soft_key = env_key.replace("_MEM_", "_SOFT_")
        # e.g. CEMENTITIOUS_SOFT_SCREEN_GB — also set generic soft for workers
        env[soft_key] = str(info.get("recommended_soft_ceiling_gb") or round(gb * DEFAULT_SOFT_FRACTION, 3))
        if stage in {
            "screen_merge",
            "extract_merge",
            "merge_literature_web",
            "web_search_merge",
            "web_extract_merge",
            "dedupe_qc",
            "export",
        }:
            merge_gb = max(merge_gb, gb)
    env["SUBMIT_LOGIN_MEM"] = f"{merge_gb}G"
    env["CEMENTITIOUS_WORKERS"] = str(recommendations.get("workers") or FULL_WORKERS_DEFAULT)
    env["ARRAY_MAX_CONCURRENCY"] = str(
        recommendations.get("array_concurrency") or FULL_ARRAY_CONCURRENCY_DEFAULT
    )
    env["SHARD_SIZE"] = str(recommendations.get("shard_size") or FULL_SHARD_SIZE_DEFAULT)
    return env


def resolve_pilot_output_for_calibration(
    *,
    results_root: str | Path | None = None,
    explicit_pilot_out: str | Path | None = None,
) -> Path | None:
    if explicit_pilot_out:
        path = Path(explicit_pilot_out)
        return path if path.is_dir() else None
    raw = os.getenv("CEMENTITIOUS_PILOT_OUTPUT_DIR") or os.getenv("PILOT_OUTPUT_DIR")
    if raw:
        path = Path(raw)
        return path if path.is_dir() else None
    if results_root:
        from pipeline.cementitious.paths import resolve_results_dir
        from pipeline.cementitious.workflow_launch import (
            PILOT_1000_RESULTS_SUFFIX,
            PILOT_50_RESULTS_SUFFIX,
            PILOT_RESULTS_SUFFIX,
            unwrap_results_root_for_calibration,
        )

        candidate = Path(results_root)
        parent = unwrap_results_root_for_calibration(candidate) or candidate
        from pipeline.cementitious import RESULTS_DIR_NAME

        if candidate.name == RESULTS_DIR_NAME:
            parent = unwrap_results_root_for_calibration(candidate.parent) or candidate.parent
        for suffix in (
            PILOT_1000_RESULTS_SUFFIX,
            PILOT_50_RESULTS_SUFFIX,
            PILOT_RESULTS_SUFFIX,
        ):
            sibling = parent / suffix
            if sibling.is_dir():
                return resolve_results_dir(sibling)
    return None
