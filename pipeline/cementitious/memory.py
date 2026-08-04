"""Stage memory profiles, structured telemetry, and soft-ceiling helpers."""

from __future__ import annotations

import json
import logging
import os
import resource
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Soft ceiling as a fraction of the Slurm hard --mem request (pilot default).
DEFAULT_SOFT_FRACTION = 0.80
DEFAULT_SAFETY_FACTOR = 1.5


class ControlledMemoryStop(RuntimeError):
    """Raised when RSS approaches the soft memory ceiling; safe to resume."""


@dataclass(frozen=True)
class StageMemoryProfile:
    stage: str
    mem_gb: float
    soft_fraction: float = DEFAULT_SOFT_FRACTION
    cpus: int = 1
    loads_full_pickle: bool = False
    scales_with: tuple[str, ...] = ()
    rationale: str = ""

    @property
    def soft_limit_gb(self) -> float:
        return round(self.mem_gb * self.soft_fraction, 3)

    @property
    def mem_slurm(self) -> str:
        value = self.mem_gb
        if value == int(value):
            return f"{int(value)}G"
        return f"{value}G"


# Conservative pilot requests. Soft ceiling = 80% of hard request.
STAGE_MEMORY_PROFILES: dict[str, StageMemoryProfile] = {
    "preprocess_plan": StageMemoryProfile(
        stage="preprocess_plan",
        mem_gb=64,
        loads_full_pickle=True,
        scales_with=("full_pickle_deserialize",),
        rationale=(
            "One-time pickle.load of ~5.2GB on-disk corpus; deserialized RSS often "
            "2–4× disk. Same cost in pilot and full when MAX_RECORDS only truncates "
            "after full load."
        ),
    ),
    "bootstrap": StageMemoryProfile(
        stage="bootstrap",
        mem_gb=8,
        scales_with=("planning_metadata",),
        rationale="Plans web queries and submits Slurm jobs; no full corpus load.",
    ),
    "screen": StageMemoryProfile(
        stage="screen",
        mem_gb=8,
        scales_with=("shard_size", "batch_size", "record_field_size", "workers"),
        rationale="Loads one corpus JSONL shard only; peak ≈ shard + LLM buffers.",
    ),
    "screen_merge": StageMemoryProfile(
        stage="screen_merge",
        mem_gb=16,
        scales_with=("shard_size", "total_screened_indices_set"),
        rationale="Streams shard JSONL to merged file; holds corpus_index set.",
    ),
    "extract": StageMemoryProfile(
        stage="extract",
        mem_gb=8,
        scales_with=("extract_shard_size", "batch_size", "workers", "llm_payload"),
        rationale="Ranked-candidate shard only; no full pickle.",
    ),
    "extract_merge": StageMemoryProfile(
        stage="extract_merge",
        mem_gb=16,
        scales_with=("accepted_candidates", "citation_count"),
        rationale="Streams extraction shards; duplicate-ID sets only.",
    ),
    "web_search": StageMemoryProfile(
        stage="web_search",
        mem_gb=8,
        scales_with=("queries_per_shard", "results_per_query", "url_budget"),
        rationale="One web-query shard; bounded by WEB_* limits.",
    ),
    "web_extract": StageMemoryProfile(
        stage="web_extract",
        mem_gb=16,
        scales_with=("urls_per_shard", "page_max_chars", "workers"),
        rationale="Assigned URLs only; page text truncated to WEB_PAGE_MAX_CHARS.",
    ),
    "web_search_merge": StageMemoryProfile(
        stage="web_search_merge",
        mem_gb=16,
        scales_with=("total_urls", "url_budget"),
        rationale="URL-key maps bounded by WEB_MAX_TOTAL_URLS.",
    ),
    "web_extract_merge": StageMemoryProfile(
        stage="web_extract_merge",
        mem_gb=16,
        scales_with=("web_records", "citations"),
        rationale="Streams web extraction shards to disk.",
    ),
    "merge_literature_web": StageMemoryProfile(
        stage="merge_literature_web",
        mem_gb=16,
        scales_with=("lit_records", "web_records"),
        rationale="Indexes literature keys; avoids full list duplication.",
    ),
    "dedupe_qc": StageMemoryProfile(
        stage="dedupe_qc",
        mem_gb=16,
        scales_with=("accepted_records",),
        rationale="SQLite-backed or streaming-friendly dedupe of accepted records.",
    ),
    "export": StageMemoryProfile(
        stage="export",
        mem_gb=16,
        scales_with=("accepted_records", "partition_count"),
        rationale="Holds accepted rows once; citations streamed per partition.",
    ),
}


