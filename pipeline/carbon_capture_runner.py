"""Shared orchestration for full and test carbon capture pipeline runs."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.carbon_capture_config import get_methodology, list_methodology_slugs
from pipeline.carbon_capture_export import (
    PipelineExportSummary,
    export_pipeline_outputs,
    log_export_summary,
    merge_existing_outputs,
    read_jsonl_rows,
    write_jsonl_rows,
)
from pipeline.carbon_capture_extraction import (
    CarbonCaptureRow,
    extract_literature_papers_parallel,
    extract_web_sources_parallel,
)
from pipeline.carbon_capture_outputs import literature_records_path, web_records_path
from pipeline.carbon_capture_retrieval import retrieve_methodology_papers
from pipeline.carbon_capture_schema import ValidationStats
from pipeline.carbon_capture_validation_report import (
    VALIDATION_REPORT_FILENAME,
    build_validation_report,
    write_validation_report,
)
from pipeline.carbon_capture_web import discover_web_sources
from pipeline.config import get_output_dir, get_top_n_sources

logger = logging.getLogger(__name__)

DEFAULT_TEST_OUTPUT_DIR = "test_run"


@dataclass
class CarbonCaptureRunConfig:
    slugs: list[str]
    stage: str = "all"
    start: int = 0
    end: int = 5000
    top_n: int | None = None
    paper_limit: int | None = None
    web_limit: int | None = None
    screening_results: str = ""
    input_path: str = ""
    output_dir: Path = field(default_factory=get_output_dir)
    test_mode: bool = False
    skip_web: bool = False
    skip_literature: bool = False
    retrieve_only: bool = False
    web_max_results_per_query: int = 5

    @property
    def mode_label(self) -> str:
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
        limit = self.effective_paper_limit()
        if limit is not None:
            return limit
        return self.top_n or get_top_n_sources()


def resolve_output_dir(
    *,
    raw: str,
    test_mode: bool,
) -> Path:
    """Resolve output directory with safe defaults for test runs."""
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            raw_posix = path.as_posix()
            if raw_posix.startswith("outputs/"):
                path = Path(raw_posix[len("outputs/") :])
            resolved = (get_output_dir() / path).resolve()
        else:
            resolved = path.resolve()
    elif test_mode:
        resolved = (get_output_dir() / DEFAULT_TEST_OUTPUT_DIR).resolve()
    else:
        resolved = get_output_dir().resolve()

    production_root = get_output_dir().resolve()
    if test_mode and resolved == production_root:
        logger.warning(
            "TEST MODE writing to production output root (%s). "
            "Use --output-dir test_run to avoid overwriting production files.",
            production_root,
        )
    return resolved


def run_literature_stage(config: CarbonCaptureRunConfig, stats: ValidationStats) -> list[CarbonCaptureRow]:
    rows: list[CarbonCaptureRow] = []
    top_n = config.effective_top_n()

    for slug in config.slugs:
        methodology = get_methodology(slug)
        logger.info("[%s] Literature retrieval: %s (top_n=%s)", config.mode_label, methodology.display_name, top_n)
        ranked = retrieve_methodology_papers(
            methodology,
            start=config.start,
            end=config.end,
            top_n=top_n,
            screening_results=config.screening_results or None,
            input_path=config.input_path or None,
            include_full_text=not config.retrieve_only,
        )
        if config.retrieve_only:
            logger.info("Retrieve-only: ranked %s papers for %s", len(ranked), slug)
            continue
        if ranked:
            rows.extend(
                extract_literature_papers_parallel(ranked, methodology, stats=stats),
            )

    if not config.retrieve_only:
        write_jsonl_rows(literature_records_path(config.output_dir), rows)
        logger.info(
            "[%s] Wrote %s literature rows -> %s",
            config.mode_label,
            len(rows),
            literature_records_path(config.output_dir),
        )
    return rows


def run_web_stage(
    config: CarbonCaptureRunConfig,
    stats: ValidationStats,
    literature_rows: list[CarbonCaptureRow] | None = None,
) -> list[CarbonCaptureRow]:
    if literature_rows is None:
        literature_rows = read_jsonl_rows(literature_records_path(config.output_dir))

    web_cap = config.effective_web_limit()
    rows: list[CarbonCaptureRow] = []

    for slug in config.slugs:
        methodology = get_methodology(slug)
        logger.info("[%s] Web search: %s (web_limit=%s)", config.mode_label, methodology.display_name, web_cap)
        methodology_literature = [
            row for row in literature_rows if row.methodology_slug == slug
        ]
        sources = discover_web_sources(
            methodology,
            seed_rows=methodology_literature,
            max_results_per_query=config.web_max_results_per_query,
            max_total_sources=web_cap,
        )
        if sources:
            rows.extend(
                extract_web_sources_parallel(sources, methodology, stats=stats),
            )

    write_jsonl_rows(web_records_path(config.output_dir), rows)
    logger.info(
        "[%s] Wrote %s web rows -> %s",
        config.mode_label,
        len(rows),
        web_records_path(config.output_dir),
    )
    return rows


def run_carbon_capture_pipeline(config: CarbonCaptureRunConfig) -> PipelineExportSummary:
    """Run literature, web, and merge stages using shared extraction logic."""
    logger.info("Starting carbon capture pipeline in %s", config.mode_label)
    logger.info(
        "Subcategories: %s | output_dir: %s | corpus slice: %s-%s",
        ", ".join(config.slugs),
        config.output_dir,
        config.start,
        config.end,
    )

    stats = ValidationStats()
    literature_rows: list[CarbonCaptureRow] = []
    web_rows: list[CarbonCaptureRow] = []

    if config.stage in {"literature", "all"} and not config.skip_literature:
        literature_rows = run_literature_stage(config, stats)
        if config.retrieve_only:
            return PipelineExportSummary(
                literature_path=str(literature_records_path(config.output_dir)),
            )

    if config.stage == "literature":
        summary = PipelineExportSummary(
            literature_records=len(literature_rows),
            literature_path=str(literature_records_path(config.output_dir)),
        )
        _maybe_write_validation_report(config, literature_rows, [], [], stats, summary)
        return summary

    if config.stage in {"web", "all"} and not config.skip_web:
        web_rows = run_web_stage(config, stats, literature_rows)
    elif config.stage in {"web", "all"}:
        write_jsonl_rows(web_records_path(config.output_dir), [])
        logger.info("[%s] Skipped web stage", config.mode_label)

    if config.stage == "web":
        summary = PipelineExportSummary(
            web_records=len(web_rows),
            web_path=str(web_records_path(config.output_dir)),
        )
        _maybe_write_validation_report(config, literature_rows, web_rows, [], stats, summary)
        return summary

    if config.stage == "merge":
        _, _, summary = merge_existing_outputs(config.output_dir, stats=stats)
        log_export_summary(summary)
        merged_rows = read_jsonl_rows(
            config.output_dir / "merged_records.jsonl",
        )
        _maybe_write_validation_report(
            config,
            read_jsonl_rows(literature_records_path(config.output_dir)),
            read_jsonl_rows(web_records_path(config.output_dir)),
            merged_rows,
            stats,
            summary,
        )
        return summary

    if not literature_rows and not config.skip_literature:
        literature_rows = read_jsonl_rows(literature_records_path(config.output_dir))
    if not web_rows and not config.skip_web:
        web_rows = read_jsonl_rows(web_records_path(config.output_dir))

    _, _, _, _, summary = export_pipeline_outputs(
        literature_rows=literature_rows,
        web_rows=web_rows,
        output_dir=config.output_dir,
        stats=stats,
    )
    log_export_summary(summary)

    merged_rows = read_jsonl_rows(config.output_dir / "merged_records.jsonl")
    _maybe_write_validation_report(config, literature_rows, web_rows, merged_rows, stats, summary)
    logger.info("[%s] Pipeline complete", config.mode_label)
    return summary


def _maybe_write_validation_report(
    config: CarbonCaptureRunConfig,
    literature_rows: list[CarbonCaptureRow],
    web_rows: list[CarbonCaptureRow],
    merged_rows: list[CarbonCaptureRow],
    stats: ValidationStats,
    summary: PipelineExportSummary,
) -> None:
    if not config.test_mode:
        return
    report = build_validation_report(
        mode="TEST" if config.test_mode else "FULL",
        slugs=config.slugs,
        output_dir=config.output_dir,
        start=config.start,
        end=config.end,
        paper_limit=config.effective_paper_limit(),
        web_limit=config.effective_web_limit(),
        literature_rows=literature_rows,
        web_rows=web_rows,
        merged_rows=merged_rows,
        stats=stats,
        summary=summary,
    )
    report_path = write_validation_report(config.output_dir / VALIDATION_REPORT_FILENAME, report)
    logger.info("[%s] Validation report -> %s", config.mode_label, report_path)


def slugs_from_args(
    *,
    subcategory: str = "",
    methodology: str = "",
    run_all: bool = False,
) -> list[str]:
    if run_all:
        return list_methodology_slugs()
    if subcategory:
        from pipeline.carbon_capture_config import resolve_methodology_slug

        return [resolve_methodology_slug(subcategory)]
    if methodology:
        return [get_methodology(methodology).slug]
    return list_methodology_slugs()
