"""JSONL shard helpers for distributed SCM pipeline stages."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.schema import RankedPaper
from pipeline.scm.extraction import ScmDiscoveryRow, ScmEvidenceRow
from pipeline.scm.screening import ScmScreeningResult


def _iter_jsonl(path: str | Path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def glob_shard_files(directory: str | Path, pattern: str = "*.jsonl") -> list[Path]:
    path = Path(directory)
    if not path.is_dir():
        return []
    return sorted(path.glob(pattern))


def write_ranked_shard(
    papers: list[RankedPaper],
    path: str | Path,
    *,
    category_slug: str,
    shard_start: int,
    shard_end: int,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "scm_ranked_shard_meta",
        "category_slug": category_slug,
        "shard_start": shard_start,
        "shard_end": shard_end,
        "ranked_count": len(papers),
    }
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for paper in papers:
            handle.write(json.dumps({"type": "ranked_paper", **paper.model_dump()}) + "\n")
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
    best_by_id: dict[str, RankedPaper] = {}
    for path in paths:
        for paper in read_ranked_shard(path):
            existing = best_by_id.get(paper.paper_id)
            if existing is None or paper.rank_score > existing.rank_score:
                best_by_id[paper.paper_id] = paper
    merged = sorted(best_by_id.values(), key=lambda paper: paper.rank_score, reverse=True)
    if top_n is not None and top_n > 0:
        merged = merged[:top_n]
    return merged


def write_ranked_final(
    papers: list[RankedPaper],
    path: str | Path,
    *,
    category_slug: str,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "scm_ranked_final_meta",
        "category_slug": category_slug,
        "ranked_count": len(papers),
    }
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for paper in papers:
            handle.write(json.dumps({"type": "ranked_paper", **paper.model_dump()}) + "\n")
    return output_path


def write_evidence_shard(
    rows: list[ScmEvidenceRow],
    path: str | Path,
    *,
    category_slug: str,
    batch_start: int = 0,
    batch_end: int | None = None,
    source_origin: str = "literature",
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "scm_evidence_shard_meta",
        "category_slug": category_slug,
        "batch_start": batch_start,
        "batch_end": batch_end if batch_end is not None else batch_start + len(rows),
        "source_origin": source_origin,
        "row_count": len(rows),
    }
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for row in rows:
            payload = row.to_dict()
            payload["type"] = "scm_evidence_row"
            handle.write(json.dumps(payload) + "\n")
    return output_path


def read_evidence_shard(path: str | Path) -> list[ScmEvidenceRow]:
    rows: list[ScmEvidenceRow] = []
    for payload in _iter_jsonl(path):
        if payload.get("type") == "scm_evidence_row":
            data = {k: v for k, v in payload.items() if k != "type"}
            rows.append(ScmEvidenceRow.from_dict(data))
    return rows


def merge_evidence_shards(paths: list[str | Path]) -> list[ScmEvidenceRow]:
    merged: list[ScmEvidenceRow] = []
    seen: set[str] = set()
    for path in paths:
        for row in read_evidence_shard(path):
            if row.record_id in seen:
                continue
            seen.add(row.record_id)
            merged.append(row)
    return merged


def write_discovery_shard(
    rows: list[ScmDiscoveryRow],
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"type": "scm_discovery_shard_meta", "row_count": len(rows)}
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for row in rows:
            payload = row.to_dict()
            payload["type"] = "scm_discovery_row"
            handle.write(json.dumps(payload) + "\n")
    return output_path


def read_discovery_shard(path: str | Path) -> list[ScmDiscoveryRow]:
    rows: list[ScmDiscoveryRow] = []
    for payload in _iter_jsonl(path):
        if payload.get("type") == "scm_discovery_row":
            data = {k: v for k, v in payload.items() if k != "type"}
            rows.append(ScmDiscoveryRow.from_dict(data))
    return rows


def write_screening_shard(
    results: list[ScmScreeningResult],
    path: str | Path,
    *,
    shard_start: int,
    shard_end: int,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "screening_meta",
        "start": shard_start,
        "end": shard_end,
        "screened": len(results),
        "stage": "scm_abstract_screening",
    }
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for offset, result in enumerate(results):
            payload = result.model_dump()
            # Compatible with pipeline.screening_results.AbstractScreeningResult.
            payload["type"] = "screening_result"
            payload["index"] = shard_start + offset
            payload["abstract"] = ""
            payload["relevant_subpaths"] = payload.get("matched_seed_hints") or []
            handle.write(json.dumps(payload) + "\n")
    return output_path


def merge_screening_shards(
    shard_paths: list[str | Path],
    output_path: str | Path,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    rows: list[dict] = []
    for path in shard_paths:
        for payload in _iter_jsonl(path):
            if payload.get("type") in {"scm_screening_meta", "screening_meta"}:
                continue
            paper_id = str(payload.get("paper_id") or "")
            if not paper_id or paper_id in seen:
                continue
            seen.add(paper_id)
            rows.append(payload)
    with out.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "scm_screening_merged_meta",
                    "row_count": len(rows),
                },
            )
            + "\n",
        )
        for row in rows:
            if "type" not in row:
                row = {**row, "type": "screening_result"}
            handle.write(json.dumps(row) + "\n")
    return out
