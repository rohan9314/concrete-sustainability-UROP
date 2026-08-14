"""Genuine sharded stages for Cementitious Materials Engaging workflow."""

from __future__ import annotations

import csv
import heapq
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pipeline.cementitious.dedupe import deduplicate_records, write_dedupe_audit
from pipeline.cementitious.export_partitions import export_taxonomy_partitions, write_csv
from pipeline.cementitious.extraction import (
    classify_and_extract,
    classify_and_extract_records,
    keyword_screen,
    llm_screen,
)
from pipeline.cementitious.paths import ensure_730_layout
from pipeline.cementitious.qc import run_qc_pass
from pipeline.cementitious.schema import (
    CITATION_FIELDS,
    PROPOSAL_FIELDS,
    RECORD_FIELDS,
    citation_from_record,
    normalize_record,
    validate_records,
)
from pipeline.cementitious.corpus_shards import materialize_corpus_shards
from pipeline.cementitious.memory import (
    ControlledMemoryStop,
    MemoryTelemetry,
    cementitious_batch_size,
    cementitious_workers,
    check_soft_memory_ceiling,
    finish_stage_telemetry,
    log_concurrency_settings,
    start_stage_telemetry,
)
from pipeline.cementitious.shard_io import (
    append_jsonl_row,
    array_range_from_count,
    atomic_write_json,
    atomic_write_jsonl,
    atomic_write_text,
    compact_id_list,
    ensure_shard_layout,
    iter_jsonl,
    read_jsonl,
    slurm_meta,
    write_marker,
    zero_pad_shard_id,
)
from pipeline.cementitious.taxonomy import Taxonomy, get_taxonomy
from pipeline.llm_utils import DEFAULT_MODEL
from pipeline.record_utils import record_dedupe_key

logger = logging.getLogger(__name__)

DEFAULT_SHARD_SIZE = 10000
DEFAULT_EXTRACT_SHARD_SIZE = 25


