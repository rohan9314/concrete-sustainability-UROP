"""JSONL helpers for shardable carbon capture pipeline stages."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from pipeline.carbon_capture_extraction import CarbonCaptureExtraction, QuestionAnswerRow
from pipeline.schema import RankedPaper


def write_ranked_shard(
    papers: list[RankedPaper],
    path: str | Path,
    *,
    methodology_slug: str,
    shard_start: int,
    shard_end: int,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "ranked_shard_meta",
        "methodology_slug": methodology_slug,
        "shard_start": shard_start,
        "shard_end": shard_end,
        "ranked_count": len(papers),
    }
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for paper in papers:
            handle.write(
                json.dumps({"type": "ranked_paper", **paper.model_dump()}) + "\n",
            )
    return output_path


def read_ranked_shard(path: str | Path) -> list[RankedPaper]:
    papers: list[RankedPaper] = []
    for payload in _iter_jsonl(path):
        if payload.get("type") == "ranked_paper":
            papers.append(RankedPaper.model_validate(payload))
    return papers


def merge_ranked_papers(
    paths: list[str | Path],
    *,
    top_n: int | None = None,
) -> list[RankedPaper]:
    """Merge ranked shard files, dedupe by paper_id, and keep best rank_score."""
    best_by_id: dict[str, RankedPaper] = {}
    for path in paths:
        for paper in read_ranked_shard(path):
            existing = best_by_id.get(paper.paper_id)
            if existing is None or paper.rank_score > existing.rank_score:
                best_by_id[paper.paper_id] = paper

    merged = sorted(best_by_id.values(), key=lambda paper: paper.rank_score, reverse=True)
    if top_n is not None:
        merged = merged[:top_n]
    return merged


def write_ranked_final(
    papers: list[RankedPaper],
    path: str | Path,
    *,
    methodology_slug: str,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "ranked_final_meta",
        "methodology_slug": methodology_slug,
        "ranked_count": len(papers),
    }
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for paper in papers:
            handle.write(
                json.dumps({"type": "ranked_paper", **paper.model_dump()}) + "\n",
            )
    return output_path


def read_ranked_final(path: str | Path) -> list[RankedPaper]:
    return read_ranked_shard(path)


def _extraction_from_dict(payload: dict) -> CarbonCaptureExtraction:
    answers_raw = payload.get("answers") or []
    answers = [
        QuestionAnswerRow(
            question_id=str(item.get("question_id") or ""),
            question=str(item.get("question") or ""),
            answer=str(item.get("answer") or ""),
            confidence=str(item.get("confidence") or ""),
            source_type_used=list(item.get("source_type_used") or []),
            sources=list(item.get("sources") or []),
        )
        for item in answers_raw
        if isinstance(item, dict)
    ]
    data = {key: value for key, value in payload.items() if key not in {"type", "answers"}}
    return CarbonCaptureExtraction(answers=answers, **data)


def write_extraction_shard(
    results: list[CarbonCaptureExtraction],
    path: str | Path,
    *,
    methodology_slug: str,
    batch_start: int = 0,
    batch_end: int | None = None,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "extraction_shard_meta",
        "methodology_slug": methodology_slug,
        "batch_start": batch_start,
        "batch_end": batch_end if batch_end is not None else batch_start + len(results),
        "result_count": len(results),
    }
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for result in results:
            payload = asdict(result)
            payload["type"] = "carbon_capture_extraction"
            handle.write(json.dumps(payload) + "\n")
    return output_path


def read_extraction_shard(path: str | Path) -> list[CarbonCaptureExtraction]:
    results: list[CarbonCaptureExtraction] = []
    for payload in _iter_jsonl(path):
        if payload.get("type") == "carbon_capture_extraction":
            results.append(_extraction_from_dict(payload))
    return results


def merge_extractions(paths: list[str | Path]) -> list[CarbonCaptureExtraction]:
    """Merge extraction shard files, deduping by result_id."""
    best_by_id: dict[str, CarbonCaptureExtraction] = {}
    for path in paths:
        for result in read_extraction_shard(path):
            existing = best_by_id.get(result.result_id)
            if existing is None or (existing.extraction_error and not result.extraction_error):
                best_by_id[result.result_id] = result
    return list(best_by_id.values())


def merge_screening_shards(paths: list[str | Path], output_path: str | Path) -> Path:
    """Merge Stage 1 screening JSONL shards into one file."""
    from pipeline.schema import AbstractScreeningResult

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    best_by_id: dict[str, AbstractScreeningResult] = {}
    meta: dict = {"type": "screening_meta", "merged_from_shards": len(paths)}

    for path in paths:
        for payload in _iter_jsonl(path):
            if payload.get("type") == "screening_meta":
                meta.update({k: v for k, v in payload.items() if k != "type"})
            elif "paper_id" in payload:
                row = AbstractScreeningResult.model_validate(payload)
                existing = best_by_id.get(row.paper_id)
                if existing is None or row.confidence > existing.confidence:
                    best_by_id[row.paper_id] = row

    meta["screened"] = len(best_by_id)
    with output.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for row in best_by_id.values():
            handle.write(json.dumps(row.model_dump()) + "\n")
    return output


def _iter_jsonl(path: str | Path):
    file_path = Path(path)
    if not file_path.is_file():
        return
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


def glob_shard_files(directory: str | Path, pattern: str) -> list[Path]:
    root = Path(directory)
    if not root.is_dir():
        return []
    return sorted(root.glob(pattern))
