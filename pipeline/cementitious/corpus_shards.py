"""One-time corpus → record-shard materialization for memory-safe screening.

Array screen tasks must read only their shard JSONL file and must not call
``pickle.load`` on the full corpus.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pipeline.cementitious.shard_io import (
    atomic_write_json,
    ensure_shard_layout,
    iter_jsonl,
    write_marker,
    zero_pad_shard_id,
)
from pipeline.cluster_shards import plan_corpus_shards
from pipeline.corpus_loader import load_paper_records, resolve_pickle_path
from pipeline.record_utils import record_dedupe_key

logger = logging.getLogger(__name__)

CORPUS_SHARD_SCHEMA_VERSION = "cementitious-corpus-shards-v1"

# Minimal fields required for literature screening + later joins.
SCREENING_RECORD_FIELDS: tuple[str, ...] = (
    "corpus_index",
    "source_record_id",
    "title",
    "abstract",
    "doi",
    "url",
    "year",
    "publication_year",
    "authors",
)


class CorpusShardError(RuntimeError):
    pass


def corpus_fingerprint(path: Path) -> dict[str, Any]:
    """Stable non-secret fingerprint (size + mtime + path); optional partial hash."""
    path = Path(path)
    st = path.stat()
    # Hash only the first 1 MiB + last 1 MiB + size to avoid reading 5.5GB.
    h = hashlib.sha256()
    size = st.st_size
    with path.open("rb") as handle:
        head = handle.read(1024 * 1024)
        h.update(head)
        if size > 2 * 1024 * 1024:
            handle.seek(max(0, size - 1024 * 1024))
            h.update(handle.read(1024 * 1024))
        h.update(str(size).encode("ascii"))
    return {
        "path": str(path.resolve()),
        "size_bytes": size,
        "mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
        "partial_sha256": h.hexdigest(),
    }


def _sample_indices(n: int, sample_size: int, seed: int) -> list[int]:
    """Deterministic sample of corpus indices (sorted for stable shard order)."""
    if sample_size >= n:
        return list(range(n))
    rng = random.Random(seed)
    return sorted(rng.sample(range(n), sample_size))


def resolve_sample_seed() -> int:
    raw = (
        os.getenv("CEMENTITIOUS_SAMPLE_SEED")
        or os.getenv("SAMPLE_SEED")
        or "42"
    ).strip()
    try:
        return int(raw)
    except ValueError:
        return 42


def _project_record(record: dict[str, Any], corpus_index: int) -> dict[str, Any]:
    year = record.get("year") or record.get("publication_year") or ""
    return {
        "corpus_index": corpus_index,
        "source_record_id": record_dedupe_key(record) or f"paper:{corpus_index}",
        "title": str(record.get("title") or ""),
        "abstract": str(record.get("abstract") or ""),
        "doi": str(record.get("doi") or ""),
        "url": str(record.get("url") or ""),
        "year": year,
        "publication_year": record.get("publication_year") or year,
        "authors": record.get("authors") or [],
    }


def corpus_shards_dir(output_dir: Path) -> Path:
    path = Path(output_dir) / "metadata" / "corpus_shards"
    path.mkdir(parents=True, exist_ok=True)
    return path


def corpus_shards_manifest_path(output_dir: Path) -> Path:
    return Path(output_dir) / "metadata" / "corpus_shards_manifest.json"


def corpus_shards_complete_marker(output_dir: Path) -> Path:
    return Path(output_dir) / "checkpoints" / "corpus_shards.complete"


def _write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return count


def validate_corpus_shard_file(path: Path, *, expected_count: int | None = None) -> int:
    if not path.is_file():
        raise CorpusShardError(f"Missing corpus shard file: {path}")
    count = 0
    for row in iter_jsonl(path):
        for key in ("corpus_index", "source_record_id", "title"):
            if key not in row:
                raise CorpusShardError(f"Corpus shard {path} missing field {key}")
        count += 1
    if expected_count is not None and count != expected_count:
        raise CorpusShardError(
            f"Corpus shard {path} has {count} rows; expected {expected_count}"
        )
    return count


def load_corpus_shards_manifest(output_dir: Path) -> dict[str, Any] | None:
    path = corpus_shards_manifest_path(output_dir)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def corpus_shards_are_valid(
    output_dir: Path,
    *,
    fingerprint: dict[str, Any],
    shard_size: int,
    total_records: int | None = None,
) -> bool:
    manifest = load_corpus_shards_manifest(output_dir)
    marker = corpus_shards_complete_marker(output_dir)
    if not manifest or not marker.is_file():
        return False
    if manifest.get("schema_version") != CORPUS_SHARD_SCHEMA_VERSION:
        return False
    if int(manifest.get("shard_size") or 0) != int(shard_size):
        return False
    fp = manifest.get("corpus_fingerprint") or {}
    for key in ("path", "size_bytes", "partial_sha256"):
        if fp.get(key) != fingerprint.get(key):
            return False
    if total_records is not None and int(manifest.get("record_count") or -1) != total_records:
        return False
    try:
        for shard in manifest.get("shards") or []:
            validate_corpus_shard_file(
                Path(shard["record_shard_path"]),
                expected_count=int(shard["paper_count"]),
            )
    except CorpusShardError as exc:
        logger.warning("Corpus shard validation failed: %s", exc)
        return False
    return True


def materialize_corpus_shards(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    shard_size: int,
    max_records: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Load the pickle once and write screening-oriented JSONL shards.

    This is the only Engaging stage that should deserialize the full corpus.
    """
    out = Path(output_dir)
    ensure_shard_layout(out)
    resolved = resolve_pickle_path(input_path, announce=True)
    fingerprint = corpus_fingerprint(resolved)

    # Bound pilot size without requiring a second architecture.
    env_max = os.getenv("CEMENTITIOUS_MAX_RECORDS", "").strip()
    if max_records is None and env_max:
        max_records = int(env_max)
    sample_seed = resolve_sample_seed() if max_records is not None else None

    if not force and corpus_shards_are_valid(
        out, fingerprint=fingerprint, shard_size=shard_size
    ):
        manifest = load_corpus_shards_manifest(out)
        assert manifest is not None
        if (
            manifest.get("max_records_applied") == max_records
            and manifest.get("sample_seed") == sample_seed
        ):
            logger.info("Reusing validated corpus shards under %s", corpus_shards_dir(out))
            return manifest

    logger.info("Materializing corpus shards from %s (full pickle load once)", resolved)
    all_records = load_paper_records(resolved)
    original_n = len(all_records)
    if max_records is not None:
        indices = _sample_indices(original_n, int(max_records), int(sample_seed or 42))
        sampled = [(i, all_records[i]) for i in indices]
        del all_records
        all_records = None  # type: ignore[assignment]
        total = len(sampled)
    else:
        sampled = [(i, rec) for i, rec in enumerate(all_records)]
        del all_records
        all_records = None  # type: ignore[assignment]
        total = len(sampled)

    if shard_size <= 0:
        raise CorpusShardError("shard_size must be positive")

    shard_plan = plan_corpus_shards(total, shard_size)
    shards_dir = corpus_shards_dir(out)
    shard_entries: list[dict[str, Any]] = []

    for cs in shard_plan:
        pad = zero_pad_shard_id(cs.index)
        shard_path = shards_dir / f"corpus_shard_{pad}.jsonl"
        rows = (
            _project_record(sampled[i][1], sampled[i][0])
            for i in range(cs.start, cs.end)
        )
        written = _write_jsonl_atomic(shard_path, rows)
        if written != (cs.end - cs.start):
            raise CorpusShardError(
                f"Shard {cs.index}: wrote {written}; expected {cs.end - cs.start}"
            )
        validate_corpus_shard_file(shard_path, expected_count=written)
        shard_entries.append(
            {
                "shard_id": cs.index,
                "start_index": cs.start,
                "end_index_exclusive": cs.end,
                "paper_count": written,
                "record_shard_path": str(shard_path),
                "record_shard_bytes": shard_path.stat().st_size,
            }
        )

    # Drop sampled corpus from this scope and clear the process-wide cache.
    del sampled
    import pipeline.corpus_loader as corpus_loader

    corpus_loader._cached_records = None
    corpus_loader._cached_path = None

    manifest = {
        "schema_version": CORPUS_SHARD_SCHEMA_VERSION,
        "status": "complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_fingerprint": fingerprint,
        "input_corpus_path": str(resolved),
        "shard_size": shard_size,
        "record_count": total,
        "source_corpus_record_count": original_n,
        "max_records_applied": max_records,
        "sample_seed": sample_seed,
        "sampling": (
            "deterministic_rng_sample" if max_records is not None else "full_corpus"
        ),
        "shard_count": len(shard_entries),
        "required_fields": list(SCREENING_RECORD_FIELDS),
        "shards": shard_entries,
    }
    atomic_write_json(corpus_shards_manifest_path(out), manifest)
    write_marker(corpus_shards_complete_marker(out))
    return manifest


def read_corpus_shard_records(shard_path: str | Path) -> list[dict[str, Any]]:
    """Load one corpus shard JSONL into memory (bounded by shard size)."""
    path = Path(shard_path)
    validate_corpus_shard_file(path)
    return list(iter_jsonl(path))