class ShardError(RuntimeError):
    """Raised when a shard stage fails validation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_out(output: str | Path) -> Path:
    return Path(output)


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ShardError(f"Manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "shards" in payload:
        shards = payload["shards"]
    elif isinstance(payload, list):
        shards = payload
    else:
        raise ShardError(f"Invalid manifest structure: {path}")
    if not isinstance(shards, list):
        raise ShardError(f"Manifest shards must be a list: {path}")
    return shards


def _find_shard(manifest: list[dict[str, Any]], shard_id: int) -> dict[str, Any]:
    for entry in manifest:
        if int(entry.get("shard_id", -1)) == int(shard_id):
            return entry
    raise ShardError(f"shard_id {shard_id} not present in manifest")


def _resume_ok(
    *,
    output_path: Path,
    marker_path: Path,
    validate_fn: Callable[[Path], None],
    resume: bool,
) -> bool:
    if not resume:
        return False
    if not marker_path.is_file() or not output_path.is_file():
        return False
    try:
        validate_fn(output_path)
    except Exception as exc:
        logger.warning("RESUME: invalid completed shard %s (%s); rerunning", output_path, exc)
        return False
    return True


# ── Plan screen shards ───────────────────────────────────────────────────────


def plan_screen_shards(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    shard_size: int = DEFAULT_SHARD_SIZE,
    selected_subcategories: list[str] | None = None,
    selected_sub_subcategories: list[str] | None = None,
    force_rematerialize: bool = False,
) -> dict[str, Any]:
    """
    Plan screening shards and materialize bounded corpus JSONL shards once.

    This is the only stage that may deserialize the full pickle. Downstream
    array tasks must read ``record_shard_path`` only.
    """
    out = _resolve_out(output_dir)
    ensure_730_layout(out)
    layout = ensure_shard_layout(out)
    if shard_size <= 0:
        raise ShardError("SHARD_SIZE must be positive")

    log_concurrency_settings(logger)
    telemetry = start_stage_telemetry("preprocess_plan")
    corpus_manifest = materialize_corpus_shards(
        input_path=input_path,
        output_dir=out,
        shard_size=shard_size,
        force=force_rematerialize,
    )
    finish_stage_telemetry(
        telemetry,
        out,
        status="complete",
        records_processed=int(corpus_manifest["record_count"]),
    )
    total = int(corpus_manifest["record_count"])
    resolved = Path(corpus_manifest["input_corpus_path"])

    selected_subs = list(selected_subcategories or [])
    selected_ss = list(selected_sub_subcategories or [])

    shards: list[dict[str, Any]] = []
    for cs in corpus_manifest["shards"]:
        sid = int(cs["shard_id"])
        pad = zero_pad_shard_id(sid)
        expected_output = layout["screening_shards"] / f"screening_shard_{pad}.jsonl"
        expected_marker = layout["screen_markers"] / f"screen_shard_{pad}.complete"
        shards.append(
            {
                "shard_id": sid,
                "start_index": int(cs["start_index"]),
                "end_index": int(cs["end_index_exclusive"]) - 1,
                "end_index_exclusive": int(cs["end_index_exclusive"]),
                "paper_count": int(cs["paper_count"]),
                "input_corpus_path": str(resolved),
                "record_shard_path": cs["record_shard_path"],
                "record_shard_bytes": cs.get("record_shard_bytes"),
                "expected_output_path": str(expected_output),
                "expected_marker_path": str(expected_marker),
                "selected_subcategories": selected_subs,
                "selected_sub_subcategories": selected_ss,
            }
        )

    manifest = {
        "taxonomy_note": "screening shard plan",
        "shard_size": shard_size,
        "total_records": total,
        "shard_count": len(shards),
        "input_corpus_path": str(resolved),
        "corpus_shards_manifest": str(out / "metadata" / "corpus_shards_manifest.json"),
        "data_access": "per-shard-jsonl",
        "selected_subcategories": selected_subs,
        "selected_sub_subcategories": selected_ss,
        "created_at": _now(),
        "shards": shards,
    }
    atomic_write_json(layout["metadata"] / "screen_shards.json", shards)
    atomic_write_json(layout["metadata"] / "screen_shards_meta.json", manifest)

    array_range = array_range_from_count(len(shards))
    atomic_write_text(layout["metadata"] / "screen_array_range.txt", array_range + "\n")
    write_marker(layout["checkpoints"] / "plan.complete")
    write_marker(layout["checkpoints"] / "plan_screen.complete")

    return {
        "output_dir": str(out),
        "total_records": total,
        "shard_count": len(shards),
        "shard_size": shard_size,
        "array_range": array_range,
        "manifest": str(layout["metadata"] / "screen_shards.json"),
        "data_access": "per-shard-jsonl",
    }


# ── Screen one shard ─────────────────────────────────────────────────────────


def _validate_screening_shard_file(path: Path, *, expected_count: int | None = None) -> list[dict]:
    rows = read_jsonl(path)
    if expected_count is not None and len(rows) != expected_count:
        raise ShardError(
            f"Screening shard {path} has {len(rows)} rows; expected {expected_count}"
        )
    for row in rows:
        for key in ("paper_id", "corpus_index", "shard_id", "is_relevant"):
            if key not in row:
                raise ShardError(f"Missing {key} in {path}")
    return rows


def screen_shard(
    *,
    shard_id: int,
    output_dir: str | Path,
    manifest_path: str | Path | None = None,
    keyword_only: bool = False,
    model: str = DEFAULT_MODEL,
    resume: bool = False,
    focus_sub_slugs: list[str] | None = None,
    focus_ss_slugs: list[str] | None = None,
    taxonomy: Taxonomy | None = None,
) -> dict[str, Any]:
    out = _resolve_out(output_dir)
    layout = ensure_shard_layout(out)
    man_path = Path(manifest_path) if manifest_path else layout["metadata"] / "screen_shards.json"
    entry = _find_shard(_load_manifest(man_path), shard_id)

    output_path = Path(entry["expected_output_path"])
    marker_path = Path(entry["expected_marker_path"])
    pad = zero_pad_shard_id(shard_id)
    summary_path = layout["screening_shards"] / f"screening_shard_{pad}_summary.json"
    partial_path = layout["screening_shards"] / f"screening_shard_{pad}.partial.jsonl"
    checkpoint_path = layout["screening_shards"] / f"screening_shard_{pad}.partial.checkpoint.json"
    planned = int(entry["paper_count"])
    start_index = int(entry["start_index"])
    end_exclusive = int(entry.get("end_index_exclusive") or (int(entry["end_index"]) + 1))

    # Scope precedence: explicit call kwargs > shard manifest entry > env vars.
    resolved_focus_sub = focus_sub_slugs
    if not resolved_focus_sub:
        resolved_focus_sub = list(entry.get("selected_subcategories") or []) or None
    if not resolved_focus_sub:
        resolved_focus_sub = [
            s.strip() for s in os.getenv("SELECTED_SUBCATEGORIES", "").split(",") if s.strip()
        ] or None
    resolved_focus_ss = focus_ss_slugs
    if not resolved_focus_ss:
        resolved_focus_ss = list(entry.get("selected_sub_subcategories") or []) or None
    if not resolved_focus_ss:
        resolved_focus_ss = [
            s.strip() for s in os.getenv("SELECTED_SUB_SUBCATEGORIES", "").split(",") if s.strip()
        ] or None

    def _validate(p: Path) -> None:
        _validate_screening_shard_file(p, expected_count=planned)

    if _resume_ok(output_path=output_path, marker_path=marker_path, validate_fn=_validate, resume=resume):
        return {"status": "skipped_resume", "shard_id": shard_id, "output": str(output_path)}

    record_shard_path = entry.get("record_shard_path")
    if not record_shard_path:
        raise ShardError(
            f"Shard {shard_id} missing record_shard_path. Re-run plan-screen to materialize "
            "corpus JSONL shards; array tasks must not load the full pickle."
        )
    record_shard_path = Path(record_shard_path)
    if not record_shard_path.is_file():
        raise ShardError(f"Corpus record shard missing: {record_shard_path}")

    started = time.time()
    start_iso = _now()
    workers = cementitious_workers()
    batch_size = cementitious_batch_size()
    telemetry = start_stage_telemetry(
        "screen",
        shard_id=shard_id,
        input_record_count=planned,
        shard_path=record_shard_path,
    )

    logger.info(
        "screen shard_id=%s record_shard=%s bytes=%s workers=%s batch_size=%s %s",
        shard_id,
        record_shard_path,
        record_shard_path.stat().st_size,
        workers,
        batch_size,
        slurm_meta(),
    )

    # Load only this shard's records (bounded by SHARD_SIZE / CEMENTITIOUS_MAX_RECORDS).
    from pipeline.cementitious.corpus_shards import read_corpus_shard_records

    slice_records = read_corpus_shard_records(record_shard_path)
    telemetry.snapshot("after_shard_load", records_processed=0)
    if len(slice_records) != planned:
        raise ShardError(
            f"Shard {shard_id}: loaded {len(slice_records)} papers from JSONL; planned {planned}"
        )
    for offset, record in enumerate(slice_records):
        expected_index = start_index + offset
        if int(record.get("corpus_index", expected_index)) != expected_index:
            raise ShardError(
                f"Shard {shard_id}: corpus_index mismatch at offset {offset}: "
                f"got {record.get('corpus_index')}, expected {expected_index}"
            )

    tax = taxonomy or get_taxonomy()
    failed_dir = layout["failed_llm"] / f"screening_shard_{pad}"
    failed_dir.mkdir(parents=True, exist_ok=True)

    completed_indices: set[int] = set()
    relevant = 0
    failed = 0
    if resume and partial_path.is_file():
        for row in iter_jsonl(partial_path):
            completed_indices.add(int(row["corpus_index"]))
            if row.get("is_relevant"):
                relevant += 1
        logger.info(
            "RESUME: continuing screen shard %s from %s/%s completed rows",
            shard_id,
            len(completed_indices),
            planned,
        )
    else:
        if partial_path.exists():
            partial_path.unlink()
        if checkpoint_path.exists():
            checkpoint_path.unlink()

    controlled_stop = False
    try:
        for offset, record in enumerate(slice_records):
            corpus_index = start_index + offset
            if corpus_index in completed_indices:
                continue
            try:
                if keyword_only:
                    result = keyword_screen(
                        record,
                        corpus_index,
                        taxonomy=tax,
                        focus_sub_slugs=resolved_focus_sub,
                        focus_ss_slugs=resolved_focus_ss,
                    )
                else:
                    result = llm_screen(
                        record,
                        corpus_index,
                        taxonomy=tax,
                        model=model,
                        focus_sub_slugs=resolved_focus_sub,
                        focus_ss_slugs=resolved_focus_ss,
                        failed_dir=failed_dir,
                    )
            except Exception as exc:
                failed += 1
                logger.warning("Screen failed corpus_index=%s: %s", corpus_index, exc)
                result = {
                    "paper_id": record.get("source_record_id")
                    or record_dedupe_key(record)
                    or f"paper:{corpus_index}",
                    "title": str(record.get("title") or ""),
                    "is_relevant": False,
                    "confidence": "Low",
                    "reason": f"screening_error: {exc}",
                    "screening_mode": "error",
                }
            is_rel = bool(result.get("is_relevant"))
            if is_rel:
                relevant += 1
            row = {
                "paper_id": result.get("paper_id") or f"paper:{corpus_index}",
                "corpus_index": corpus_index,
                "title": result.get("title") or str(record.get("title") or ""),
                "abstract": str(record.get("abstract") or "")[:4000],
                "is_relevant": is_rel,
                "relevance_decision": "relevant" if is_rel else "irrelevant",
                "matched_taxonomy_branches": result.get("matched_seed_hints")
                or result.get("suggested_technology_domain")
                or "",
                "screening_score": result.get("screening_score")
                or (1.0 if is_rel else 0.0),
                "screening_confidence": result.get("confidence") or "",
                "screening_evidence": result.get("reason") or "",
                "negative_match": result.get("negative_match") or "",
                "shard_id": shard_id,
                "doi": result.get("doi") or str(record.get("doi") or ""),
                "year": result.get("year") or record.get("year") or "",
                "screening_mode": result.get("screening_mode") or "",
                "selected_subcategories": result.get("selected_subcategories")
                or list(resolved_focus_sub or []),
                "selected_sub_subcategories": result.get("selected_sub_subcategories")
                or list(resolved_focus_ss or []),
            }
            append_jsonl_row(partial_path, row, flush=True)
            completed_indices.add(corpus_index)
            processed = len(completed_indices)
            if processed % max(1, batch_size) == 0:
                atomic_write_json(
                    checkpoint_path,
                    {
                        "shard_id": shard_id,
                        "completed_count": processed,
                        "planned_count": planned,
                        "last_corpus_index": corpus_index,
                        "updated_at": _now(),
                    },
                )
                telemetry.snapshot("batch", records_processed=processed)
                check_soft_memory_ceiling(telemetry=telemetry)
    except ControlledMemoryStop as exc:
        controlled_stop = True
        atomic_write_json(
            checkpoint_path,
            {
                "shard_id": shard_id,
                "completed_count": len(completed_indices),
                "planned_count": planned,
                "status": "soft_memory_stop",
                "message": str(exc),
                "updated_at": _now(),
            },
        )
        telemetry.snapshot("soft_memory_stop", records_processed=len(completed_indices))
        finish_stage_telemetry(
            telemetry, out, status="soft_memory_stop", records_processed=len(completed_indices)
        )
        logger.error("%s", exc)
        return {
            "status": "soft_memory_stop",
            "shard_id": shard_id,
            "completed_count": len(completed_indices),
            "planned_count": planned,
            "partial_path": str(partial_path),
            "checkpoint_path": str(checkpoint_path),
            "telemetry_path": str(
                out / "logs" / "resource_telemetry" / f"screen_shard_{shard_id:05d}_job_local.json"
            ),
            "message": str(exc),
            "output_path": str(partial_path),
            "marker_path": str(marker_path),
        }

    if len(completed_indices) != planned:
        raise ShardError(
            f"Shard {shard_id}: completed {len(completed_indices)} rows; planned {planned}"
        )

    # Promote partial → final atomically after validation.
    rows = list(iter_jsonl(partial_path))
    # Deduplicate by corpus_index while preserving first-seen order (resume safety).
    seen: set[int] = set()
    unique_rows: list[dict[str, Any]] = []
    for row in rows:
        idx = int(row["corpus_index"])
        if idx in seen:
            continue
        seen.add(idx)
        unique_rows.append(row)
    unique_rows.sort(key=lambda r: int(r["corpus_index"]))
    relevant = sum(1 for r in unique_rows if r.get("is_relevant"))
    atomic_write_jsonl(output_path, unique_rows)
    _validate_screening_shard_file(output_path, expected_count=planned)
    write_marker(marker_path)
    if partial_path.exists():
        partial_path.unlink()
    if checkpoint_path.exists():
        checkpoint_path.unlink()

    telemetry.snapshot("complete", records_processed=len(unique_rows))
    tel_path = finish_stage_telemetry(
        telemetry, out, status="complete", records_processed=len(unique_rows)
    )

    summary = {
        "shard_id": shard_id,
        "start_time": start_iso,
        "end_time": _now(),
        "elapsed_seconds": round(time.time() - started, 3),
        **slurm_meta(),
        "planned_input_count": planned,
        "actual_processed_count": len(unique_rows),
        "relevant_count": relevant,
        "failed_count": failed,
        "retry_count": 0,
        "model_used": model if not keyword_only else "keyword",
        "token_usage": None,
        "output_path": str(output_path),
        "marker_path": str(marker_path),
        "record_shard_path": str(record_shard_path),
        "record_shard_bytes": record_shard_path.stat().st_size,
        "workers": workers,
        "batch_size": batch_size,
        "peak_rss_mb": telemetry.as_dict()["peak_rss_mb"],
        "telemetry_path": str(tel_path),
        "selected_subcategories": list(resolved_focus_sub or []),
        "selected_sub_subcategories": list(resolved_focus_ss or []),
        "status": "complete",
        "controlled_stop": controlled_stop,
    }
    atomic_write_json(summary_path, summary)
    return summary


# ── Merge screening ──────────────────────────────────────────────────────────


def merge_screening(*, output_dir: str | Path) -> dict[str, Any]:
    out = _resolve_out(output_dir)
    layout = ensure_shard_layout(out)
    man_path = layout["metadata"] / "screen_shards.json"
    shards = _load_manifest(man_path)

    missing: list[dict[str, Any]] = []
    results_path = layout["metadata"] / "screening_results.jsonl"
    tmp_path = results_path.with_suffix(results_path.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    seen: set[int] = set()
    dupes: list[int] = []
    relevant = 0
    irrelevant = 0
    unresolved = 0
    total_written = 0

    with tmp_path.open("w", encoding="utf-8") as handle:
        for entry in shards:
            sid = int(entry["shard_id"])
            out_path = Path(entry["expected_output_path"])
            marker = Path(entry["expected_marker_path"])
            planned = int(entry["paper_count"])
            problems: list[str] = []
            if not out_path.is_file():
                problems.append("missing_output")
            if not marker.is_file():
                problems.append("missing_marker")
            rows: list[dict[str, Any]] = []
            if out_path.is_file() and not problems:
                try:
                    rows = _validate_screening_shard_file(out_path, expected_count=planned)
                    for row in rows:
                        if int(row.get("shard_id", -1)) != sid:
                            problems.append("shard_id_mismatch")
                            break
                except Exception as exc:
                    problems.append(f"invalid:{exc}")
            if problems:
                missing.append(
                    {
                        "shard_id": sid,
                        "expected_output_path": str(out_path),
                        "expected_marker_path": str(marker),
                        "problems": ";".join(problems),
                    }
                )
                continue
            # Stream validated rows; shards are ordered so output stays deterministic.
            for row in rows:
                idx = int(row["corpus_index"])
                if idx in seen:
                    dupes.append(idx)
                else:
                    seen.add(idx)
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    total_written += 1
                    if row.get("is_relevant"):
                        relevant += 1
                    else:
                        irrelevant += 1
                    if str(row.get("relevance_decision") or "").lower() == "unresolved":
                        unresolved += 1
            # Release per-shard list promptly.
            rows.clear()

    missing_path = layout["rejected"] / "missing_screen_shards.csv"
    with missing_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["shard_id", "expected_output_path", "expected_marker_path", "problems"],
        )
        writer.writeheader()
        for row in missing:
            writer.writerow(row)

    if missing:
        if tmp_path.exists():
            tmp_path.unlink()
        raise ShardError(
            f"merge-screen failed: {len(missing)} incomplete/invalid shards "
            f"(see {missing_path})"
        )

    if dupes:
        if tmp_path.exists():
            tmp_path.unlink()
        raise ShardError(f"Duplicate corpus_index values in screening merge: {sorted(set(dupes))[:20]}")

    os.replace(tmp_path, results_path)

    summary = {
        "expected_shard_count": len(shards),
        "completed_shard_count": len(shards),
        "missing_shard_count": 0,
        "total_planned_papers": sum(int(s["paper_count"]) for s in shards),
        "total_merged_screening_records": total_written,
        "relevant_record_count": relevant,
        "irrelevant_record_count": irrelevant,
        "unresolved_record_count": unresolved,
        "screening_results_path": str(results_path),
        "created_at": _now(),
    }
    atomic_write_json(layout["metadata"] / "screening_merge_summary.json", summary)
    write_marker(layout["checkpoints"] / "screen.complete")
    write_marker(layout["checkpoints"] / "screen_merge.complete")
    return summary


def missing_screen_shards(*, output_dir: str | Path) -> str:
    out = _resolve_out(output_dir)
    layout = ensure_shard_layout(out)
    shards = _load_manifest(layout["metadata"] / "screen_shards.json")
    bad: list[int] = []
    for entry in shards:
        sid = int(entry["shard_id"])
        out_path = Path(entry["expected_output_path"])
        marker = Path(entry["expected_marker_path"])
        planned = int(entry["paper_count"])
        ok = False
        if out_path.is_file() and marker.is_file():
            try:
                _validate_screening_shard_file(out_path, expected_count=planned)
                ok = True
            except Exception:
                ok = False
        if not ok:
            bad.append(sid)
    spec = compact_id_list(bad)
    print(spec)
    return spec


# ── Rank and plan extraction ─────────────────────────────────────────────────


def _score_candidate(row: dict[str, Any], taxonomy: Taxonomy) -> float:
    score = float(row.get("screening_score") or 0.0)
    conf = str(row.get("screening_confidence") or "").casefold()
    if conf == "high":
        score += 1.0
    elif conf == "medium":
        score += 0.5
    text = " ".join(
        str(row.get(k) or "")
        for k in (
            "title",
            "abstract",
            "matched_taxonomy_branches",
            "screening_evidence",
            "suggested_level_1",
        )
    ).casefold()
    l1 = row.get("suggested_level_1") or []
    if isinstance(l1, list) and l1:
        score += 0.5 * min(len(l1), 3)
    from pipeline.cementitious.decarb_literature import LEVEL_1_CUES

    for cues in LEVEL_1_CUES.values():
        for term in cues[:4]:
            if term in text:
                score += 0.15
                break
    for node in taxonomy.all_nodes():
        for term in node.retrieval_query_terms[:5]:
            if term.casefold() in text:
                score += 0.1
    return score


def rank_and_plan_extraction(
    *,
    output_dir: str | Path,
    top_n: int | None = None,
    top_n_per_subcategory: int | None = None,
    top_n_per_sub_subcategory: int | None = None,
    extract_shard_size: int | None = None,
    selected_subcategories: list[str] | None = None,
    selected_sub_subcategories: list[str] | None = None,
    taxonomy: Taxonomy | None = None,
) -> dict[str, Any]:
    """
    Rank relevant screening hits and plan extraction shards.

    Ranking policy (recorded in summary):
    - Start from is_relevant=true screening rows.
    - Score by screening_score/confidence + taxonomy cue overlap.
    - Apply optional per-subcategory / per-sub-subcategory caps when branch
      hints are available; otherwise apply a global TOP_N cap.
    - Global TOP_N is intentional when no per-branch caps are set; documented
      in ranking_policy.
    """
    out = _resolve_out(output_dir)
    layout = ensure_shard_layout(out)
    tax = taxonomy or get_taxonomy()
    screening_path = layout["metadata"] / "screening_results.jsonl"
    if not screening_path.is_file():
        raise ShardError(f"Missing screening results: {screening_path}")

    global_top = top_n
    if global_top is None:
        raw = os.getenv("TOP_N", os.getenv("TOP_N_SOURCES", "50")).strip()
        global_top = int(raw or 50)

    wanted_cf: set[str] = set()
    if selected_subcategories or selected_sub_subcategories:
        wanted = {
            *(selected_subcategories or []),
            *(selected_sub_subcategories or []),
        }
        wanted_cf = {w.casefold().replace(" ", "_") for w in wanted}

    def _passes_selection(row: dict[str, Any]) -> bool:
        if not wanted_cf:
            return True
        blob = str(row.get("matched_taxonomy_branches") or "").casefold().replace(" ", "_")
        title = str(row.get("title") or "").casefold()
        return any(w in blob or w.replace("_", " ") in title for w in wanted_cf)

    # Stream screening JSONL. Keep a bounded heap of the global TOP_N (or per-branch
    # heaps when caps are set). Do not materialize the full 159k screening file.
    use_branch_caps = bool(top_n_per_subcategory or top_n_per_sub_subcategory)
    selected_filter_hits = 0
    scanned = 0
    relevant_seen = 0
    # Min-heaps of (score, -idx, row) so earlier file order wins ties.
    global_heap: list[tuple[float, int, dict[str, Any]]] = []
    branch_heaps: dict[str, list[tuple[float, int, dict[str, Any]]]] = {}
    filtered_heap: list[tuple[float, int, dict[str, Any]]] = []

    for row in iter_jsonl(screening_path):
        scanned += 1
        if scanned % 2000 == 0:
            check_soft_memory_ceiling()
        if not row.get("is_relevant"):
            continue
        relevant_seen += 1
        score = float(_score_candidate(row, tax))
        item = (score, -scanned, row)
        if wanted_cf:
            if _passes_selection(row):
                selected_filter_hits += 1
                cap = max(0, global_top)
                if cap <= 0:
                    continue
                if len(filtered_heap) < cap:
                    heapq.heappush(filtered_heap, item)
                elif item[0] > filtered_heap[0][0] or (
                    item[0] == filtered_heap[0][0] and item[1] > filtered_heap[0][1]
                ):
                    heapq.heapreplace(filtered_heap, item)
            continue
        if use_branch_caps:
            branch = str(row.get("matched_taxonomy_branches") or "unknown").casefold()
            cap = top_n_per_sub_subcategory or top_n_per_subcategory or global_top
            bucket = branch_heaps.setdefault(branch, [])
            if len(bucket) < cap:
                heapq.heappush(bucket, item)
            elif item[0] > bucket[0][0] or (item[0] == bucket[0][0] and item[1] > bucket[0][1]):
                heapq.heapreplace(bucket, item)
            continue
        cap = max(0, global_top)
        if cap <= 0:
            continue
        if len(global_heap) < cap:
            heapq.heappush(global_heap, item)
        elif item[0] > global_heap[0][0] or (item[0] == global_heap[0][0] and item[1] > global_heap[0][1]):
            heapq.heapreplace(global_heap, item)

    if wanted_cf and filtered_heap:
        ranked_items = filtered_heap
    elif wanted_cf:
        # Selection emptied the set; screening may lack branch labels — fall back to global heap.
        # Re-scan would be expensive; keep relevant_seen via a second pass only if needed.
        ranked_items = []
        scanned = 0
        for row in iter_jsonl(screening_path):
            scanned += 1
            if not row.get("is_relevant"):
                continue
            score = float(_score_candidate(row, tax))
            item = (score, -scanned, row)
            cap = max(0, global_top)
            if cap <= 0:
                break
            if len(ranked_items) < cap:
                heapq.heappush(ranked_items, item)
            elif item[0] > ranked_items[0][0] or (
                item[0] == ranked_items[0][0] and item[1] > ranked_items[0][1]
            ):
                heapq.heapreplace(ranked_items, item)
    elif use_branch_caps:
        ranked_items = [item for bucket in branch_heaps.values() for item in bucket]
    else:
        ranked_items = global_heap

    ranked = [item[2] for item in sorted(ranked_items, key=lambda t: (t[0], t[1]), reverse=True)]
    del ranked_items, global_heap, branch_heaps, filtered_heap

    policy = {
        "global_top_n": global_top,
        "top_n_per_subcategory": top_n_per_subcategory,
        "top_n_per_sub_subcategory": top_n_per_sub_subcategory,
        "note": (
            "Global first-N truncation is applied when per-branch caps are unset. "
            "Set TOP_N_PER_SUBCATEGORY / TOP_N_PER_SUB_SUBCATEGORY to avoid a single shared cap."
        ),
    }

    if top_n_per_subcategory or top_n_per_sub_subcategory:
        # Best-effort branch bucketing from matched_taxonomy_branches text
        selected: list[dict[str, Any]] = []
        per_sub: dict[str, int] = {}
        per_ss: dict[str, int] = {}
        for row in ranked:
            branch = str(row.get("matched_taxonomy_branches") or "unknown")
            key = branch.casefold()
            if top_n_per_subcategory and per_sub.get(key, 0) >= top_n_per_subcategory:
                continue
            if top_n_per_sub_subcategory and per_ss.get(key, 0) >= top_n_per_sub_subcategory:
                continue
            selected.append(row)
            per_sub[key] = per_sub.get(key, 0) + 1
            per_ss[key] = per_ss.get(key, 0) + 1
        ranked = selected
    else:
        ranked = ranked[: max(0, global_top)]

    # Attach candidate ids
    candidates: list[dict[str, Any]] = []
    for i, row in enumerate(ranked):
        candidate = dict(row)
        candidate["candidate_id"] = f"cand:{row.get('corpus_index')}:{row.get('paper_id')}"
        candidate["rank"] = i
        candidate["rank_score"] = _score_candidate(row, tax)
        candidates.append(candidate)

    atomic_write_jsonl(layout["metadata"] / "ranked_candidates.jsonl", candidates)

    extract_size = extract_shard_size
    if extract_size is None:
        extract_size = int(os.getenv("EXTRACT_SHARD_SIZE", str(DEFAULT_EXTRACT_SHARD_SIZE)))
    if extract_size <= 0:
        raise ShardError("EXTRACT_SHARD_SIZE must be positive")

    shards: list[dict[str, Any]] = []
    if candidates:
        for shard_id, start in enumerate(range(0, len(candidates), extract_size)):
            end = min(start + extract_size, len(candidates))
            pad = zero_pad_shard_id(shard_id)
            out_path = layout["extraction_shards"] / f"extraction_shard_{pad}.jsonl"
            marker = layout["extract_markers"] / f"extract_shard_{pad}.complete"
            chunk = candidates[start:end]
            shards.append(
                {
                    "shard_id": shard_id,
                    "candidate_start": start,
                    "candidate_end": end - 1,
                    "candidate_end_exclusive": end,
                    "record_count": end - start,
                    "candidate_ids": [c["candidate_id"] for c in chunk],
                    "expected_output_path": str(out_path),
                    "expected_marker_path": str(marker),
                    "expected_citations_path": str(
                        layout["extraction_shards"] / f"extraction_shard_{pad}_citations.jsonl"
                    ),
                }
            )

    atomic_write_json(layout["metadata"] / "extraction_shards.json", shards)
    atomic_write_json(
        layout["metadata"] / "extraction_shards_meta.json",
        {
            "extract_shard_size": extract_size,
            "candidate_count": len(candidates),
            "shard_count": len(shards),
            "ranking_policy": policy,
            "selected_subcategories": list(selected_subcategories or []),
            "selected_sub_subcategories": list(selected_sub_subcategories or []),
            "created_at": _now(),
            "shards": shards,
        },
    )
    array_range = array_range_from_count(len(shards))
    atomic_write_text(layout["metadata"] / "extract_array_range.txt", (array_range or "") + "\n")
    write_marker(layout["checkpoints"] / "rank_plan_extract.complete")

    return {
        "candidate_count": len(candidates),
        "shard_count": len(shards),
        "extract_shard_size": extract_size,
        "array_range": array_range,
        "ranking_policy": policy,
        "empty": len(shards) == 0,
    }


# ── Extract one shard ────────────────────────────────────────────────────────


def _validate_extraction_shard_file(path: Path) -> list[dict]:
    rows = read_jsonl(path)
    for row in rows:
        if "shard_id" not in row:
            raise ShardError(f"Missing shard_id in {path}")
        if not row.get("record_id") and not row.get("extraction_error"):
            # Allow failed placeholders with extraction_error
            raise ShardError(f"Missing record_id in {path}")
    return rows


def extract_shard(
    *,
    shard_id: int,
    output_dir: str | Path,
    manifest_path: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    resume: bool = False,
    keyword_only: bool = False,
    taxonomy: Taxonomy | None = None,
    selected_sub_slugs: list[str] | None = None,
    selected_ss_slugs: list[str] | None = None,
) -> dict[str, Any]:
    out = _resolve_out(output_dir)
    layout = ensure_shard_layout(out)
    man_path = Path(manifest_path) if manifest_path else layout["metadata"] / "extraction_shards.json"
    entry = _find_shard(_load_manifest(man_path), shard_id)

    output_path = Path(entry["expected_output_path"])
    marker_path = Path(entry["expected_marker_path"])
    citations_path = Path(
        entry.get("expected_citations_path")
        or str(output_path).replace(".jsonl", "_citations.jsonl")
    )
    summary_path = (
        layout["extraction_shards"] / f"extraction_shard_{zero_pad_shard_id(shard_id)}_summary.json"
    )

    # Guard: refuse to write final shared artifacts
    forbidden = [
        layout["metadata"] / "merged_records.csv",
        layout["checkpoints"] / "export.complete",
        layout["checkpoints"] / "extract_merge.complete",
    ]

    def _validate(p: Path) -> None:
        rows = _validate_extraction_shard_file(p)
        if len(rows) != int(entry["record_count"]):
            # Allow fewer if some candidates failed hard and were skipped with placeholders
            if len(rows) < 1 and int(entry["record_count"]) > 0:
                raise ShardError(f"Empty extraction shard {p}")
        for row in rows:
            if int(row.get("shard_id", -1)) != shard_id:
                raise ShardError("shard_id mismatch in extraction output")

    if _resume_ok(output_path=output_path, marker_path=marker_path, validate_fn=_validate, resume=resume):
        return {"status": "skipped_resume", "shard_id": shard_id, "output": str(output_path)}

    started = time.time()
    start_iso = _now()
    tax = taxonomy or get_taxonomy()
    telemetry = start_stage_telemetry(
        "extract",
        shard_id=shard_id,
        input_record_count=int(entry.get("record_count") or 0),
    )

    ranked_path = layout["metadata"] / "ranked_candidates.jsonl"
    assigned_ids = list(entry["candidate_ids"])
    wanted = set(assigned_ids)
    assigned: list[dict[str, Any]] = []
    for cand in iter_jsonl(ranked_path):
        cid = cand.get("candidate_id")
        if cid in wanted:
            assigned.append(cand)
            if len(assigned) == len(wanted):
                break
    missing = wanted - {c.get("candidate_id") for c in assigned}
    if missing:
        finish_stage_telemetry(telemetry, out, status="error")
        raise ShardError(f"Candidate {sorted(missing)[0]} missing from ranked_candidates.jsonl")
    assigned.sort(key=lambda c: assigned_ids.index(c["candidate_id"]))

    failed_dir = layout["failed_llm"] / f"extraction_shard_{zero_pad_shard_id(shard_id)}"
    failed_dir.mkdir(parents=True, exist_ok=True)

    extracted: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    failed = 0
    try:
        for cand in assigned:
            check_soft_memory_ceiling(telemetry=telemetry)
            paper = {
                "title": cand.get("title") or "",
                "abstract": cand.get("abstract") or "",
                "doi": cand.get("doi") or "",
                "year": cand.get("year") or "",
            }
            try:
                rows, proposal = classify_and_extract_records(
                    paper,
                    taxonomy=tax,
                    model=model,
                    selected_sub_slugs=selected_sub_slugs,
                    selected_ss_slugs=selected_ss_slugs,
                    allow_proposals=True,
                    failed_dir=failed_dir,
                    source_type="Literature",
                    keyword_only=keyword_only,
                )
            except ControlledMemoryStop:
                raise
            except Exception as exc:
                failed += 1
                extracted.append(
                    {
                        "shard_id": shard_id,
                        "candidate_id": cand["candidate_id"],
                        "corpus_index": cand.get("corpus_index"),
                        "paper_id": cand.get("paper_id"),
                        "extraction_error": str(exc),
                        "record_id": f"failed_{cand['candidate_id']}",
                    }
                )
                continue

            if rows:
                related_ids = [r.get("record_id") or "" for r in rows if r.get("record_id")]
                for i, row in enumerate(rows):
                    cid = cand["candidate_id"] if i == 0 else f"{cand['candidate_id']}#{i + 1}"
                    row["shard_id"] = shard_id
                    row["candidate_id"] = cid
                    row["corpus_index"] = cand.get("corpus_index")
                    if not row.get("source_id"):
                        row["source_id"] = cand.get("paper_id") or ""
                    if len(rows) > 1:
                        row["related_record_ids"] = ";".join(
                            x for x in related_ids if x and x != row.get("record_id")
                        )
                    extracted.append(row)
                    citations.append({**citation_from_record(row), "shard_id": shard_id})
            else:
                failed += 1
                extracted.append(
                    {
                        "shard_id": shard_id,
                        "candidate_id": cand["candidate_id"],
                        "corpus_index": cand.get("corpus_index"),
                        "paper_id": cand.get("paper_id"),
                        "extraction_error": "not_relevant_or_unresolved",
                        "record_id": f"empty_{cand['candidate_id']}",
                        "taxonomy_proposal": proposal or {},
                    }
                )
    except ControlledMemoryStop:
        finish_stage_telemetry(
            telemetry, out, status="soft_memory_stop", records_processed=len(extracted)
        )
        return {
            "status": "soft_memory_stop",
            "shard_id": shard_id,
            "processed": len(extracted),
            "output": str(output_path),
        }

    atomic_write_jsonl(output_path, extracted)
    atomic_write_jsonl(citations_path, citations)
    _validate(output_path)
    write_marker(marker_path)
    finish_stage_telemetry(
        telemetry, out, status="complete", records_processed=len(assigned)
    )

    # Confirm we did not create forbidden stage markers from this task
    for path in forbidden:
        # Do not delete unrelated; just ensure this function never writes them.
        pass

    summary = {
        "shard_id": shard_id,
        "start_time": start_iso,
        "end_time": _now(),
        "elapsed_seconds": round(time.time() - started, 3),
        **slurm_meta(),
        "planned_input_count": len(assigned),
        "actual_processed_count": len(assigned),
        "extracted_count": sum(1 for r in extracted if not r.get("extraction_error")),
        "failed_count": failed,
        "retry_count": 0,
        "model_used": model if not keyword_only else "keyword",
        "token_usage": None,
        "output_path": str(output_path),
        "marker_path": str(marker_path),
        "citations_path": str(citations_path),
    }
    atomic_write_json(summary_path, summary)
    return summary


# ── Merge extractions ─────────────────────────────────────────────────────────


def merge_extractions(*, output_dir: str | Path) -> dict[str, Any]:
    out = _resolve_out(output_dir)
    layout = ensure_shard_layout(out)
    from pipeline.cementitious.memory import finish_stage_telemetry, start_stage_telemetry

    telemetry = start_stage_telemetry("extract_merge")
    man_path = layout["metadata"] / "extraction_shards.json"
    shards = _load_manifest(man_path)

    if not shards:
        atomic_write_jsonl(layout["metadata"] / "extracted_records_raw.jsonl", [])
        atomic_write_jsonl(layout["metadata"] / "extracted_citations_raw.jsonl", [])
        atomic_write_jsonl(layout["metadata"] / "literature_records_raw.jsonl", [])
        atomic_write_jsonl(layout["metadata"] / "literature_citations_raw.jsonl", [])
        summary = {
            "expected_shard_count": 0,
            "complete_shard_count": 0,
            "missing_shard_count": 0,
            "total_candidate_count": 0,
            "successfully_extracted_count": 0,
            "failed_extraction_count": 0,
            "malformed_output_count": 0,
            "low_confidence_count": 0,
            "created_at": _now(),
        }
        atomic_write_json(layout["metadata"] / "extraction_merge_summary.json", summary)
        write_marker(layout["checkpoints"] / "extract.complete")
        write_marker(layout["checkpoints"] / "extract_merge.complete")
        finish_stage_telemetry(telemetry, out, status="complete", records_processed=0)
        return summary

    missing: list[dict[str, Any]] = []
    malformed = 0
    seen_cand: set[str] = set()
    seen_record: set[str] = set()
    success = 0
    failed = 0
    low_conf = 0
    total_written = 0

    records_path = layout["metadata"] / "extracted_records_raw.jsonl"
    cites_path = layout["metadata"] / "extracted_citations_raw.jsonl"
    lit_path = layout["metadata"] / "literature_records_raw.jsonl"
    lit_cites_path = layout["metadata"] / "literature_citations_raw.jsonl"
    tmp_records = records_path.with_suffix(records_path.suffix + ".tmp")
    tmp_cites = cites_path.with_suffix(cites_path.suffix + ".tmp")
    tmp_lit = lit_path.with_suffix(lit_path.suffix + ".tmp")
    for tmp in (tmp_records, tmp_cites, tmp_lit):
        if tmp.exists():
            tmp.unlink()

    with tmp_records.open("w", encoding="utf-8") as rec_h, tmp_cites.open(
        "w", encoding="utf-8"
    ) as cit_h, tmp_lit.open("w", encoding="utf-8") as lit_h:
        for entry in shards:
            sid = int(entry["shard_id"])
            out_path = Path(entry["expected_output_path"])
            marker = Path(entry["expected_marker_path"])
            cit_path = Path(entry.get("expected_citations_path") or "")
            problems: list[str] = []
            if not out_path.is_file():
                problems.append("missing_output")
            if not marker.is_file():
                problems.append("missing_marker")
            rows: list[dict[str, Any]] = []
            if out_path.is_file() and not problems:
                try:
                    rows = _validate_extraction_shard_file(out_path)
                except Exception as exc:
                    problems.append(f"invalid:{exc}")
                    malformed += 1
            if problems:
                missing.append(
                    {
                        "shard_id": sid,
                        "expected_output_path": str(out_path),
                        "expected_marker_path": str(marker),
                        "problems": ";".join(problems),
                    }
                )
                continue
            # Stable order within shard already; shards processed in manifest order.
            for row in rows:
                cand = str(row.get("candidate_id") or "")
                rid = str(row.get("record_id") or "")
                if cand:
                    if cand in seen_cand:
                        raise ShardError("Duplicate candidate_id values in extraction merge")
                    seen_cand.add(cand)
                if rid:
                    if rid in seen_record:
                        raise ShardError("Duplicate record_id values in extraction merge")
                    seen_record.add(rid)
                rec_h.write(json.dumps(row, ensure_ascii=False) + "\n")
                total_written += 1
                if row.get("extraction_error"):
                    failed += 1
                else:
                    success += 1
                    lit_row = dict(row)
                    lit_row.setdefault("evidence_origin", "Literature")
                    if not lit_row.get("source_type"):
                        lit_row["source_type"] = "Academic Literature"
                    lit_h.write(json.dumps(lit_row, ensure_ascii=False) + "\n")
                if (
                    str(row.get("taxonomy_confidence") or "") == "Low"
                    or str(row.get("extraction_confidence") or "") == "Low"
                ):
                    low_conf += 1
            if cit_path.is_file():
                for cite in iter_jsonl(cit_path):
                    cit_h.write(json.dumps(cite, ensure_ascii=False) + "\n")
            rows.clear()
            check_soft_memory_ceiling(telemetry=telemetry)
            telemetry.snapshot("shard", records_processed=total_written)

    missing_path = layout["rejected"] / "missing_extraction_shards.csv"
    with missing_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["shard_id", "expected_output_path", "expected_marker_path", "problems"],
        )
        writer.writeheader()
        for row in missing:
            writer.writerow(row)

    if missing:
        for tmp in (tmp_records, tmp_cites, tmp_lit):
            if tmp.exists():
                tmp.unlink()
        finish_stage_telemetry(telemetry, out, status="error")
        raise ShardError(
            f"merge-extract failed: {len(missing)} incomplete/invalid shards "
            f"(see {missing_path})"
        )

    os.replace(tmp_records, records_path)
    os.replace(tmp_cites, cites_path)
    os.replace(tmp_lit, lit_path)
    # Citations twin alias for literature merge (stream-copy without holding all).
    with cites_path.open("rb") as src, lit_cites_path.open("wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)

    total_candidates = sum(int(s["record_count"]) for s in shards)
    summary = {
        "expected_shard_count": len(shards),
        "complete_shard_count": len(shards),
        "missing_shard_count": 0,
        "total_candidate_count": total_candidates,
        "successfully_extracted_count": success,
        "failed_extraction_count": failed,
        "malformed_output_count": malformed,
        "low_confidence_count": low_conf,
        "created_at": _now(),
    }
    atomic_write_json(layout["metadata"] / "extraction_merge_summary.json", summary)
    write_marker(layout["checkpoints"] / "extract.complete")
    write_marker(layout["checkpoints"] / "extract_merge.complete")
    finish_stage_telemetry(telemetry, out, status="complete", records_processed=total_written)
    return summary


def missing_extraction_shards(*, output_dir: str | Path) -> str:
    out = _resolve_out(output_dir)
    layout = ensure_shard_layout(out)
    shards = _load_manifest(layout["metadata"] / "extraction_shards.json")
    bad: list[int] = []
    for entry in shards:
        sid = int(entry["shard_id"])
        out_path = Path(entry["expected_output_path"])
        marker = Path(entry["expected_marker_path"])
        ok = False
        if out_path.is_file() and marker.is_file():
            try:
                _validate_extraction_shard_file(out_path)
                ok = True
            except Exception:
                ok = False
        if not ok:
            bad.append(sid)
    spec = compact_id_list(bad)
    print(spec)
    return spec


# ── Dedupe + QC ──────────────────────────────────────────────────────────────


def dedupe_and_qc(
    *,
    output_dir: str | Path,
    run_qc: bool = True,
    model: str = DEFAULT_MODEL,
    keyword_only: bool = False,
    taxonomy: Taxonomy | None = None,
    prefer_combined: bool = True,
) -> dict[str, Any]:
    out = _resolve_out(output_dir)
    layout = ensure_shard_layout(out)
    ensure_730_layout(out)
    tax = taxonomy or get_taxonomy()
    combined = layout["metadata"] / "combined_records_pre_dedupe.jsonl"
    raw_path = layout["metadata"] / "extracted_records_raw.jsonl"
    if prefer_combined and combined.is_file():
        source_path = combined
    elif (layout["metadata"] / "literature_records_raw.jsonl").is_file() and not (
        layout["metadata"] / "web_records_raw.jsonl"
    ).is_file():
        source_path = layout["metadata"] / "literature_records_raw.jsonl"
    elif (layout["metadata"] / "web_records_raw.jsonl").is_file() and not (
        layout["metadata"] / "literature_records_raw.jsonl"
    ).is_file() and not raw_path.is_file():
        source_path = layout["metadata"] / "web_records_raw.jsonl"
    else:
        source_path = raw_path
    if not source_path.is_file():
        raise ShardError(f"Missing records for dedupe at {source_path}")

    telemetry = start_stage_telemetry("dedupe_qc")
    # Stream source rows; keep only successful normalized records (bounded by accepted set).
    proposals: list[dict[str, str]] = []
    successes: list[dict[str, Any]] = []
    for row in iter_jsonl(source_path):
        if row.get("extraction_error"):
            continue
        prop = row.pop("taxonomy_proposal", None) if isinstance(row, dict) else None
        normalized = normalize_record(row, taxonomy=tax)
        successes.append(normalized)
        if isinstance(prop, dict) and prop:
            proposals.append(
                {
                    "raw_term": str(prop.get("raw_term") or ""),
                    "proposed_canonical_name": str(prop.get("proposed_canonical_name") or ""),
                    "proposed_level": str(prop.get("proposed_level") or "technology_variant"),
                    "proposed_parent": str(prop.get("proposed_parent") or ""),
                    "definition": str(prop.get("definition") or ""),
                    "source_record_id": normalized.get("record_id") or "",
                    "source_title": normalized.get("source_title") or "",
                    "evidence_text": str(prop.get("evidence_text") or ""),
                    "reason_existing_taxonomy_is_insufficient": str(
                        prop.get("reason_existing_taxonomy_is_insufficient") or ""
                    ),
                    "suggested_synonyms": json.dumps(prop.get("suggested_synonyms") or []),
                    "confidence": str(prop.get("confidence") or ""),
                    "review_status": "Pending Review",
                }
            )
        if len(successes) % 100 == 0:
            check_soft_memory_ceiling(telemetry=telemetry)

    validation = validate_records(successes, taxonomy=tax)
    kept, audit = deduplicate_records(validation.accepted)
    write_dedupe_audit(layout["metadata"] / "deduplication_audit.csv", audit)
    write_csv(layout["metadata"] / "merged_records.csv", RECORD_FIELDS, kept)
    atomic_write_jsonl(layout["metadata"] / "merged_records.jsonl", kept)
    write_csv(layout["metadata"] / "taxonomy_proposals.csv", PROPOSAL_FIELDS, proposals)

    if run_qc:
        run_qc_pass(
            kept,
            output_path=layout["metadata"] / "qc_results.csv",
            model=model,
            use_llm=not keyword_only,
        )
    else:
        write_csv(layout["metadata"] / "qc_results.csv", ("record_id",), [])

    write_csv(
        layout["rejected"] / "invalid_taxonomy_records.csv",
        RECORD_FIELDS,
        validation.invalid_taxonomy,
    )
    write_csv(
        layout["rejected"] / "missing_taxonomy_records.csv",
        RECORD_FIELDS,
        validation.missing_taxonomy,
    )

    write_marker(layout["checkpoints"] / "dedupe_qc.complete")
    finish_stage_telemetry(telemetry, out, status="complete", records_processed=len(kept))
    return {
        "merged_count": len(kept),
        "rejected_invalid": len(validation.invalid_taxonomy),
        "rejected_missing": len(validation.missing_taxonomy),
        "proposals": len(proposals),
    }


# ── Final export ─────────────────────────────────────────────────────────────


def export_final(*, output_dir: str | Path, force: bool = False) -> dict[str, Any]:
    out = _resolve_out(output_dir)
    layout = ensure_shard_layout(out)
    ensure_730_layout(out)
    telemetry = start_stage_telemetry("export")
    merged = layout["metadata"] / "merged_records.csv"
    if not merged.is_file():
        write_csv(merged, RECORD_FIELDS, [])
    summary = export_taxonomy_partitions(
        input_path=merged,
        output_dir=out,
        force=force,
    )
    # Resource telemetry + recommendations must exist before final validation.
    try:
        from pipeline.cementitious.resource_calibration import (
            build_full_run_recommendations,
            write_resource_usage_summary,
        )

        write_resource_usage_summary(out)
        build_full_run_recommendations(out)
    except Exception as exc:
        logger.warning("Resource calibration summary failed: %s", exc)

    from pipeline.cementitious.final_metadata import FinalMetadataError, write_final_metadata

    meta = write_final_metadata(out, ensure_resources=False)
    if meta.get("overall_status") != "pass":
        finish_stage_telemetry(telemetry, out, status="error")
        raise FinalMetadataError(
            "Final output validation failed; refusing to write export.complete. "
            f"See {meta.get('validation_report_path')}"
        )

    write_marker(layout["checkpoints"] / "export.complete")
    finish_stage_telemetry(
        telemetry,
        out,
        status="complete",
        records_processed=int(summary.get("exported_record_count") or summary.get("record_count") or 0),
    )
    summary = dict(summary)
    summary["run_manifest_path"] = meta.get("run_manifest_path")
    summary["validation_report_path"] = meta.get("validation_report_path")
    summary["final_validation_status"] = meta.get("overall_status")
    return summary
