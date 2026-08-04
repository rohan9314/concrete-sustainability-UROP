"""Genuinely sharded web search/extraction stages for Cementitious Materials."""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pipeline.cementitious.extraction import classify_and_extract
from pipeline.cementitious.memory import check_soft_memory_ceiling
from pipeline.cementitious.schema import (
    RECORD_FIELDS,
    normalize_record,
    citation_from_record,
)
from pipeline.cementitious.shard_io import (
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
from pipeline.cementitious.web_config import WebLimits, load_web_limits
from pipeline.cementitious.web_queries import plan_web_queries
from pipeline.cementitious.web_tavily import (
    extract_page_text,
    get_tavily_client,
    tavily_search,
)
from pipeline.cementitious.source_classification import classify_source_type
from pipeline.cementitious.evidence_alignment import align_record_evidence
from pipeline.cementitious.web_url import domain_of, normalize_url
from pipeline.llm_utils import DEFAULT_MODEL

logger = logging.getLogger(__name__)


class WebShardError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise WebShardError(f"Manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "shards" in payload:
        return list(payload["shards"])
    if isinstance(payload, list):
        return payload
    raise WebShardError(f"Invalid manifest: {path}")


def _find_shard(manifest: list[dict[str, Any]], shard_id: int) -> dict[str, Any]:
    for entry in manifest:
        if int(entry.get("shard_id", -1)) == int(shard_id):
            return entry
    raise WebShardError(f"shard_id {shard_id} not in manifest")


def _resume_ok(output_path: Path, marker_path: Path, validate_fn) -> bool:
    if not marker_path.is_file() or not output_path.is_file():
        return False
    try:
        validate_fn(output_path)
        return True
    except Exception as exc:
        logger.warning("RESUME invalid %s (%s); rerunning", output_path, exc)
        return False


def ensure_web_layout(output_dir: Path) -> dict[str, Path]:
    layout = ensure_shard_layout(output_dir)
    extra = {
        "web_search_shards": layout["metadata"] / "web_search_shards",
        "web_search_markers": layout["checkpoints"] / "web_search_shards",
        "web_extraction_shards": layout["metadata"] / "web_extraction_shards",
        "web_extract_markers": layout["checkpoints"] / "web_extraction_shards",
    }
    for path in extra.values():
        path.mkdir(parents=True, exist_ok=True)
    layout.update(extra)
    return layout


# ── Plan web queries ─────────────────────────────────────────────────────────


def plan_web_query_shards(
    *,
    output_dir: str | Path,
    taxonomy: Taxonomy | None = None,
    limits: WebLimits | None = None,
    selected_subcategories: list[str] | None = None,
    selected_sub_subcategories: list[str] | None = None,
) -> dict[str, Any]:
    out = Path(output_dir)
    layout = ensure_web_layout(out)
    tax = taxonomy or get_taxonomy()
    lim = limits or load_web_limits()

    queries = plan_web_queries(
        tax,
        lim,
        selected_subcategories=selected_subcategories,
        selected_sub_subcategories=selected_sub_subcategories,
    )
    atomic_write_json(layout["metadata"] / "web_queries.json", queries)

    shards: list[dict[str, Any]] = []
    if queries:
        size = lim.search_shard_size
        for shard_id, start in enumerate(range(0, len(queries), size)):
            end = min(start + size, len(queries))
            chunk = queries[start:end]
            for q in chunk:
                q["shard_id"] = shard_id
            pad = zero_pad_shard_id(shard_id)
            shards.append(
                {
                    "shard_id": shard_id,
                    "query_ids": [q["query_id"] for q in chunk],
                    "query_count": len(chunk),
                    "expected_output_path": str(
                        layout["web_search_shards"] / f"web_search_shard_{pad}.jsonl"
                    ),
                    "expected_marker_path": str(
                        layout["web_search_markers"] / f"web_search_shard_{pad}.complete"
                    ),
                }
            )

    # Rewrite queries with shard_ids assigned
    atomic_write_json(layout["metadata"] / "web_queries.json", queries)
    atomic_write_json(layout["metadata"] / "web_query_shards.json", shards)
    array_range = array_range_from_count(len(shards))
    atomic_write_text(layout["metadata"] / "web_search_array_range.txt", (array_range or "") + "\n")
    atomic_write_json(
        layout["metadata"] / "web_limits.json",
        lim.to_dict(),
    )
    write_marker(layout["checkpoints"] / "plan_web_queries.complete")
    return {
        "query_count": len(queries),
        "shard_count": len(shards),
        "array_range": array_range,
        "limits": lim.to_dict(),
    }


# ── Web search shard ─────────────────────────────────────────────────────────


def web_search_shard(
    *,
    shard_id: int,
    output_dir: str | Path,
    manifest_path: str | Path | None = None,
    resume: bool = False,
    tavily_client=None,
    limits: WebLimits | None = None,
) -> dict[str, Any]:
    out = Path(output_dir)
    layout = ensure_web_layout(out)
    lim = limits or load_web_limits()
    man = Path(manifest_path) if manifest_path else layout["metadata"] / "web_query_shards.json"
    entry = _find_shard(_load_manifest(man), shard_id)
    output_path = Path(entry["expected_output_path"])
    marker_path = Path(entry["expected_marker_path"])
    summary_path = layout["web_search_shards"] / f"web_search_shard_{zero_pad_shard_id(shard_id)}_summary.json"

    def _validate(p: Path) -> None:
        rows = read_jsonl(p)
        for row in rows:
            if int(row.get("shard_id", -1)) != shard_id:
                raise WebShardError("shard_id mismatch")

    if resume and _resume_ok(output_path, marker_path, _validate):
        return {"status": "skipped_resume", "shard_id": shard_id}

    from pipeline.cementitious.memory import finish_stage_telemetry, start_stage_telemetry

    started = time.time()
    start_iso = _now()
    telemetry = start_stage_telemetry(
        "web_search",
        shard_id=shard_id,
        input_record_count=len(entry.get("query_ids") or []),
    )
    queries_all = {
        q["query_id"]: q
        for q in json.loads((layout["metadata"] / "web_queries.json").read_text(encoding="utf-8"))
    }
    assigned = [queries_all[qid] for qid in entry["query_ids"] if qid in queries_all]
    if len(assigned) != len(entry["query_ids"]):
        raise WebShardError(f"Missing query definitions for shard {shard_id}")

    client = tavily_client if tavily_client is not None else get_tavily_client(require=True)
    rows: list[dict[str, Any]] = []
    failed_queries = 0
    api_calls = 0

    for query in assigned:
        results, meta = tavily_search(
            client,
            query["query_text"],
            max_results=int(query.get("maximum_results") or lim.results_per_query),
            timeout=lim.request_timeout,
            max_retries=lim.max_retries,
        )
        api_calls += meta.get("attempts", 1)
        if not meta.get("ok"):
            failed_queries += 1
            rows.append(
                {
                    "query_id": query["query_id"],
                    "query_text": query["query_text"],
                    "subcategory_slug": query["subcategory_slug"],
                    "sub_subcategory_slug": query["sub_subcategory_slug"],
                    "result_rank": None,
                    "title": "",
                    "url": "",
                    "normalized_url": "",
                    "domain": "",
                    "snippet": "",
                    "tavily_score": None,
                    "raw_source_type": "",
                    "raw_content": "",
                    "retrieval_timestamp": _now(),
                    "shard_id": shard_id,
                    "search_error": meta.get("final_error") or "search_failed",
                    "category": query["category"],
                    "subcategory": query["subcategory"],
                    "sub_subcategory": query["sub_subcategory"],
                    "technology_variant": query.get("technology_variant") or "",
                }
            )
            continue
        for rank, item in enumerate(results, start=1):
            url = item["url"]
            domain = domain_of(url)
            if lim.domain_denylist and domain in lim.domain_denylist:
                continue
            if lim.domain_allowlist and domain not in lim.domain_allowlist:
                continue
            rows.append(
                {
                    "query_id": query["query_id"],
                    "query_text": query["query_text"],
                    "subcategory_slug": query["subcategory_slug"],
                    "sub_subcategory_slug": query["sub_subcategory_slug"],
                    "category": query["category"],
                    "subcategory": query["subcategory"],
                    "sub_subcategory": query["sub_subcategory"],
                    "technology_variant": query.get("technology_variant") or "",
                    "result_rank": rank,
                    "title": item.get("title") or "",
                    "url": url,
                    "normalized_url": normalize_url(url),
                    "domain": domain,
                    "snippet": item.get("snippet") or "",
                    "tavily_score": item.get("tavily_score"),
                    "raw_source_type": item.get("raw_source_type") or "",
                    "raw_content": item.get("raw_content") or "",
                    "retrieval_timestamp": _now(),
                    "shard_id": shard_id,
                    "search_error": "",
                }
            )

    atomic_write_jsonl(output_path, rows)
    _validate(output_path)
    write_marker(marker_path)
    summary = {
        "shard_id": shard_id,
        "start_time": start_iso,
        "end_time": _now(),
        "elapsed_seconds": round(time.time() - started, 3),
        **slurm_meta(),
        "planned_input_count": len(assigned),
        "actual_processed_count": len(assigned),
        "raw_result_count": sum(1 for r in rows if r.get("url")),
        "failed_count": failed_queries,
        "api_calls": api_calls,
        "output_path": str(output_path),
        "marker_path": str(marker_path),
    }
    atomic_write_json(summary_path, summary)
    finish_stage_telemetry(
        telemetry,
        out,
        status="complete",
        records_processed=len(assigned),
    )
    return summary


# ── Merge web search + URL dedupe + lightweight screening ────────────────────


def _screen_web_result(row: dict[str, Any], query_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    title = str(row.get("title") or "")
    snippet = str(row.get("snippet") or "")
    url = str(row.get("url") or "")
    domain = str(row.get("domain") or "")
    blob = f"{title}\n{snippet}\n{url}".casefold()
    ss = str(row.get("sub_subcategory_slug") or "")
    negatives = list((query_meta or {}).get("negative_terms") or [])
    positives = list((query_meta or {}).get("positive_terms") or [])

    # Structural rejects
    if any(
        x in blob
        for x in (
            "login",
            "sign in",
            "cookie policy",
            "search results",
            "yellow pages",
            "directory listing",
        )
    ):
        return {
            "relevance_decision": "irrelevant",
            "relevance_score": 0.1,
            "screening_reason": "Low-content or directory/login page",
            "screening_confidence": "Medium",
        }

    # Role-sensitive exclusions
    if ss == "biomass_ashes" and any(
        x in blob for x in ("kiln fuel", "alternative fuel", "rdf", "co-processing fuel")
    ) and "ash" not in blob and "scm" not in blob and "cement replacement" not in blob:
        return {
            "relevance_decision": "irrelevant",
            "relevance_score": 0.2,
            "screening_reason": "Biomass framed as kiln fuel, not ash SCM",
            "screening_confidence": "High",
        }
    if any(
        x in ss
        for x in (
            "chemical_absorption",
            "membrane_separation",
            "calcium_looping",
            "oxyfuel",
            "direct_separation",
        )
    ):
        industry_only = any(
            x in blob
            for x in (
                "steel mill",
                "coal power plant",
                "natural gas processing",
                "oil refinery",
            )
        )
        if industry_only and "cement" not in blob and "kiln" not in blob:
            return {
                "relevance_decision": "irrelevant",
                "relevance_score": 0.15,
                "screening_reason": "Carbon capture in unrelated industry without cement context",
                "screening_confidence": "High",
            }
    if "scm" in ss or "ash" in ss or "pozzolan" in ss:
        if any(x in blob for x in ("as aggregate only", "road base", "soil amendment")) and "cement replacement" not in blob:
            return {
                "relevance_decision": "irrelevant",
                "relevance_score": 0.2,
                "screening_reason": "Aggregate/soil use without cementitious role",
                "screening_confidence": "High",
            }

    neg_hit = any(n.casefold() in blob for n in negatives if n)
    pos_hit = any(p.casefold() in blob for p in positives if p) or any(
        x in blob
        for x in (
            "cement",
            "concrete",
            "clinker",
            "carbon capture",
            "scm",
            "pozzolan",
            "kiln",
        )
    )
    if neg_hit and not pos_hit:
        return {
            "relevance_decision": "irrelevant",
            "relevance_score": 0.25,
            "screening_reason": "Matched negative screening cues without cementitious positives",
            "screening_confidence": "Medium",
        }
    if pos_hit:
        return {
            "relevance_decision": "relevant",
            "relevance_score": 0.75 if not neg_hit else 0.55,
            "screening_reason": "Title/snippet indicates cementitious intervention",
            "screening_confidence": "Medium",
        }
    return {
        "relevance_decision": "uncertain",
        "relevance_score": 0.4,
        "screening_reason": "Insufficient evidence in snippet; retained for optional extraction",
        "screening_confidence": "Low",
    }


def merge_web_search(*, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    layout = ensure_web_layout(out)
    shards = _load_manifest(layout["metadata"] / "web_query_shards.json")
    queries = {
        q["query_id"]: q
        for q in json.loads((layout["metadata"] / "web_queries.json").read_text(encoding="utf-8"))
    }
    lim = load_web_limits()

    missing: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    for entry in shards:
        sid = int(entry["shard_id"])
        op = Path(entry["expected_output_path"])
        mk = Path(entry["expected_marker_path"])
        problems = []
        if not op.is_file():
            problems.append("missing_output")
        if not mk.is_file():
            problems.append("missing_marker")
        if problems:
            missing.append({"shard_id": sid, "problems": ";".join(problems), "path": str(op)})
            continue
        raw.extend(read_jsonl(op))

    miss_path = layout["rejected"] / "missing_web_search_shards.csv"
    with miss_path.open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=["shard_id", "problems", "path"])
        w.writeheader()
        for row in missing:
            w.writerow(row)
    if missing:
        raise WebShardError(f"merge-web-search failed: {len(missing)} incomplete shards")

    atomic_write_jsonl(layout["metadata"] / "web_search_results_raw.jsonl", raw)

    # URL dedupe preserving query provenance
    by_url: dict[str, dict[str, Any]] = {}
    url_query_map: list[dict[str, Any]] = []
    duplicate_url_count = 0
    for row in raw:
        url = row.get("url") or ""
        if not url:
            continue
        norm = row.get("normalized_url") or normalize_url(url)
        url_query_map.append(
            {
                "normalized_url": norm,
                "url": url,
                "query_id": row.get("query_id"),
                "query_text": row.get("query_text"),
                "sub_subcategory_slug": row.get("sub_subcategory_slug"),
                "result_rank": row.get("result_rank"),
            }
        )
        if norm in by_url:
            duplicate_url_count += 1
            existing = by_url[norm]
            qids = set(existing.get("query_ids") or [])
            qids.add(row.get("query_id"))
            existing["query_ids"] = sorted(qids)
            existing["query_texts"] = sorted(
                set(existing.get("query_texts") or []) | {row.get("query_text")}
            )
            continue
        by_url[norm] = {
            **row,
            "normalized_url": norm,
            "query_ids": [row.get("query_id")],
            "query_texts": [row.get("query_text")],
        }

    # Enforce branch and global URL caps
    branch_counts: Counter[str] = Counter()
    deduped: list[dict[str, Any]] = []
    for norm, row in by_url.items():
        branch = str(row.get("sub_subcategory_slug") or "unknown")
        if branch_counts[branch] >= lim.max_urls_per_branch:
            continue
        if len(deduped) >= lim.max_total_urls:
            break
        branch_counts[branch] += 1
        deduped.append(row)

    atomic_write_jsonl(layout["metadata"] / "web_url_query_map.jsonl", url_query_map)
    atomic_write_jsonl(layout["metadata"] / "web_search_results_deduplicated.jsonl", deduped)

    # Screening
    screened: list[dict[str, Any]] = []
    for idx, row in enumerate(deduped):
        qmeta = queries.get((row.get("query_ids") or [None])[0]) or queries.get(row.get("query_id"))
        decision = _screen_web_result(row, qmeta)
        web_source_id = f"web:{zero_pad_shard_id(idx, 6)}"
        source_cls = classify_source_type(
            url=str(row.get("url") or ""),
            title=str(row.get("title") or ""),
            domain=str(row.get("domain") or ""),
            raw_source_type=str(row.get("raw_source_type") or ""),
        )
        screened.append(
            {
                "web_source_id": web_source_id,
                "url": row.get("url"),
                "normalized_url": row.get("normalized_url"),
                "final_resolved_url": row.get("url"),
                "domain": row.get("domain"),
                "title": row.get("title"),
                "snippet": row.get("snippet"),
                "raw_content": row.get("raw_content") or "",
                "relevance_decision": decision["relevance_decision"],
                "relevance_score": decision["relevance_score"],
                "matched_taxonomy_path": (
                    f"{row.get('subcategory_slug')}/{row.get('sub_subcategory_slug')}"
                ),
                "screening_reason": decision["screening_reason"],
                "screening_confidence": decision["screening_confidence"],
                "query_ids": row.get("query_ids") or [row.get("query_id")],
                "query_texts": row.get("query_texts") or [row.get("query_text")],
                "source_type_guess": source_cls.source_type,
                "source_type_classification_method": source_cls.method,
                "source_type_classification_reason": source_cls.reason,
                "source_type_matched_rule": source_cls.matched_rule,
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "subcategory_slug": row.get("subcategory_slug"),
                "sub_subcategory": row.get("sub_subcategory"),
                "sub_subcategory_slug": row.get("sub_subcategory_slug"),
                "technology_variant": row.get("technology_variant") or "",
                "retrieval_timestamp": row.get("retrieval_timestamp") or _now(),
                "tavily_score": row.get("tavily_score"),
            }
        )
    atomic_write_jsonl(layout["metadata"] / "web_screening_results.jsonl", screened)

    successful_queries = len({r.get("query_id") for r in raw if r.get("url")})
    failed_queries = len({r.get("query_id") for r in raw if r.get("search_error")})
    summary = {
        "query_count": len(queries),
        "successful_query_count": successful_queries,
        "failed_query_count": failed_queries,
        "raw_result_count": sum(1 for r in raw if r.get("url")),
        "unique_url_count": len(deduped),
        "duplicate_url_count": duplicate_url_count,
        "results_by_subcategory": dict(
            Counter(r.get("subcategory_slug") for r in deduped if r.get("url"))
        ),
        "results_by_sub_subcategory": dict(
            Counter(r.get("sub_subcategory_slug") for r in deduped if r.get("url"))
        ),
        "results_by_domain": dict(Counter(r.get("domain") for r in deduped if r.get("domain"))),
        "results_by_source_type": dict(
            Counter(s.get("source_type_guess") for s in screened)
        ),
        "relevant_url_count": sum(
            1 for s in screened if s.get("relevance_decision") == "relevant"
        ),
        "created_at": _now(),
    }
    atomic_write_json(layout["metadata"] / "web_search_merge_summary.json", summary)
    write_marker(layout["checkpoints"] / "web_search.complete")
    write_marker(layout["checkpoints"] / "web_search_merge.complete")
    return summary


def missing_web_search_shards(*, output_dir: str | Path) -> str:
    layout = ensure_web_layout(Path(output_dir))
    shards = _load_manifest(layout["metadata"] / "web_query_shards.json")
    bad = []
    for entry in shards:
        sid = int(entry["shard_id"])
        if not (
            Path(entry["expected_output_path"]).is_file()
            and Path(entry["expected_marker_path"]).is_file()
        ):
            bad.append(sid)
    spec = compact_id_list(bad)
    print(spec)
    return spec


# ── Plan web extraction ──────────────────────────────────────────────────────


def plan_web_extraction(
    *,
    output_dir: str | Path,
    limits: WebLimits | None = None,
) -> dict[str, Any]:
    out = Path(output_dir)
    layout = ensure_web_layout(out)
    lim = limits or load_web_limits()
    screened = read_jsonl(layout["metadata"] / "web_screening_results.jsonl")
    ranked = [
        s
        for s in screened
        if s.get("relevance_decision") in {"relevant", "uncertain"}
    ]
    ranked.sort(key=lambda r: float(r.get("relevance_score") or 0), reverse=True)
    # Cap again by global limit
    ranked = ranked[: lim.max_total_urls]
    atomic_write_jsonl(layout["metadata"] / "web_ranked_sources.jsonl", ranked)

    shards: list[dict[str, Any]] = []
    size = lim.extract_shard_size
    for shard_id, start in enumerate(range(0, len(ranked), size) if ranked else []):
        end = min(start + size, len(ranked))
        chunk = ranked[start:end]
        pad = zero_pad_shard_id(shard_id)
        shards.append(
            {
                "shard_id": shard_id,
                "web_source_ids": [c["web_source_id"] for c in chunk],
                "record_count": len(chunk),
                "expected_output_path": str(
                    layout["web_extraction_shards"] / f"web_extraction_shard_{pad}.jsonl"
                ),
                "expected_citation_path": str(
                    layout["web_extraction_shards"]
                    / f"web_extraction_shard_{pad}_citations.jsonl"
                ),
                "expected_marker_path": str(
                    layout["web_extract_markers"] / f"web_extract_shard_{pad}.complete"
                ),
            }
        )
    atomic_write_json(layout["metadata"] / "web_extraction_shards.json", shards)
    array_range = array_range_from_count(len(shards))
    atomic_write_text(
        layout["metadata"] / "web_extract_array_range.txt", (array_range or "") + "\n"
    )
    write_marker(layout["checkpoints"] / "plan_web_extract.complete")
    return {
        "ranked_count": len(ranked),
        "shard_count": len(shards),
        "array_range": array_range,
        "empty": len(shards) == 0,
    }


# ── Web extract shard ────────────────────────────────────────────────────────


def web_extract_shard(
    *,
    shard_id: int,
    output_dir: str | Path,
    manifest_path: str | Path | None = None,
    resume: bool = False,
    keyword_only: bool = False,
    model: str = DEFAULT_MODEL,
    taxonomy: Taxonomy | None = None,
    limits: WebLimits | None = None,
) -> dict[str, Any]:
    out = Path(output_dir)
    layout = ensure_web_layout(out)
    lim = limits or load_web_limits()
    tax = taxonomy or get_taxonomy()
    man = Path(manifest_path) if manifest_path else layout["metadata"] / "web_extraction_shards.json"
    entry = _find_shard(_load_manifest(man), shard_id)
    output_path = Path(entry["expected_output_path"])
    marker_path = Path(entry["expected_marker_path"])
    citation_path = Path(entry["expected_citation_path"])
    summary_path = (
        layout["web_extraction_shards"]
        / f"web_extraction_shard_{zero_pad_shard_id(shard_id)}_summary.json"
    )
    fail_dir = layout["failed_llm"] / f"web_extraction_shard_{zero_pad_shard_id(shard_id)}"
    fail_dir.mkdir(parents=True, exist_ok=True)
    fetch_failures: list[dict[str, Any]] = []

    def _validate(p: Path) -> None:
        rows = read_jsonl(p)
        for row in rows:
            if int(row.get("shard_id", -1)) != shard_id:
                raise WebShardError("shard_id mismatch")

    if resume and _resume_ok(output_path, marker_path, _validate):
        return {"status": "skipped_resume", "shard_id": shard_id}

    from pipeline.cementitious.memory import finish_stage_telemetry, start_stage_telemetry

    started = time.time()
    start_iso = _now()
    telemetry = start_stage_telemetry(
        "web_extract",
        shard_id=shard_id,
        input_record_count=len(entry.get("web_source_ids") or []),
    )
    ranked_path = layout["metadata"] / "web_ranked_sources.jsonl"
    wanted = set(entry["web_source_ids"])
    assigned: list[dict[str, Any]] = []
    for row in iter_jsonl(ranked_path):
        wid = row.get("web_source_id")
        if wid in wanted:
            assigned.append(row)
            if len(assigned) == len(wanted):
                break
    missing_ids = wanted - {r.get("web_source_id") for r in assigned}
    if missing_ids:
        raise WebShardError(f"Unknown web_source_id(s): {sorted(missing_ids)[:5]}")

    extracted: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    failed = 0
    fetched_ok = 0

    for src in assigned:
        text, content_source = extract_page_text(
            tavily_raw_content=str(src.get("raw_content") or ""),
            snippet=str(src.get("snippet") or ""),
            page_max_chars=lim.page_max_chars,
            url=str(src.get("url") or ""),
            timeout=lim.request_timeout,
            allow_http_fetch=True,
        )
        if content_source == "Unavailable":
            failed += 1
            fetch_failures.append(
                {
                    "web_source_id": src["web_source_id"],
                    "url": src.get("url"),
                    "final_url": src.get("final_resolved_url") or src.get("url"),
                    "domain": src.get("domain"),
                    "failure_type": "content_unavailable",
                    "status_code": "",
                    "error_message": "No raw content or snippet",
                    "retry_count": 0,
                    "retrieval_timestamp": _now(),
                    "query_ids": json.dumps(src.get("query_ids") or []),
                    "taxonomy_path": src.get("matched_taxonomy_path") or "",
                }
            )
            extracted.append(
                {
                    "shard_id": shard_id,
                    "web_source_id": src["web_source_id"],
                    "record_id": f"failed_{src['web_source_id']}",
                    "extraction_error": "content_unavailable",
                    "evidence_origin": "Web",
                    "source_url": src.get("url"),
                }
            )
            continue
        if content_source == "Tavily Snippet":
            fetch_failures.append(
                {
                    "web_source_id": src["web_source_id"],
                    "url": src.get("url"),
                    "final_url": src.get("url"),
                    "domain": src.get("domain"),
                    "failure_type": "fallback_snippet",
                    "status_code": "",
                    "error_message": "Full page unavailable; using Tavily snippet",
                    "retry_count": 0,
                    "retrieval_timestamp": _now(),
                    "query_ids": json.dumps(src.get("query_ids") or []),
                    "taxonomy_path": src.get("matched_taxonomy_path") or "",
                }
            )
        elif content_source in {"Tavily Raw Content", "HTTP Page Fetch"}:
            fetched_ok += 1
        else:
            fetched_ok += 1

        paper_like = {
            "title": src.get("title") or "",
            "abstract": text[:8000],
            "text": text,
            "doi": "",
            "url": src.get("url"),
        }
        try:
            row, _proposal = classify_and_extract(
                paper_like,
                taxonomy=tax,
                model=model,
                selected_sub_slugs=[src["subcategory_slug"]] if src.get("subcategory_slug") else None,
                selected_ss_slugs=[src["sub_subcategory_slug"]]
                if src.get("sub_subcategory_slug")
                else None,
                allow_proposals=True,
                failed_dir=fail_dir,
                source_type=src.get("source_type_guess") or "Other Web Source",
                keyword_only=keyword_only,
            )
        except Exception as exc:
            failed += 1
            extracted.append(
                {
                    "shard_id": shard_id,
                    "web_source_id": src["web_source_id"],
                    "record_id": f"failed_{src['web_source_id']}",
                    "extraction_error": str(exc),
                    "evidence_origin": "Web",
                    "source_url": src.get("url"),
                }
            )
            continue

        if not row:
            failed += 1
            extracted.append(
                {
                    "shard_id": shard_id,
                    "web_source_id": src["web_source_id"],
                    "record_id": f"empty_{src['web_source_id']}",
                    "extraction_error": "unresolved_or_irrelevant",
                    "evidence_origin": "Web",
                    "source_url": src.get("url"),
                }
            )
            continue

        # Prefer taxonomy assignment from search intent if LLM left empty
        if not row.get("sub_subcategory_slug") and src.get("sub_subcategory_slug"):
            row["subcategory"] = src.get("subcategory") or ""
            row["subcategory_slug"] = src.get("subcategory_slug") or ""
            row["sub_subcategory"] = src.get("sub_subcategory") or ""
            row["sub_subcategory_slug"] = src.get("sub_subcategory_slug") or ""

        row["evidence_origin"] = "Web"
        row["web_source_id"] = src["web_source_id"]
        row["query_ids"] = json.dumps(src.get("query_ids") or [])
        row["query_texts"] = json.dumps(src.get("query_texts") or [])
        row["retrieval_timestamp"] = src.get("retrieval_timestamp") or _now()
        row["source_url"] = src.get("url") or ""
        row["normalized_url"] = src.get("normalized_url") or normalize_url(str(src.get("url") or ""))
        row["final_resolved_url"] = src.get("final_resolved_url") or src.get("url") or ""
        row["domain"] = src.get("domain") or ""
        row["content_source"] = content_source
        row["organization_or_publisher"] = src.get("domain") or ""
        # Re-classify with page text available (still deterministic; no LLM).
        source_cls = classify_source_type(
            url=str(src.get("url") or ""),
            title=str(src.get("title") or row.get("source_title") or ""),
            domain=str(src.get("domain") or ""),
            raw_source_type=str(src.get("raw_source_type") or ""),
            page_text=text[:2000],
        )
        # Prefer the stronger of screening guess vs refreshed classification when
        # screening already applied the same deterministic module.
        if src.get("source_type_guess") and src.get("source_type_classification_method") in {
            "domain_rule",
            "url_rule",
            "explicit_metadata",
        }:
            row["source_type"] = src.get("source_type_guess")
            row["source_type_classification_method"] = src.get(
                "source_type_classification_method"
            ) or source_cls.method
            row["source_type_classification_reason"] = src.get(
                "source_type_classification_reason"
            ) or source_cls.reason
            row["source_type_matched_rule"] = src.get("source_type_matched_rule") or source_cls.matched_rule
        else:
            row["source_type"] = source_cls.source_type
            row["source_type_classification_method"] = source_cls.method
            row["source_type_classification_reason"] = source_cls.reason
            row["source_type_matched_rule"] = source_cls.matched_rule
        row["source_id"] = src["web_source_id"]
        row["citation"] = row.get("citation") or row.get("source_url")
        if content_source == "Tavily Snippet" and row.get("extraction_confidence") == "High":
            row["extraction_confidence"] = "Medium"
            row["notes"] = (
                (row.get("notes") + " | " if row.get("notes") else "")
                + "Extracted from Tavily snippet fallback; not full-page evidence."
            )

        alignment = align_record_evidence(
            row,
            source_text=text or str(src.get("snippet") or ""),
            content_source=content_source,
        )
        if (
            row.get("sub_subcategory_slug")
            and not alignment.taxonomy_supported
            and alignment.method == "taxonomy_unsupported"
        ):
            # Search intent assigned a taxonomy the page cannot support — drop.
            failed += 1
            extracted.append(
                {
                    "shard_id": shard_id,
                    "web_source_id": src["web_source_id"],
                    "record_id": f"empty_{src['web_source_id']}",
                    "extraction_error": "taxonomy_evidence_unaligned",
                    "evidence_origin": "Web",
                    "source_url": src.get("url"),
                    "alignment_reason": alignment.reason,
                }
            )
            continue

        row["shard_id"] = shard_id
        extracted.append(row)
        citations.append({**citation_from_record(row), "shard_id": shard_id})

    atomic_write_jsonl(output_path, extracted)
    atomic_write_jsonl(citation_path, citations)
    # Append fetch failures (create or extend)
    fail_csv = layout["rejected"] / "web_fetch_failures.csv"
    write_header = not fail_csv.is_file()
    with fail_csv.open("a", encoding="utf-8", newline="") as handle:
        fields = [
            "web_source_id",
            "url",
            "final_url",
            "domain",
            "failure_type",
            "status_code",
            "error_message",
            "retry_count",
            "retrieval_timestamp",
            "query_ids",
            "taxonomy_path",
        ]
        w = csv.DictWriter(handle, fieldnames=fields)
        if write_header:
            w.writeheader()
        for row in fetch_failures:
            w.writerow(row)

    _validate(output_path)
    write_marker(marker_path)
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
        "successfully_fetched_pages": fetched_ok,
        "output_path": str(output_path),
        "marker_path": str(marker_path),
        "model_used": model if not keyword_only else "keyword",
    }
    atomic_write_json(summary_path, summary)
    finish_stage_telemetry(
        telemetry,
        out,
        status="complete",
        records_processed=len(assigned),
    )
    return summary


def merge_web_extractions(*, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    layout = ensure_web_layout(out)
    shards = _load_manifest(layout["metadata"] / "web_extraction_shards.json")
    if not shards:
        atomic_write_jsonl(layout["metadata"] / "web_records_raw.jsonl", [])
        atomic_write_jsonl(layout["metadata"] / "web_citations_raw.jsonl", [])
        summary = {
            "expected_shard_count": 0,
            "completed_shard_count": 0,
            "missing_shard_count": 0,
            "url_count": 0,
            "successfully_fetched_count": 0,
            "failed_fetch_count": 0,
            "extracted_record_count": 0,
            "malformed_output_count": 0,
            "low_confidence_count": 0,
            "records_by_taxonomy_branch": {},
            "records_by_source_type": {},
            "created_at": _now(),
        }
        atomic_write_json(layout["metadata"] / "web_extraction_merge_summary.json", summary)
        write_marker(layout["checkpoints"] / "web_extract.complete")
        write_marker(layout["checkpoints"] / "web_extract_merge.complete")
        return summary

    missing = []
    seen_record: set[str] = set()
    success_count = 0
    failed_fetch = 0
    low_conf = 0
    url_ids: set[str] = set()
    branch_counter: Counter[str] = Counter()
    source_type_counter: Counter[str] = Counter()
    raw_content_ok = 0

    records_path = layout["metadata"] / "web_records_raw.jsonl"
    cites_path = layout["metadata"] / "web_citations_raw.jsonl"
    tmp_records = records_path.with_suffix(records_path.suffix + ".tmp")
    tmp_cites = cites_path.with_suffix(cites_path.suffix + ".tmp")
    for tmp in (tmp_records, tmp_cites):
        if tmp.exists():
            tmp.unlink()

    with tmp_records.open("w", encoding="utf-8") as rec_h, tmp_cites.open(
        "w", encoding="utf-8"
    ) as cit_h:
        for entry in shards:
            sid = int(entry["shard_id"])
            op = Path(entry["expected_output_path"])
            mk = Path(entry["expected_marker_path"])
            cp = Path(entry["expected_citation_path"])
            problems = []
            if not op.is_file():
                problems.append("missing_output")
            if not mk.is_file():
                problems.append("missing_marker")
            if problems:
                missing.append({"shard_id": sid, "problems": ";".join(problems)})
                continue
            for row in iter_jsonl(op):
                wid = str(row.get("web_source_id") or "")
                if wid:
                    url_ids.add(wid)
                if row.get("extraction_error"):
                    failed_fetch += 1
                    continue
                rid = str(row.get("record_id") or "")
                if rid:
                    if rid in seen_record:
                        raise WebShardError("Duplicate record_id in web extraction merge")
                    seen_record.add(rid)
                rec_h.write(json.dumps(row, ensure_ascii=False) + "\n")
                success_count += 1
                if row.get("content_source") == "Tavily Raw Content":
                    raw_content_ok += 1
                if row.get("taxonomy_confidence") == "Low" or row.get("extraction_confidence") == "Low":
                    low_conf += 1
                branch_counter[str(row.get("sub_subcategory_slug") or "")] += 1
                source_type_counter[str(row.get("source_type") or "")] += 1
            if cp.is_file():
                for cite in iter_jsonl(cp):
                    cit_h.write(json.dumps(cite, ensure_ascii=False) + "\n")

    miss_path = layout["rejected"] / "missing_web_extraction_shards.csv"
    with miss_path.open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=["shard_id", "problems"])
        w.writeheader()
        for row in missing:
            w.writerow(row)
    if missing:
        for tmp in (tmp_records, tmp_cites):
            if tmp.exists():
                tmp.unlink()
        raise WebShardError(f"merge-web-extract failed: {len(missing)} incomplete shards")

    os.replace(tmp_records, records_path)
    os.replace(tmp_cites, cites_path)
    summary = {
        "expected_shard_count": len(shards),
        "completed_shard_count": len(shards),
        "missing_shard_count": 0,
        "url_count": len(url_ids),
        "successfully_fetched_count": raw_content_ok,
        "failed_fetch_count": failed_fetch,
        "extracted_record_count": success_count,
        "malformed_output_count": 0,
        "low_confidence_count": low_conf,
        "records_by_taxonomy_branch": dict(branch_counter),
        "records_by_source_type": dict(source_type_counter),
        "created_at": _now(),
    }
    atomic_write_json(layout["metadata"] / "web_extraction_merge_summary.json", summary)
    write_marker(layout["checkpoints"] / "web_extract.complete")
    write_marker(layout["checkpoints"] / "web_extract_merge.complete")
    return summary


def missing_web_extraction_shards(*, output_dir: str | Path) -> str:
    layout = ensure_web_layout(Path(output_dir))
    shards = _load_manifest(layout["metadata"] / "web_extraction_shards.json")
    bad = []
    for entry in shards:
        sid = int(entry["shard_id"])
        if not (
            Path(entry["expected_output_path"]).is_file()
            and Path(entry["expected_marker_path"]).is_file()
        ):
            bad.append(sid)
    spec = compact_id_list(bad)
    print(spec)
    return spec


# ── Merge literature + web ───────────────────────────────────────────────────


def merge_literature_and_web(*, output_dir: str | Path) -> dict[str, Any]:
    """Merge literature + web records with streaming I/O and lightweight link indexes.

    Full record bodies are written incrementally; in-memory indexes store only
    (record_id, tech, project, subcategory) stubs for overlap linking.
    """
    from pipeline.cementitious.memory import finish_stage_telemetry, start_stage_telemetry

    out = Path(output_dir)
    layout = ensure_web_layout(out)
    telemetry = start_stage_telemetry("merge_literature_web")

    lit_path = layout["metadata"] / "literature_records_raw.jsonl"
    if not lit_path.is_file():
        lit_path = layout["metadata"] / "extracted_records_raw.jsonl"
    web_path = layout["metadata"] / "web_records_raw.jsonl"

    lit_cite_path = None
    for p in (
        layout["metadata"] / "literature_citations_raw.jsonl",
        layout["metadata"] / "extracted_citations_raw.jsonl",
    ):
        if p.is_file():
            lit_cite_path = p
            break
    web_cite_path = layout["metadata"] / "web_citations_raw.jsonl"

    combined_path = layout["metadata"] / "combined_records_pre_dedupe.jsonl"
    cites_path = layout["metadata"] / "combined_citations_pre_dedupe.jsonl"
    audit_path = layout["metadata"] / "literature_web_merge_audit.csv"
    fields = [
        "record_id",
        "evidence_origin",
        "source_id",
        "normalized_technology",
        "project_name",
        "company",
        "location",
        "year",
        "potential_match_record_id",
        "match_type",
        "match_score",
        "merge_action",
        "merge_reason",
    ]

    tech_index: dict[tuple[str, str], list[dict[str, str]]] = {}
    project_index: dict[str, list[dict[str, str]]] = {}
    lit_count = 0
    web_count = 0

    combined_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{combined_path.name}.", dir=str(combined_path.parent))
    tmp_combined = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as comb_handle, audit_path.open(
            "w", encoding="utf-8", newline=""
        ) as audit_handle:
            audit_w = csv.DictWriter(audit_handle, fieldnames=fields)
            audit_w.writeheader()

            if lit_path.is_file():
                for row in iter_jsonl(lit_path):
                    if row.get("extraction_error"):
                        continue
                    rec = normalize_record(row)
                    rec["evidence_origin"] = rec.get("evidence_origin") or "Literature"
                    if not rec.get("source_type"):
                        rec["source_type"] = "Academic Literature"
                    stub = {
                        "record_id": str(rec.get("record_id") or ""),
                        "canonical_technology_name": str(rec.get("canonical_technology_name") or ""),
                        "sub_subcategory_slug": str(rec.get("sub_subcategory_slug") or ""),
                        "project_name": str(rec.get("project_name") or ""),
                    }
                    tech = stub["canonical_technology_name"].casefold()
                    ss = stub["sub_subcategory_slug"]
                    if tech:
                        tech_index.setdefault((ss, tech), []).append(stub)
                    pname = stub["project_name"].casefold()
                    if pname:
                        project_index.setdefault(pname, []).append(stub)
                    comb_handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    lit_count += 1
                    audit_w.writerow(
                        {
                            "record_id": stub["record_id"],
                            "evidence_origin": "Literature",
                            "source_id": rec.get("source_id") or "",
                            "normalized_technology": stub["canonical_technology_name"],
                            "project_name": stub["project_name"],
                            "company": rec.get("company_or_organization") or "",
                            "location": rec.get("location") or "",
                            "year": rec.get("project_year") or "",
                            "potential_match_record_id": "",
                            "match_type": "",
                            "match_score": "",
                            "merge_action": "Keep Separate",
                            "merge_reason": "Literature record retained",
                        }
                    )
                    if lit_count % 200 == 0:
                        check_soft_memory_ceiling(telemetry=telemetry)

            if web_path.is_file():
                for row in iter_jsonl(web_path):
                    if row.get("extraction_error"):
                        continue
                    rec = normalize_record(row)
                    rec["evidence_origin"] = "Web"
                    related: list[str] = []
                    tech = (rec.get("canonical_technology_name") or "").casefold()
                    ss = rec.get("sub_subcategory_slug") or ""
                    pname = (rec.get("project_name") or "").casefold()
                    candidates: list[dict[str, str]] = []
                    if tech:
                        candidates.extend(tech_index.get((ss, tech), []))
                    if pname:
                        candidates.extend(project_index.get(pname, []))
                    seen_lit: set[str] = set()
                    matched_project = False
                    for lit in candidates:
                        lid = lit.get("record_id") or ""
                        if not lid or lid in seen_lit:
                            continue
                        seen_lit.add(lid)
                        same_tech = bool(tech) and (
                            ss == (lit.get("sub_subcategory_slug") or "")
                            and tech == (lit.get("canonical_technology_name") or "").casefold()
                        )
                        same_project = bool(pname) and pname == (lit.get("project_name") or "").casefold()
                        if not (same_tech or same_project):
                            continue
                        related.append(lid)
                        if same_project:
                            matched_project = True
                        audit_w.writerow(
                            {
                                "record_id": rec.get("record_id") or "",
                                "evidence_origin": "Web",
                                "source_id": rec.get("source_id") or "",
                                "normalized_technology": rec.get("canonical_technology_name") or "",
                                "project_name": rec.get("project_name") or "",
                                "company": rec.get("company_or_organization") or "",
                                "location": rec.get("location") or "",
                                "year": rec.get("project_year") or "",
                                "potential_match_record_id": lid,
                                "match_type": "same_project" if same_project else "same_technology",
                                "match_score": "0.8" if same_project else "0.6",
                                "merge_action": "Link as Related Evidence",
                                "merge_reason": "Distinct evidence origins retained",
                            }
                        )
                    if related:
                        rec["related_record_ids"] = json.dumps([r for r in related if r])
                        rec["same_technology_candidate"] = "true"
                        if matched_project:
                            rec["same_project_candidate"] = "true"
                    else:
                        audit_w.writerow(
                            {
                                "record_id": rec.get("record_id") or "",
                                "evidence_origin": "Web",
                                "source_id": rec.get("source_id") or "",
                                "normalized_technology": rec.get("canonical_technology_name") or "",
                                "project_name": rec.get("project_name") or "",
                                "company": rec.get("company_or_organization") or "",
                                "location": rec.get("location") or "",
                                "year": rec.get("project_year") or "",
                                "potential_match_record_id": "",
                                "match_type": "",
                                "match_score": "",
                                "merge_action": "Keep Separate",
                                "merge_reason": "No literature overlap",
                            }
                        )
                    comb_handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    web_count += 1
                    if web_count % 200 == 0:
                        check_soft_memory_ceiling(telemetry=telemetry)

            comb_handle.flush()
            os.fsync(comb_handle.fileno())
            audit_handle.flush()
        os.replace(tmp_combined, combined_path)
    except Exception:
        if tmp_combined.exists():
            tmp_combined.unlink(missing_ok=True)
        finish_stage_telemetry(telemetry, out, status="error")
        raise

    # Citations: stream-copy without materializing both sides at once.
    def _cite_stream():
        if lit_cite_path and lit_cite_path.is_file():
            for c in iter_jsonl(lit_cite_path):
                row = dict(c)
                row["evidence_origin"] = row.get("evidence_origin") or "Literature"
                yield row
        if web_cite_path.is_file():
            for c in iter_jsonl(web_cite_path):
                row = dict(c)
                row["evidence_origin"] = "Web"
                yield row

    atomic_write_jsonl(cites_path, _cite_stream())
    write_marker(layout["checkpoints"] / "merge_literature_web.complete")
    finish_stage_telemetry(
        telemetry,
        out,
        status="complete",
        records_processed=lit_count + web_count,
    )
    return {
        "literature_records": lit_count,
        "web_records": web_count,
        "combined_records": lit_count + web_count,
    }
