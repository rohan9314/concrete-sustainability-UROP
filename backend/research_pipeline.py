"""Research pipeline callable from the CLI and API."""

from __future__ import annotations

import logging
from typing import Callable

from concurrency import get_extraction_concurrency
from executive_summary import generate_intelligence_executive_summary
from intelligence_llm import extract_technology_intelligence
from source_registry import build_registry_from_sources
from llm import (
    InvalidJSONError,
    MissingAPIKeyError,
    SchemaValidationError,
    extract_technology_info,
    validate_api_key as validate_openai_key,
)
from paper_records import (
    PaperDatabaseConfigError,
    PaperDatabaseLoadError,
    PaperDatabaseNotFoundError,
    is_paper_database_available,
    load_paper_records,
)
from questions import (
    InvalidQuestionSetError,
    QuestionSetNotFoundError,
    load_questions,
    question_set_name,
)
from retrieval import retrieve_all_sources
from schema import RetrievalSummary
from schemas.technology_intelligence import ResearchFilters, TechnologyIntelligence
from serializer import normalize_result
from timing import PipelineTimer

ProgressCallback = Callable[[str, str], None]

logger = logging.getLogger(__name__)


class ResearchPipelineError(Exception):
    """Raised when the research pipeline fails."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _report_progress(
    callback: ProgressCallback | None,
    step: str,
    message: str,
) -> None:
    if callback:
        callback(step, message)


def _intelligence_is_sparse(intelligence: TechnologyIntelligence) -> bool:
    return not (
        intelligence.evidence_sources
        or intelligence.metrics
        or intelligence.companies
        or intelligence.pilot_demonstration_projects
    )


def run_research_pipeline(
    subject: str,
    question_set: str,
    *,
    filters: ResearchFilters | dict | None = None,
    include_legacy_qa: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """
    Run the full research workflow and return a normalized result dict.

    Primary output is structured technology intelligence. Legacy 26-question
    answers are optional and returned under legacy_answers when requested.

    The live website uses bounded parallel retrieval plus one consolidated LLM pass
    for responsiveness. Per-source workers run through scripts/process_batch.py for
    large-scale corpus slices.
    """
    timer = PipelineTimer(label="research")
    technology_name = subject.strip()
    if not technology_name:
        raise ResearchPipelineError("INVALID_SUBJECT", "Subject cannot be empty.")

    filter_model = (
        filters
        if isinstance(filters, ResearchFilters)
        else ResearchFilters.model_validate(filters or {})
    )

    with timer.stage("question_set"):
        try:
            questions = load_questions(question_set)
            set_name = question_set_name(question_set)
        except QuestionSetNotFoundError as exc:
            raise ResearchPipelineError("QUESTION_SET_NOT_FOUND", str(exc)) from exc
        except InvalidQuestionSetError as exc:
            raise ResearchPipelineError("INVALID_QUESTION_SET", str(exc)) from exc

        try:
            validate_openai_key()
        except MissingAPIKeyError as exc:
            raise ResearchPipelineError("CONFIGURATION_ERROR", str(exc)) from exc

    _report_progress(
        progress_callback,
        "preparing_question_set",
        f"Preparing structured extraction for: {technology_name}",
    )

    with timer.stage("pickle_load"):
        try:
            local_db_available = is_paper_database_available()
        except PaperDatabaseConfigError as exc:
            raise ResearchPipelineError("PAPER_DATABASE_NOT_CONFIGURED", str(exc)) from exc

        if not local_db_available:
            raise ResearchPipelineError(
                "PAPER_DATABASE_NOT_FOUND",
                "Local paper database not found. Set PAPER_RECORDS_PATH in backend/.env "
                "to the absolute path of your confidential paper database file.",
            )

        try:
            paper_records = load_paper_records()
        except PaperDatabaseNotFoundError as exc:
            raise ResearchPipelineError("PAPER_DATABASE_NOT_FOUND", str(exc)) from exc
        except PaperDatabaseLoadError as exc:
            raise ResearchPipelineError("PAPER_DATABASE_LOAD_ERROR", str(exc)) from exc

    with timer.stage("source_retrieval"):
        try:
            paper_sources, internet_sources = retrieve_all_sources(
                technology_name,
                company_name=filter_model.company_name,
                ccs_subcategory=filter_model.ccs_subcategory,
                project_stage=filter_model.project_stage,
                progress_callback=progress_callback,
                records=paper_records,
            )
        except PaperDatabaseConfigError as exc:
            raise ResearchPipelineError("PAPER_DATABASE_NOT_CONFIGURED", str(exc)) from exc
        except PaperDatabaseNotFoundError as exc:
            raise ResearchPipelineError("PAPER_DATABASE_NOT_FOUND", str(exc)) from exc
        except PaperDatabaseLoadError as exc:
            raise ResearchPipelineError("PAPER_DATABASE_LOAD_ERROR", str(exc)) from exc

    if not paper_sources and not internet_sources:
        raise ResearchPipelineError(
            "NO_SOURCES_FOUND",
            "No local paper matches or internet sources were found for this subject.",
        )

    all_sources = paper_sources + internet_sources
    retrieval_summary = RetrievalSummary(
        internet_sources_found=len(internet_sources),
        scientific_paper_sources_found=len(paper_sources),
        local_paper_database_enabled=local_db_available,
    )

    _report_progress(
        progress_callback,
        "analyzing_evidence",
        (
            f"Extracting structured intelligence from {len(paper_sources)} papers and "
            f"{len(internet_sources)} internet sources "
            f"(concurrency={get_extraction_concurrency()})..."
        ),
    )

    intelligence: TechnologyIntelligence

    with timer.stage("intelligence_llm"):
        try:
            source_registry = build_registry_from_sources(all_sources)
            intelligence, bibliography = extract_technology_intelligence(
                technology_name,
                all_sources,
                filters=filter_model,
                source_registry=source_registry,
            )
        except (InvalidJSONError, SchemaValidationError, MissingAPIKeyError) as exc:
            raise ResearchPipelineError("EXTRACTION_ERROR", str(exc)) from exc

    if _intelligence_is_sparse(intelligence):
        intelligence.warnings.append(
            "Structured extraction returned sparse results for the retrieved sources."
        )

    legacy_answers: list[dict] = []
    if include_legacy_qa:
        _report_progress(
            progress_callback,
            "analyzing_evidence",
            "Extracting legacy 26-question answers...",
        )
        with timer.stage("legacy_qa"):
            try:
                legacy_eval = extract_technology_info(
                    technology_name,
                    all_sources,
                    questions=questions,
                    questions_file=set_name,
                    retrieval_summary=retrieval_summary,
                )
                legacy_result = normalize_result(legacy_eval)
                legacy_answers = legacy_result.get("answers") or []
            except (InvalidJSONError, SchemaValidationError, MissingAPIKeyError) as exc:
                intelligence.warnings.append(f"Legacy Q&A extraction failed: {exc}")

    _report_progress(
        progress_callback,
        "generating_report",
        "Generating executive summary...",
    )
    with timer.stage("executive_summary"):
        executive_summary = generate_intelligence_executive_summary(
            technology_name,
            intelligence,
        )

    timer.log_total()

    return {
        "technology": intelligence.technology_overview.technology_name or technology_name,
        "questions_file": set_name,
        "executive_summary": executive_summary,
        "intelligence": intelligence.model_dump(),
        "legacy_answers": legacy_answers,
        "retrieval_summary": retrieval_summary.model_dump(),
        "search_filters": filter_model.model_dump(),
        "sources": [source.model_dump() for source in bibliography.sources],
        "sources_used": [source.model_dump() for source in bibliography.sources_used],
        "sources_considered": [
            source.model_dump() for source in bibliography.sources_considered
        ],
        "citation_warnings": bibliography.citation_warnings,
    }
