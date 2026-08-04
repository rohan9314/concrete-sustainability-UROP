"""End-to-end Cementitious Materials runner."""

from __future__ import annotations

import csv
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.cementitious import RESULTS_DIR_NAME, SCHEMA_VERSION, TAXONOMY_VERSION
from pipeline.cementitious.dedupe import deduplicate_records, write_dedupe_audit
from pipeline.cementitious.export_partitions import export_taxonomy_partitions, write_csv
from pipeline.cementitious.extraction import classify_and_extract, screen_records
from pipeline.cementitious.migrate_carbon_capture import migrate_carbon_capture
from pipeline.cementitious.paths import ensure_730_layout, get_results_root, resolve_output_dir
from pipeline.cementitious.qc import run_qc_pass
from pipeline.cementitious.resume_stages import stage_is_complete
from pipeline.cementitious.schema import PROPOSAL_FIELDS, RECORD_FIELDS
from pipeline.cementitious.taxonomy import Taxonomy, get_taxonomy, load_taxonomy
from pipeline.cementitious.validation_metrics import (
    get_call_metrics,
    reset_call_metrics,
)
from pipeline.config import get_extraction_concurrency, get_pickle_path, get_top_n_sources
from pipeline.corpus_loader import load_paper_records, resolve_pickle_path
from pipeline.llm_utils import DEFAULT_MODEL

logger = logging.getLogger(__name__)


@dataclass
class RunConfig:
    mode: str = "literature-and-web"  # literature-only | web-only | literature-and-web
    sample_size: int | None = None
    seed: int = 42
    start: int = 0
    end: int | None = None
    top_n: int | None = None
    web_limit: int | None = None
    subcategory: str | None = None
    subcategories: list[str] = field(default_factory=list)
    sub_subcategory: str | None = None
    sub_subcategories: list[str] = field(default_factory=list)
    output_dir: str | Path | None = None
    input_path: str | Path | None = None
    taxonomy_path: str | Path | None = None
    dry_run: bool = False
    planning: bool = False
    resume: bool = False
    force: bool = False
    keyword_only: bool = False
    open_discovery: bool = False
    seed_retrieval: bool = True
    migrate_ccs_input: str | Path | None = None
    run_qc: bool = False
    model: str = DEFAULT_MODEL
    concurrency: int | None = None
    allow_missing_citations: bool = False


def _git_info() -> dict[str, Any]:
    info = {"git_commit": None, "git_dirty": None}
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        info["git_commit"] = commit
        info["git_dirty"] = bool(dirty)
    except Exception:
        pass
    return info


def _mark_complete(checkpoints: Path, name: str) -> None:
    (checkpoints / f"{name}.complete").write_text(
        datetime.now(timezone.utc).isoformat(),
        encoding="utf-8",
    )


def _is_complete(checkpoints: Path, name: str, *, output_dir: Path, resume: bool, force: bool) -> bool:
    """Backward-compatible name; validates stage outputs when resuming."""
    return stage_is_complete(output_dir, name, resume=resume, force=force)


def resolve_selection(config: RunConfig, taxonomy: Taxonomy) -> tuple[list[str], list[str]]:
    sub_slugs: list[str] = []
    ss_slugs: list[str] = []
    if config.subcategory:
        sub_slugs.append(taxonomy.resolve_slug(config.subcategory, level="subcategory"))
    for item in config.subcategories:
        sub_slugs.append(taxonomy.resolve_slug(item, level="subcategory"))
    if config.sub_subcategory:
        ss_slugs.append(
            taxonomy.resolve_slug(config.sub_subcategory, level="sub_subcategory")
        )
    for item in config.sub_subcategories:
        ss_slugs.append(taxonomy.resolve_slug(item, level="sub_subcategory"))
    # Deduplicate preserve order
    sub_slugs = list(dict.fromkeys(sub_slugs))
    ss_slugs = list(dict.fromkeys(ss_slugs))
    if ss_slugs and not sub_slugs:
        sub_slugs = list(
            dict.fromkeys(taxonomy.parent_of_sub_sub[s] for s in ss_slugs)
        )
    return sub_slugs, ss_slugs