@dataclass
class MemoryTelemetry:
    """Lightweight RSS telemetry for a stage run."""

    stage: str
    shard_id: int | None = None
    samples: list[dict[str, Any]] = field(default_factory=list)
    peak_rss_bytes: int = 0
    records_processed: int = 0
    input_record_count: int | None = None
    shard_file_bytes: int | None = None
    worker_count: int = 1
    batch_size: int = 1
    requested_mem_gb: float | None = None
    soft_limit_gb: float | None = None
    status: str = "running"
    started_at: float = field(default_factory=time.time)

    def snapshot(self, label: str, *, records_processed: int | None = None) -> dict[str, Any]:
        rss = current_rss_bytes()
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
        if records_processed is not None:
            self.records_processed = records_processed
        row = {
            "label": label,
            "timestamp": time.time(),
            "rss_bytes": rss,
            "rss_mb": round(rss / (1024 * 1024), 2),
            "peak_rss_mb": round(self.peak_rss_bytes / (1024 * 1024), 2),
            "records_processed": self.records_processed,
            "shard_id": self.shard_id,
            "stage": self.stage,
        }
        self.samples.append(row)
        return row

    def as_dict(self) -> dict[str, Any]:
        meta = slurm_resource_meta()
        elapsed = round(time.time() - self.started_at, 3)
        req = self.requested_mem_gb
        if req is None and self.stage in STAGE_MEMORY_PROFILES:
            req = STAGE_MEMORY_PROFILES[self.stage].mem_gb
        soft = self.soft_limit_gb
        if soft is None and self.stage in STAGE_MEMORY_PROFILES:
            soft = STAGE_MEMORY_PROFILES[self.stage].soft_limit_gb
        peak = self.peak_rss_bytes
        util = None
        if req and req > 0:
            util = round(100.0 * peak / (req * (1024**3)), 2)
        return {
            "stage": self.stage,
            "shard_id": self.shard_id,
            "job_id": meta.get("slurm_job_id") or "",
            "array_task_id": meta.get("slurm_array_task_id") or "",
            "hostname": meta.get("hostname") or socket.gethostname(),
            "requested_mem_gb": req,
            "allocated_cpus": meta.get("allocated_cpus"),
            "input_record_count": self.input_record_count,
            "shard_file_bytes": self.shard_file_bytes,
            "worker_count": self.worker_count,
            "batch_size": self.batch_size,
            "current_rss_bytes": current_rss_bytes(),
            "peak_rss_bytes": peak,
            "peak_rss_mb": round(peak / (1024 * 1024), 2),
            "utilization_pct_of_request": util,
            "soft_limit_gb": soft,
            "elapsed_seconds": elapsed,
            "records_processed": self.records_processed,
            "completion_status": self.status,
            "samples": self.samples,
            **meta,
        }

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2) + "\n", encoding="utf-8")
        return path


def current_rss_bytes() -> int:
    """Best-effort resident set size in bytes (macOS/Linux)."""
    proc = Path("/proc/self/status")
    if proc.is_file():
        for line in proc.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) * 1024
    import sys

    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return rss
    return rss * 1024


def slurm_resource_meta() -> dict[str, Any]:
    cpus = os.getenv("SLURM_CPUS_PER_TASK") or os.getenv("SLURM_CPUS_ON_NODE") or ""
    mem = os.getenv("SLURM_MEM_PER_NODE") or os.getenv("SLURM_MEM_PER_CPU") or ""
    return {
        "hostname": socket.gethostname(),
        "slurm_job_id": os.getenv("SLURM_JOB_ID", ""),
        "slurm_array_job_id": os.getenv("SLURM_ARRAY_JOB_ID", ""),
        "slurm_array_task_id": os.getenv("SLURM_ARRAY_TASK_ID", ""),
        "allocated_cpus": int(cpus) if str(cpus).isdigit() else cpus or None,
        "slurm_mem_visible": mem,
    }


def soft_memory_limit_bytes() -> int | None:
    raw = os.getenv("CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB", "").strip()
    if not raw:
        # Derive from stage profile when STAGE is set.
        stage = os.getenv("CEMENTITIOUS_STAGE", "").strip()
        if stage and stage in STAGE_MEMORY_PROFILES:
            return int(STAGE_MEMORY_PROFILES[stage].soft_limit_gb * (1024**3))
        return None
    try:
        gb = float(raw)
    except ValueError:
        logger.warning("Invalid CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB=%r; ignoring", raw)
        return None
    if gb <= 0:
        return None
    return int(gb * (1024**3))


def soft_memory_threshold_fraction() -> float:
    """Fraction of the soft-limit GB at which ControlledMemoryStop fires.

    Soft limit itself is already ~80% of Slurm --mem; threshold defaults to 1.0
    of that soft limit (i.e. stop at the soft ceiling). Legacy env still honored.
    """
    raw = os.getenv("CEMENTITIOUS_SOFT_MEMORY_THRESHOLD", "1.0").strip()
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return min(1.0, max(0.5, value))


