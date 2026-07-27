"""Shared orchestration for SCM seed-category and discovery pipeline runs.

This module never imports carbon-capture runners, configs, or schemas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from pipeline.config import get_top_n_sources
from pipeline.scm.config import (
    CATEGORY_ID,
    CATEGORY_LABEL,
    assert_input_under_scm_root,
    assert_scm_output_isolated,
    ensure_scm_layout,
    scm_output_root,
)
from pipeline.scm.export import (
    ScmExportSummary,
    export_combined_outputs,
    export_discovery_evidence_csv,
    export_seed_category_outputs,
    read_jsonl_discovery,
    read_jsonl_evidence,
    write_jsonl_discovery,
    write_jsonl_evidence,
)
from pipeline.scm.extraction import (
    ScmDiscoveryRow,
    ScmEvidenceRow,
    extract_discovery_from_source,
    extract_discovery_papers_parallel,
    extract_literature_papers_parallel,
    extract_web_sources_parallel,
    format_web_source_for_llm,
)
from pipeline.scm.logging_utils import checkpoint_exists, stage_timer
from pipeline.scm.outputs import (
    discovery_evidence_path,
    discovery_records_path,
    literature_path_for_slug,
    web_path_for_slug,
)
from pipeline.scm.retrieval import retrieve_discovery_papers, retrieve_seed_category_papers
from pipeline.scm.schema import NA, ValidationStats
from pipeline.scm.seed_categories import (
    get_seed_category,
    list_seed_category_ids,
    resolve_seed_category_slug,
)
from pipeline.scm.web import discover_discovery_web_sources, discover_web_sources

logger = logging.getLogger(__name__)

# Hard ceiling so --test-mode cannot accidentally process the full corpus.
TEST_MODE_MAX_CORPUS_SPAN = 500


@dataclass
class ScmRunConfig:
    slugs: list[str] = field(default_factory=list)
    stage: str = "all"
    start: int = 0
    end: int = 5000
    top_n: int | None = None
    paper_limit: int | None = None
    web_limit: int | None = None
    screening_results: str = ""
    input_path: str = ""
    output_dir: Path = field(default_factory=lambda: scm_output_root())
    test_mode: bool = False
    skip_web: bool = False
    skip_literature: bool = False
    retrieve_only: bool = False
    web_max_results_per_query: int = 5
    run_discovery: bool = False
    dry_run: bool = False
    # When True, skip stages whose checkpoints already exist (even in test_mode).
    resume: bool = False

    @property
    def mode_label(self) -> str:
        if self.dry_run:
            return "DRY RUN"
        return "TEST MODE" if self.test_mode else "FULL MODE"

    def effective_paper_limit(self) -> int | None:
        if self.paper_limit is not None:
            return self.paper_limit
        if self.test_mode:
            return 5
        return None

    def effective_web_limit(self) -> int | None:
        if self.web_limit is not None:
            return self.web_limit
        if self.test_mode:
            return 5
        return None

    def effective_top_n(self) -> int:
        # Explicit --top-n always wins so paper_limit can mean sample size.
        if self.top_n is not None:
            return self.top_n
        limit = self.effective_paper_limit()
        if limit is not None and self.test_mode:
            return limit
        return get_top_n_sources()

    def effective_start_end(self) -> tuple[int, int]:
        start, end = self.start, self.end
        if self.test_mode:
            span = max(0, end - start)
            cap = self.effective_paper_limit() or 5
            # Prefer the caller's explicit end when it is already within the paper limit.
            if span > 0 and span <= cap:
                max_span = span
            else:
                max_span = max(cap, min(TEST_MODE_MAX_CORPUS_SPAN, max(span, cap)))
            if span > max_span or span <= 0:
                end = start + max_span
            logger.info(
                "[%s] Constrained corpus window to %s-%s (span cap %s)",
                self.mode_label,
                start,
                end,
                max_span,
            )
        return start, end

    def validated_output_dir(self) -> Path:
        return assert_scm_output_isolated(self.output_dir)

    def validated_screening_path(self) -> str | None:
        if not self.screening_results:
            return None
        # Optional screening inputs must live under the SCM root when provided as
        # relative paths inside the SCM tree. Absolute paths outside SCM are rejected.
        path = Path(self.screening_results)
        if not path.is_absolute():
            path = self.validated_output_dir() / path
        return str(
            assert_input_under_scm_root(
                path,
                self.validated_output_dir(),
                label="SCM screening",
            ),
        )


def resolve_scm_output_dir(*, raw: str, test_mode: bool) -> Path:
    return scm_output_root(raw, test_mode=test_mode)


def slugs_from_args(
    *,
    subcategory: str = "",
    run_all: bool = False,
) -> list[str]:
    if run_all:
        return list_seed_category_ids()
    if subcategory:
        return [resolve_seed_category_slug(subcategory)]
    return []


def print_dry_run(config: ScmRunConfig) -> None:
    start, end = config.effective_start_end()
    out = config.validated_output_dir()
    print("=== SCM dry run ===")
    print(f"Selected category: SCM ({CATEGORY_ID})")
    print(f"Category label: {CATEGORY_LABEL}")
    print(f"Selected SCM branch: {config.stage}")
    print(
        f"Selected SCM subcategories: "
        f"{', '.join(config.slugs) if config.slugs else '(none — discovery-only or plan)'}",
    )
    print(f"Run discovery: {config.run_discovery}")
    print(f"Corpus window: {start}-{end}")
    print(f"Input corpus path: {config.input_path or '(PICKLE_PATH / PAPER_RECORDS_PATH)'}")
    print(f"Screening results: {config.screening_results or '(none)'}")
    print(f"SCM output root: {out}")
    print(f"Test mode: {config.test_mode}")
    print(f"Web retrieval enabled: {not config.skip_web}")
    print(f"Literature enabled: {not config.skip_literature}")
    print(f"Paper limit: {config.effective_paper_limit()}")
    print(f"Web limit: {config.effective_web_limit()}")
    print(f"Top-N: {config.effective_top_n()}")
    print("Cluster execution: disabled (local dry-run)")
    print("Carbon-capture execution: disabled")
    print("Carbon-capture outputs will not be read or modified")
    print("=== end dry run (no papers processed, no APIs called, no CSVs written) ===")


def run_seed_literature(
    config: ScmRunConfig,
    slug: str,
    stats: ValidationStats,
) -> list[ScmEvidenceRow]:
    category = get_seed_category(slug)
    start, end = config.effective_start_end()
    top_n = config.effective_top_n()
    out_path = literature_path_for_slug(config.validated_output_dir(), slug)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with stage_timer(
        category=CATEGORY_ID,
        subcategory_or_discovery=slug,
        stage="extract-literature",
    ) as log:
        checkpoint = config.validated_output_dir() / "checkpoints" / f"{slug}_literature.done"
        if (
            checkpoint_exists(out_path)
            and checkpoint_exists(checkpoint)
            and (config.resume or not config.test_mode)
        ):
            existing = read_jsonl_evidence(out_path)
            log.skipped_count = len(existing)
            log.output_count = len(existing)
            log.output_path = str(out_path)
            logger.info("Resume: skipping completed SCM literature for %s", slug)
            return existing

        ranked = retrieve_seed_category_papers(
            category,
            start=start,
            end=end,
            top_n=top_n,
            screening_results=config.validated_screening_path(),
            input_path=config.input_path or None,
            include_full_text=not config.retrieve_only,
        )
        log.input_count = len(ranked)
        if config.retrieve_only:
            log.output_count = len(ranked)
            return []

        rows = extract_literature_papers_parallel(ranked, category, stats=stats)
        write_jsonl_evidence(out_path, rows)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(f"complete rows={len(rows)}\n", encoding="utf-8")
        log.output_count = len(rows)
        log.output_path = str(out_path)
        return rows


def run_seed_web(
    config: ScmRunConfig,
    slug: str,
    literature_rows: list[ScmEvidenceRow],
    stats: ValidationStats,
) -> list[ScmEvidenceRow]:
    category = get_seed_category(slug)
    out_path = web_path_for_slug(config.validated_output_dir(), slug)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    web_cap = config.effective_web_limit()

    with stage_timer(
        category=CATEGORY_ID,
        subcategory_or_discovery=slug,
        stage="extract-web",
    ) as log:
        checkpoint = config.validated_output_dir() / "checkpoints" / f"{slug}_web.done"
        if (
            checkpoint_exists(out_path)
            and checkpoint_exists(checkpoint)
            and (config.resume or not config.test_mode)
        ):
            existing = read_jsonl_evidence(out_path)
            log.skipped_count = len(existing)
            log.output_count = len(existing)
            log.output_path = str(out_path)
            return existing

        sources = discover_web_sources(
            category,
            seed_rows=literature_rows,
            max_results_per_query=config.web_max_results_per_query,
            max_total_sources=web_cap,
        )
        log.input_count = len(sources)
        rows = (
            extract_web_sources_parallel(sources, category, stats=stats) if sources else []
        )
        write_jsonl_evidence(out_path, rows)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(f"complete rows={len(rows)}\n", encoding="utf-8")
        log.output_count = len(rows)
        log.output_path = str(out_path)
        return rows


# Stages that should extract (or merge) seed literature/web when invoked via
# run_seed_category — includes orchestrator stages that loop over seeds.
_SEED_LITERATURE_STAGES = {
    "all",
    "literature",
    "extract-literature",
    "run-seed-category",
    "run-all-seed-categories",
    "run-all",
}
_SEED_WEB_STAGES = {
    "all",
    "web",
    "extract-web",
    "run-seed-category",
    "run-all-seed-categories",
    "run-all",
}
_SEED_EXPORT_STAGES = {
    "all",
    "merge",
    "merge-evidence",
    "run-seed-category",
    "run-all-seed-categories",
    "run-all",
}


def run_seed_category(config: ScmRunConfig, slug: str) -> ScmExportSummary:
    """Run exactly one SCM seed subcategory. Never runs discovery or other seeds."""
    if config.dry_run:
        print_dry_run(config)
        return ScmExportSummary()

    ensure_scm_layout(config.validated_output_dir())
    stats = ValidationStats()
    literature_rows: list[ScmEvidenceRow] = []
    web_rows: list[ScmEvidenceRow] = []
    root = config.validated_output_dir()

    if not config.skip_literature and config.stage in _SEED_LITERATURE_STAGES:
        literature_rows = run_seed_literature(config, slug, stats)
    else:
        literature_rows = read_jsonl_evidence(literature_path_for_slug(root, slug))

    if not config.skip_web and config.stage in _SEED_WEB_STAGES:
        web_rows = run_seed_web(config, slug, literature_rows, stats)
    elif config.stage in _SEED_EXPORT_STAGES and not config.skip_web:
        # Resume/merge path: load prior web evidence only when web is enabled.
        web_rows = read_jsonl_evidence(web_path_for_slug(root, slug))

    if config.stage in {"literature", "extract-literature", "web", "extract-web"}:
        return ScmExportSummary(
            literature_records=len(literature_rows),
            web_records=len(web_rows),
        )

    return export_seed_category_outputs(
        literature_rows=literature_rows,
        web_rows=web_rows,
        category=get_seed_category(slug),
        output_dir=root,
        stats=stats,
    )


def run_all_seed_categories(config: ScmRunConfig) -> list[ScmExportSummary]:
    """Run only the eight SCM seed categories. Does not run discovery."""
    if config.dry_run:
        print_dry_run(replace(config, slugs=config.slugs or list_seed_category_ids()))
        return []

    summaries: list[ScmExportSummary] = []
    slugs = config.slugs or list_seed_category_ids()
    for slug in slugs:
        try:
            summaries.append(run_seed_category(config, slug))
        except Exception as exc:
            logger.exception("SCM seed category %s failed: %s", slug, exc)
    return summaries


def run_discovery(config: ScmRunConfig) -> list[ScmDiscoveryRow]:
    """Open-ended discovery only. Does not run seed-category extraction."""
    if config.dry_run:
        print_dry_run(replace(config, run_discovery=True, slugs=[]))
        return []

    ensure_scm_layout(config.validated_output_dir())
    stats = ValidationStats()
    start, end = config.effective_start_end()
    top_n = config.effective_top_n()
    out_path = discovery_records_path(config.validated_output_dir())
    csv_path = discovery_evidence_path(config.validated_output_dir())
    checkpoint = config.validated_output_dir() / "checkpoints" / "discovery.done"

    with stage_timer(
        category=CATEGORY_ID,
        subcategory_or_discovery="discovery",
        stage="discover",
    ) as log:
        if (
            checkpoint_exists(out_path)
            and checkpoint_exists(checkpoint)
            and (config.resume or not config.test_mode)
        ):
            rows = read_jsonl_discovery(out_path)
            log.skipped_count = len(rows)
            log.output_count = len(rows)
            log.output_path = str(out_path)
            logger.info("Resume: skipping completed SCM discovery")
            return rows

        rows: list[ScmDiscoveryRow] = []
        if not config.skip_literature:
            ranked = retrieve_discovery_papers(
                start=start,
                end=end,
                top_n=top_n,
                screening_results=config.validated_screening_path(),
                input_path=config.input_path or None,
            )
            log.input_count += len(ranked)
            rows.extend(extract_discovery_papers_parallel(ranked, stats=stats))

        if not config.skip_web:
            sources = discover_discovery_web_sources(
                max_results_per_query=config.web_max_results_per_query,
                max_total_sources=config.effective_web_limit(),
            )
            log.input_count += len(sources)
            for source in sources:
                rows.extend(
                    extract_discovery_from_source(
                        source_content=format_web_source_for_llm(source),
                        source_type="Web",
                        source_id=str(source.get("url") or source.get("title") or NA),
                        source_title=str(source.get("title") or NA),
                        source_url=str(source.get("url") or ""),
                        source_origin="web",
                        stats=stats,
                    ),
                )

        write_jsonl_discovery(out_path, rows)
        export_discovery_evidence_csv(csv_path, rows)
        # Flat convenience copy
        export_discovery_evidence_csv(
            config.validated_output_dir() / csv_path.name,
            rows,
        )
        # Literature-only discovery view (web rows still included when present;
        # filtered copy helps pilot inspection).
        lit_only = [r for r in rows if r.source_type == "Literature"]
        export_discovery_evidence_csv(
            config.validated_output_dir()
            / "discovery"
            / "scm_discovery_literature_evidence.csv",
            lit_only,
        )
        if stats.warnings:
            from pipeline.scm.export import _append_validation_warnings

            _append_validation_warnings(
                config.validated_output_dir() / "validation" / "validation_warnings.csv",
                stats.warnings,
                subcategory_or_discovery="discovery",
            )
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(f"complete rows={len(rows)}\n", encoding="utf-8")
        log.output_count = len(rows)
        log.output_path = str(csv_path)
        for warning in stats.warnings[:20]:
            logger.warning("SCM discovery validation: %s", warning)
        return rows


def merge_all_evidence(config: ScmRunConfig) -> ScmExportSummary:
    """Merge SCM seed + discovery evidence only. Never reads carbon-capture files."""
    if config.dry_run:
        print_dry_run(config)
        return ScmExportSummary()

    root = config.validated_output_dir()
    ensure_scm_layout(root)
    seed_rows: list[ScmEvidenceRow] = []
    for slug in list_seed_category_ids():
        seed_rows.extend(read_jsonl_evidence(literature_path_for_slug(root, slug)))
        seed_rows.extend(read_jsonl_evidence(web_path_for_slug(root, slug)))
        # Backward-compatible flat filenames from earlier SCM layouts.
        category = get_seed_category(slug)
        seed_rows.extend(read_jsonl_evidence(root / category.literature_filename))
        seed_rows.extend(read_jsonl_evidence(root / category.web_filename))

    discovery_rows = read_jsonl_discovery(discovery_records_path(root))
    if not discovery_rows:
        discovery_rows = read_jsonl_discovery(root / "discovery_records.jsonl")

    from pipeline.scm.discovery import discovery_row_to_evidence_bridge
    from pipeline.scm.schema import validate_and_normalize_evidence_row

    discovery_evidence = [
        ScmEvidenceRow.from_dict(
            validate_and_normalize_evidence_row(discovery_row_to_evidence_bridge(row)),
        )
        for row in discovery_rows
    ]
    return export_combined_outputs(
        seed_rows=seed_rows,
        discovery_evidence_rows=discovery_evidence,
        output_dir=root,
    )


def run_scm_pipeline(config: ScmRunConfig) -> None:
    """
    Explicit SCM orchestration.

    - run-discovery / discover: discovery only
    - run-all-seed-categories: eight seed categories only
    - run-all / all: seeds then discovery then merge
    Never invokes carbon-capture code.
    """
    logger.info("Starting SCM pipeline in %s", config.mode_label)
    logger.info("Output dir: %s", config.validated_output_dir())

    if config.dry_run:
        print_dry_run(config)
        return

    ensure_scm_layout(config.validated_output_dir())

    stage = config.stage
    if stage in {"discover", "run-discovery"} or (
        config.run_discovery and stage not in {"run-all", "all", "merge-evidence"}
    ):
        run_discovery(config)
        return

    if stage in {"run-all-seed-categories"}:
        run_all_seed_categories(config)
        return

    if stage in {"run-seed-category"}:
        if not config.slugs:
            raise ValueError("run-seed-category requires --subcategory")
        run_seed_category(config, config.slugs[0])
        return

    if stage in {"merge-evidence"}:
        merge_all_evidence(config)
        return

    if stage in {"run-all", "all"}:
        run_all_seed_categories(config)
        run_discovery(config)
        merge_all_evidence(config)
        return

    # Fallback: if slugs were provided without an explicit discovery flag, run those seeds only.
    if config.slugs and not config.run_discovery:
        run_all_seed_categories(config)