def build_plan(config: RunConfig, taxonomy: Taxonomy) -> dict[str, Any]:
    sub_slugs, ss_slugs = resolve_selection(config, taxonomy)
    output_dir = resolve_output_dir(config.output_dir)
    pickle_path = None
    corpus_size = None
    try:
        pickle_path = str(resolve_pickle_path(config.input_path, announce=False))
        if Path(pickle_path).is_file():
            # Avoid loading full corpus during plan unless needed
            corpus_size = None
    except Exception as exc:
        pickle_path = f"unresolved: {exc}"
    return {
        "taxonomy_version": taxonomy.taxonomy_version,
        "schema_version": taxonomy.schema_version or SCHEMA_VERSION,
        "mode": config.mode,
        "sample_size": config.sample_size,
        "seed": config.seed,
        "selected_subcategories": sub_slugs or list(taxonomy.subcategories.keys()),
        "selected_sub_subcategories": ss_slugs
        or (
            [c.slug for s in sub_slugs for c in taxonomy.children_of(s)]
            if sub_slugs
            else list(taxonomy.sub_subcategories.keys())
        ),
        "output_dir": str(output_dir),
        "results_root": str(get_results_root()),
        "results_dirname": RESULTS_DIR_NAME,
        "pickle_path": pickle_path,
        "corpus_size": corpus_size,
        "top_n": config.top_n or get_top_n_sources(),
        "web_limit": config.web_limit
        or int(os.getenv("WEB_LIMIT", "50") or 50),
        "concurrency": config.concurrency or get_extraction_concurrency(),
        "open_discovery": config.open_discovery,
        "seed_retrieval": config.seed_retrieval,
        "dry_run": config.dry_run,
        "keyword_only": config.keyword_only,
        "model": config.model,
    }


def _sample_records(records: list[dict], sample_size: int, seed: int) -> list[dict]:
    import random

    if sample_size >= len(records):
        return list(records)
    rng = random.Random(seed)
    indices = sorted(rng.sample(range(len(records)), sample_size))
    return [records[i] for i in indices]


