"""Research pipeline callable from the CLI and API."""

from typing import Callable

from executive_summary import generate_executive_summary
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
)
from questions import (
    InvalidQuestionSetError,
    QuestionSetNotFoundError,
    load_questions,
    question_set_name,
)
from retrieval import retrieve_all_sources
from schema import RetrievalSummary
from serializer import normalize_result

ProgressCallback = Callable[[str, str], None]


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


def run_research_pipeline(
    subject: str,
    question_set: str,
    *,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """
    Run the full research workflow and return a normalized result dict.

    Academic papers are retrieved from the local pickle database and internet
    sources are retrieved via Tavily. Both streams use multiple targeted queries.
    """
    technology_name = subject.strip()
    if not technology_name:
        raise ResearchPipelineError("INVALID_SUBJECT", "Subject cannot be empty.")

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
        f"Preparing question set: {set_name} ({len(questions)} questions)",
    )

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
        paper_sources, internet_sources = retrieve_all_sources(
            technology_name,
            progress_callback=progress_callback,
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
            f"Extracting answers from {len(paper_sources)} papers and "
            f"{len(internet_sources)} internet sources (batched)..."
        ),
    )
    try:
        evaluation = extract_technology_info(
            technology_name,
            all_sources,
            questions=questions,
            questions_file=set_name,
            retrieval_summary=retrieval_summary,
        )
    except (InvalidJSONError, SchemaValidationError, MissingAPIKeyError) as exc:
        raise ResearchPipelineError("EXTRACTION_ERROR", str(exc)) from exc

    _report_progress(
        progress_callback,
        "generating_report",
        "Generating executive summary...",
    )
    executive_summary = generate_executive_summary(evaluation)
    evaluation.executive_summary = executive_summary

    return normalize_result(evaluation, executive_summary=executive_summary)