def apply_stage_soft_limit(stage: str) -> float:
    """Export soft-limit env for ``stage`` from the profile; return soft GB."""
    profile = STAGE_MEMORY_PROFILES[stage]
    soft = profile.soft_limit_gb
    os.environ["CEMENTITIOUS_STAGE"] = stage
    os.environ["CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB"] = str(soft)
    return soft


def check_soft_memory_ceiling(*, telemetry: MemoryTelemetry | None = None) -> None:
    """Raise ControlledMemoryStop when RSS crosses the soft ceiling."""
    limit = soft_memory_limit_bytes()
    if limit is None:
        return
    rss = current_rss_bytes()
    if telemetry is not None:
        telemetry.peak_rss_bytes = max(telemetry.peak_rss_bytes, rss)
    threshold = int(limit * soft_memory_threshold_fraction())
    if rss >= threshold:
        raise ControlledMemoryStop(
            f"Soft memory ceiling reached: RSS={rss / (1024**3):.2f} GiB "
            f">= {soft_memory_threshold_fraction():.0%} of soft limit "
            f"({limit / (1024**3):.2f} GiB). Checkpoint and exit for resume."
        )


def cementitious_workers() -> int:
    raw = os.getenv("CEMENTITIOUS_WORKERS", os.getenv("EXTRACTION_CONCURRENCY", "1")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1
    max_workers = int(os.getenv("CEMENTITIOUS_MAX_WORKERS", "4"))
    return max(1, min(value, max_workers))


def cementitious_batch_size(default: int = 25) -> int:
    raw = os.getenv("CEMENTITIOUS_BATCH_SIZE", str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(1, min(value, 500))


def cementitious_max_in_flight(default: int = 1) -> int:
    raw = os.getenv("CEMENTITIOUS_MAX_IN_FLIGHT", str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(1, min(value, cementitious_workers()))


def log_concurrency_settings(logger_: logging.Logger | None = None) -> dict[str, Any]:
    log = logger_ or logger
    payload = {
        "CEMENTITIOUS_WORKERS": cementitious_workers(),
        "CEMENTITIOUS_BATCH_SIZE": cementitious_batch_size(),
        "CEMENTITIOUS_MAX_IN_FLIGHT": cementitious_max_in_flight(),
        "CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB": os.getenv("CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB", ""),
        "CEMENTITIOUS_SOFT_MEMORY_THRESHOLD": soft_memory_threshold_fraction(),
        "CEMENTITIOUS_MAX_RECORDS": os.getenv("CEMENTITIOUS_MAX_RECORDS", ""),
        "CEMENTITIOUS_STAGE": os.getenv("CEMENTITIOUS_STAGE", ""),
    }
    log.info("Cementitious concurrency/memory settings: %s", payload)
    return payload


def start_stage_telemetry(
    stage: str,
    *,
    shard_id: int | None = None,
    input_record_count: int | None = None,
    shard_path: str | Path | None = None,
) -> MemoryTelemetry:
    apply_stage_soft_limit(stage)
    profile = STAGE_MEMORY_PROFILES[stage]
    shard_bytes = None
    if shard_path and Path(shard_path).is_file():
        shard_bytes = Path(shard_path).stat().st_size
    tel = MemoryTelemetry(
        stage=stage,
        shard_id=shard_id,
        input_record_count=input_record_count,
        shard_file_bytes=shard_bytes,
        worker_count=cementitious_workers(),
        batch_size=cementitious_batch_size(),
        requested_mem_gb=profile.mem_gb,
        soft_limit_gb=profile.soft_limit_gb,
    )
    tel.snapshot("startup")
    log_concurrency_settings()
    return tel


def finish_stage_telemetry(
    telemetry: MemoryTelemetry,
    output_dir: str | Path,
    *,
    status: str = "complete",
    records_processed: int | None = None,
) -> Path:
    telemetry.status = status
    if records_processed is not None:
        telemetry.records_processed = records_processed
    telemetry.snapshot("complete" if status == "complete" else status)
    out = Path(output_dir)
    logs = out / "logs" / "resource_telemetry"
    logs.mkdir(parents=True, exist_ok=True)
    shard = telemetry.shard_id
    suffix = f"_shard_{shard:05d}" if shard is not None else ""
    job = os.getenv("SLURM_JOB_ID") or "local"
    path = logs / f"{telemetry.stage}{suffix}_job_{job}.json"
    telemetry.write(path)
    # Also append a one-line JSONL index for consolidation.
    index = logs / "telemetry_index.jsonl"
    with index.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "path": str(path),
                    "stage": telemetry.stage,
                    "shard_id": telemetry.shard_id,
                    "peak_rss_mb": telemetry.as_dict()["peak_rss_mb"],
                    "status": telemetry.status,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return path


def stage_profiles_public() -> dict[str, Any]:
    return {
        name: {
            **asdict(profile),
            "soft_limit_gb": profile.soft_limit_gb,
            "mem_slurm": profile.mem_slurm,
        }
        for name, profile in STAGE_MEMORY_PROFILES.items()
    }
