"""Atomic I/O and shard path helpers for Cementitious Materials cluster stages."""

from __future__ import annotations

import csv
import json
import os
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def zero_pad_shard_id(shard_id: int, width: int = 5) -> str:
    if shard_id < 0:
        raise ValueError(f"Invalid shard_id: {shard_id}")
    return f"{shard_id:0{width}d}"


def atomic_write_text(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return path


def atomic_write_json(path: Path, payload: Any) -> Path:
    return atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def atomic_write_csv(
    path: Path,
    fieldnames: tuple[str, ...] | list[str],
    rows: Iterable[dict[str, Any]],
) -> Path:
    """Write a CSV via temp-file + os.replace so a crash cannot leave a truncated file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".csv", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(fieldnames),
                extrasaction="ignore",
                quoting=csv.QUOTE_MINIMAL,
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return path


def atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return path


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Stream JSONL rows without materializing the full file."""
    path = Path(path)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSONL at {path}:{line_no}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL row must be object at {path}:{line_no}")
            yield payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


def append_jsonl_row(path: Path, row: dict[str, Any], *, flush: bool = True) -> None:
    """Append one JSON object as a line (caller manages resume/partial files)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if flush:
            handle.flush()


def write_marker(path: Path, *, payload: str | None = None) -> Path:
    text = payload or datetime.now(timezone.utc).isoformat()
    return atomic_write_text(path, text + ("\n" if not text.endswith("\n") else ""))


def slurm_meta() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "slurm_job_id": os.getenv("SLURM_JOB_ID", ""),
        "slurm_array_job_id": os.getenv("SLURM_ARRAY_JOB_ID", ""),
        "slurm_array_task_id": os.getenv("SLURM_ARRAY_TASK_ID", ""),
    }


def array_range_from_count(n: int) -> str:
    """Return Slurm --array range for n shards (0-based). Empty string if n==0."""
    if n <= 0:
        return ""
    if n == 1:
        return "0"
    return f"0-{n - 1}"


def compact_id_list(ids: list[int]) -> str:
    """Compact sorted ids into Slurm-friendly specs like 3,7,11-14."""
    if not ids:
        return ""
    ordered = sorted(set(ids))
    ranges: list[str] = []
    start = prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = value
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(ranges)


def ensure_shard_layout(output_dir: Path) -> dict[str, Path]:
    root = Path(output_dir)
    layout = {
        "root": root,
        "metadata": root / "metadata",
        "checkpoints": root / "checkpoints",
        "rejected": root / "rejected_records",
        "logs": root / "logs",
        "screening_shards": root / "metadata" / "screening_shards",
        "screen_markers": root / "checkpoints" / "screen_shards",
        "extraction_shards": root / "metadata" / "extraction_shards",
        "extract_markers": root / "checkpoints" / "extraction_shards",
        "failed_llm": root / "logs" / "failed_llm_responses",
    }
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    return layout