def run_pipeline(config: RunConfig) -> dict[str, Any]:
    metrics = reset_call_metrics()
    if config.keyword_only:
        metrics.mark_keyword_only()
    taxonomy = load_taxonomy(config.taxonomy_path) if config.taxonomy_path else get_taxonomy()
    plan = build_plan(config, taxonomy)
    output_dir = Path(plan["output_dir"])
    layout = ensure_730_layout(output_dir)
    start_time = datetime.now(timezone.utc)

    (layout["metadata"] / "job_plan.json").write_text(
        json.dumps(plan, indent=2),
        encoding="utf-8",
    )

    if config.planning or config.dry_run:
        logger.info("Plan-only / dry-run complete: %s", plan)
        return {"plan": plan, "status": "planned"}

    sub_slugs, ss_slugs = resolve_selection(config, taxonomy)
    if config.resume and _is_complete(
        layout["checkpoints"], "export", output_dir=output_dir, resume=True, force=config.force
    ):
        logger.info("Export already complete; use --force to regenerate")
        return {"status": "skipped_complete", "output_dir": str(output_dir)}

    literature_only = config.mode in {"literature-only", "literature_only"}
    web_only = config.mode in {"web-only", "web_only"}
    need_lit = not web_only
    need_web = not literature_only

    if need_web and not os.getenv("TAVILY_API_KEY", "").strip():
        raise RuntimeError("TAVILY_API_KEY is required for web modes")

    # Apply web limit env overrides from config when provided
    if config.web_limit is not None:
        os.environ.setdefault("WEB_MAX_TOTAL_URLS", str(config.web_limit))

    records: list[dict] = []
    if need_lit:
        plan_done = _is_complete(
            layout["checkpoints"], "plan", output_dir=output_dir, resume=config.resume, force=config.force
        )
        if not plan_done:
            corpus_path = resolve_pickle_path(config.input_path, announce=True)
            records = load_paper_records(corpus_path)
            if config.end is not None:
                records = records[config.start : config.end]
            elif config.start:
                records = records[config.start :]
            if config.sample_size:
                records = _sample_records(records, config.sample_size, config.seed)
            sample_path = layout["metadata"] / "working_sample.jsonl"
            with sample_path.open("w", encoding="utf-8") as handle:
                for rec in records:
                    handle.write(
                        json.dumps(
                            {
                                "title": rec.get("title"),
                                "doi": rec.get("doi"),
                                "abstract": (rec.get("abstract") or "")[:2000],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            plan["corpus_size"] = len(records)
            plan["input_corpus_path"] = str(corpus_path)
            (layout["metadata"] / "job_plan.json").write_text(
                json.dumps(plan, indent=2),
                encoding="utf-8",
            )
            _mark_complete(layout["checkpoints"], "plan")
        else:
            corpus_path = resolve_pickle_path(config.input_path, announce=True)
            records = load_paper_records(corpus_path)
            if config.sample_size:
                records = _sample_records(records, config.sample_size, config.seed)
            plan["input_corpus_path"] = str(corpus_path)

    extracted: list[dict[str, str]] = []
    proposals: list[dict[str, str]] = []

    if need_lit:
        # Screen
        screen_done = _is_complete(
            layout["checkpoints"], "screen", output_dir=output_dir, resume=config.resume, force=config.force
        )
        if not screen_done:
            screening = screen_records(
                records,
                taxonomy=taxonomy,
                keyword_only=config.keyword_only,
                model=config.model,
                focus_sub_slugs=sub_slugs or None,
                focus_ss_slugs=ss_slugs or None,
                failed_dir=layout["logs"],
                concurrency=config.concurrency,
            )
            screen_path = layout["metadata"] / "screening_results.jsonl"
            with screen_path.open("w", encoding="utf-8") as handle:
                for row in screening:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            _mark_complete(layout["checkpoints"], "screen")
            _mark_complete(layout["checkpoints"], "screen_merge")
        else:
            screening = []
            screen_path = layout["metadata"] / "screening_results.jsonl"
            if screen_path.is_file():
                for line in screen_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        screening.append(json.loads(line))

        relevant_ids = {row["paper_id"] for row in screening if row.get("is_relevant")}
        from pipeline.record_utils import record_dedupe_key

        candidates = []
        for idx, rec in enumerate(records):
            pid = record_dedupe_key(rec) or f"paper:{idx}"
            if pid in relevant_ids or config.keyword_only and not screening:
                candidates.append(rec)
        if not candidates and config.keyword_only:
            candidates = records[: max(1, min(len(records), config.top_n or 20))]

        top_n = config.top_n or get_top_n_sources()
        candidates = candidates[:top_n]

        extract_done = _is_complete(
            layout["checkpoints"], "extract", output_dir=output_dir, resume=config.resume, force=config.force
        )
        if not extract_done:
            for rec in candidates:
                try:
                    row, proposal = classify_and_extract(
                        rec,
                        taxonomy=taxonomy,
                        model=config.model,
                        selected_sub_slugs=sub_slugs or None,
                        selected_ss_slugs=ss_slugs or None,
                        allow_proposals=config.open_discovery or True,
                        failed_dir=layout["logs"],
                        source_type="Academic Literature",
                        keyword_only=config.keyword_only,
                    )
                except Exception as exc:
                    logger.warning("Extraction failed: %s", exc)
                    get_call_metrics().record_llm_fallback(reason=str(exc))
                    continue
                if row:
                    row["evidence_origin"] = "Literature"
                    if ss_slugs and row.get("sub_subcategory_slug") not in ss_slugs:
                        continue
                    if sub_slugs and row.get("subcategory_slug") not in sub_slugs:
                        continue
                    extracted.append(row)
                if proposal:
                    proposals.append(
                        {
                            "raw_term": str(proposal.get("raw_term") or ""),
                            "proposed_canonical_name": str(
                                proposal.get("proposed_canonical_name") or ""
                            ),
                            "proposed_level": str(proposal.get("proposed_level") or "technology_variant"),
                            "proposed_parent": str(proposal.get("proposed_parent") or ""),
                            "definition": str(proposal.get("definition") or ""),
                            "source_record_id": row["record_id"] if row else "",
                            "source_title": str(rec.get("title") or ""),
                            "evidence_text": str(proposal.get("evidence_text") or ""),
                            "reason_existing_taxonomy_is_insufficient": str(
                                proposal.get("reason_existing_taxonomy_is_insufficient")
                                or ""
                            ),
                            "suggested_synonyms": json.dumps(
                                proposal.get("suggested_synonyms") or []
                            ),
                            "confidence": str(proposal.get("confidence") or ""),
                            "review_status": "Pending Review",
                        }
                    )
            _mark_complete(layout["checkpoints"], "extract")
            _mark_complete(layout["checkpoints"], "extract_merge")

        # Persist literature aliases for merge stage
        from pipeline.cementitious.shard_io import atomic_write_jsonl

        for row in extracted:
            row.setdefault("evidence_origin", "Literature")
        atomic_write_jsonl(layout["metadata"] / "literature_records_raw.jsonl", extracted)
        atomic_write_jsonl(layout["metadata"] / "extracted_records_raw.jsonl", extracted)

    web_extracted: list[dict[str, Any]] = []
    if need_web:
        from pipeline.cementitious.web_config import load_web_limits
        from pipeline.cementitious.web_stages import (
            merge_web_extractions,
            merge_web_search,
            plan_web_extraction,
            plan_web_query_shards,
            web_extract_shard,
            web_search_shard,
        )

        limits = load_web_limits()
        plan_web = plan_web_query_shards(
            output_dir=output_dir,
            taxonomy=taxonomy,
            limits=limits,
            selected_subcategories=sub_slugs or None,
            selected_sub_subcategories=ss_slugs or None,
        )
        plan["web_query_plan"] = plan_web
        shards = json.loads((layout["metadata"] / "web_query_shards.json").read_text(encoding="utf-8"))
        for entry in shards:
            web_search_shard(
                shard_id=int(entry["shard_id"]),
                output_dir=output_dir,
                resume=config.resume and not config.force,
                limits=limits,
            )
        merge_web_search(output_dir=output_dir)
        plan_web_extraction(output_dir=output_dir, limits=limits)
        extract_shards = json.loads(
            (layout["metadata"] / "web_extraction_shards.json").read_text(encoding="utf-8")
        )
        for entry in extract_shards:
            web_extract_shard(
                shard_id=int(entry["shard_id"]),
                output_dir=output_dir,
                resume=config.resume and not config.force,
                keyword_only=config.keyword_only,
                model=config.model,
                taxonomy=taxonomy,
                limits=limits,
            )
        merge_web_extractions(output_dir=output_dir)
        web_path = layout["metadata"] / "web_records_raw.jsonl"
        if web_path.is_file():
            for line in web_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    web_extracted.append(json.loads(line))

    if need_lit and need_web:
        from pipeline.cementitious.web_stages import merge_literature_and_web

        merge_literature_and_web(output_dir=output_dir)
        combined_path = layout["metadata"] / "combined_records_pre_dedupe.jsonl"
        extracted = []
        if combined_path.is_file():
            for line in combined_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    extracted.append(json.loads(line))
    elif need_web and not need_lit:
        from pipeline.cementitious.web_stages import merge_literature_and_web

        merge_literature_and_web(output_dir=output_dir)
        extracted = [r for r in web_extracted if not r.get("extraction_error")]
        combined_path = layout["metadata"] / "combined_records_pre_dedupe.jsonl"
        if combined_path.is_file():
            extracted = []
            for line in combined_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    extracted.append(json.loads(line))

    # Optional CCS migration inclusion
    if config.migrate_ccs_input:
        mig = migrate_carbon_capture(
            input_path=config.migrate_ccs_input,
            output_dir=output_dir,
        )
        mig_csv = layout["metadata"] / "migrated_carbon_capture_records.csv"
        if mig_csv.is_file():
            with mig_csv.open("r", encoding="utf-8", newline="") as handle:
                extracted.extend(list(csv.DictReader(handle)))

    # Dedup
    extracted, audit = deduplicate_records(extracted)
    write_dedupe_audit(layout["metadata"] / "deduplication_audit.csv", audit)

    # Proposals
    write_csv(
        layout["metadata"] / "taxonomy_proposals.csv",
        PROPOSAL_FIELDS,
        proposals,
    )

    # Intermediate merged CSV for export
    merged_path = layout["metadata"] / "merged_records.csv"
    write_csv(merged_path, RECORD_FIELDS, extracted)

    if config.run_qc:
        run_qc_pass(
            extracted,
            output_path=layout["metadata"] / "qc_review.csv",
            model=config.model,
            use_llm=not config.keyword_only,
        )

    # Export partitions
    export_summary = export_taxonomy_partitions(
        input_path=merged_path,
        output_dir=output_dir,
        taxonomy=taxonomy,
        force=config.force,
        allow_missing_citations=config.allow_missing_citations,
    )
    _mark_complete(layout["checkpoints"], "export")

    end_time = datetime.now(timezone.utc)
    from pipeline.cementitious.web_config import load_web_limits

    web_limits = load_web_limits().to_dict() if need_web else {}
    metrics_payload = get_call_metrics().to_dict()
    env_used = {
        key: ("set" if os.getenv(key) else "unset")
        for key in (
            "OPENAI_API_KEY",
            "TAVILY_API_KEY",
            "PICKLE_PATH",
            "PAPER_RECORDS_PATH",
            "RESULTS_ROOT",
            "TAXONOMY_PATH",
            "TOP_N",
            "TOP_N_SOURCES",
            "WEB_LIMIT",
            "SHARD_SIZE",
            "CONCURRENCY",
            "EXTRACTION_CONCURRENCY",
            "RUN_MODE",
            "SELECTED_SUBCATEGORIES",
            "SELECTED_SUB_SUBCATEGORIES",
            "CHECKPOINT_DIR",
            *web_limits.keys(),
        )
    }
    env_resolved = {
        "RESULTS_ROOT": str(get_results_root()),
        "TOP_N_SOURCES": str(get_top_n_sources()),
        "EXTRACTION_CONCURRENCY": str(get_extraction_concurrency()),
        "OPENAI_MODEL": config.model,
        **{k: str(v) for k, v in web_limits.items()},
    }
    run_manifest = {
        **_git_info(),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "model_names": [config.model],
        "input_corpus_path": plan.get("input_corpus_path"),
        "corpus_size": plan.get("corpus_size"),
        "sample_size": config.sample_size,
        "random_seed": config.seed,
        "retrieval_settings": {
            "top_n": plan["top_n"],
            "seed_retrieval": config.seed_retrieval,
            "open_discovery": config.open_discovery,
            "selected_subcategories": plan["selected_subcategories"],
            "selected_sub_subcategories": plan["selected_sub_subcategories"],
        },
        "web_settings": {
            "mode": config.mode,
            "web_limit": plan["web_limit"],
            "enabled": need_web,
            "limits": web_limits,
        },
        "shard_settings": {
            "shard_size": os.getenv("SHARD_SIZE", ""),
        },
        "concurrency": plan["concurrency"],
        "environment_variables_present": env_used,
        "environment_resolved_nonsecret": env_resolved,
        "taxonomy_version": TAXONOMY_VERSION,
        "schema_version": SCHEMA_VERSION,
        "output_directory": str(output_dir),
        "commands_used": [
            "python -m pipeline.run_cementitious_materials run",
        ],
        "failures_and_retries": [],
        "export_summary": {
            k: v for k, v in export_summary.items() if k != "validation_report"
        },
        "records_extracted": len(extracted),
        "proposals": len(proposals),
        **metrics_payload,
        "pending_taxonomy_review_count": (
            (export_summary.get("validation_report") or {}).get("pending_taxonomy_review_count")
            or 0
        ),
    }
    # Merge validation metrics into validation_report.json
    vr_path = layout["all_records"] / "validation_report.json"
    if vr_path.is_file():
        try:
            vr = json.loads(vr_path.read_text(encoding="utf-8"))
            vr.update(metrics_payload)
            vr_path.write_text(json.dumps(vr, indent=2), encoding="utf-8")
        except Exception:
            pass
    (layout["all_records"] / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2),
        encoding="utf-8",
    )
    status = "ok"
    return {
        "status": status,
        "run_status": metrics_payload.get("run_status"),
        "output_dir": str(output_dir),
        "records": len(extracted),
        "export": export_summary,
        "plan": plan,
        "validation_metrics": metrics_payload,
        "qualifies_as_live_llm_validation": metrics_payload.get(
            "qualifies_as_live_llm_validation"
        ),
    }
