"""Research pipeline callable from the CLI and API."""

from typing import Callable

from edison import is_edison_configured, retrieve_edison_papers
from executive_summary import generate_executive_summary
from llm import (
    InvalidJSONError,
    MissingAPIKeyError,
    SchemaValidationError,
    extract_technology_info,
    validate_api_key as validate_openai_key,
)
from questions import (
    InvalidQuestionSetError,
    QuestionSetNotFoundError,
    load_questions,
    question_set_name,
)
from schema import RetrievalSummary
from search import (
    MissingAPIKeyError as TavilyMissingKeyError,
    NoSearchResultsError,
    retrieve_internet_sources,
    validate_api_key as validate_tavily_key,
)
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

    Preserves the existing internet search workflow and optionally adds Edison papers.
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
        validate_tavily_key()
        validate_openai_key()
    except (TavilyMissingKeyError, MissingAPIKeyError) as exc:
        raise ResearchPipelineError("CONFIGURATION_ERROR", str(exc)) from exc

    _report_progress(
        progress_callback,
        "preparing_question_set",
        f"Preparing question set: {set_name} ({len(questions)} questions)",
    )

    _report_progress(
        progress_callback,
        "searching_internet",
        "Searching internet sources...",
    )
    try:
        internet_sources = retrieve_internet_sources(technology_name)
    except NoSearchResultsError as exc:
        raise ResearchPipelineError("NO_SEARCH_RESULTS", str(exc)) from exc
    except TavilyMissingKeyError as exc:
        raise ResearchPipelineError("CONFIGURATION_ERROR", str(exc)) from exc

    edison_enabled = is_edison_configured()
    if edison_enabled:
        _report_progress(
            progress_callback,
            "searching_scientific_literature",
            "Searching scientific literature (Edison API)...",
        )
        paper_sources = retrieve_edison_papers(technology_name)
    else:
        _report_progress(
            progress_callback,
            "searching_scientific_literature",
            "Edison API key not configured. Continuing with internet sources only.",
        )
        paper_sources = []

    all_sources = internet_sources + paper_sources
    retrieval_summary = RetrievalSummary(
        internet_sources_found=len(internet_sources),
        scientific_paper_sources_found=len(paper_sources),
        edison_enabled=edison_enabled,
    )

    _report_progress(
        progress_callback,
        "analyzing_evidence",
        "Extracting structured answers with OpenAI...",
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
