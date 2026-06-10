"""Normalize research results to the frontend API contract."""

from schema import (
    QuestionAnswer,
    RetrievalSummary,
    Source,
    SourceMetadata,
    TechnologyEvaluation,
)


def _normalize_metadata(raw: dict | None) -> dict:
    metadata = raw if isinstance(raw, dict) else {}
    authors = metadata.get("authors")
    if isinstance(authors, str):
        cleaned = authors.strip()
        authors = [] if not cleaned or cleaned == "Not Found" else [cleaned]
    elif not isinstance(authors, list):
        authors = []
    return {
        "authors": [str(a) for a in authors if str(a).strip()],
        "year": str(metadata.get("year") or "").strip(),
        "journal": str(metadata.get("journal") or "").strip(),
        "doi": str(metadata.get("doi") or "").strip(),
    }


def _normalize_source(raw: dict | None) -> dict:
    source = raw if isinstance(raw, dict) else {}
    raw_type = str(source.get("source_type") or "").strip().lower()
    if raw_type == "internet":
        source_type = "internet"
    else:
        source_type = "scientific_paper"
    return {
        "title": str(source.get("title") or ""),
        "url": str(source.get("url") or ""),
        "source_type": source_type,
        "snippet": str(source.get("snippet") or ""),
        "full_text": str(source.get("full_text") or ""),
        "metadata": _normalize_metadata(source.get("metadata")),
    }


def _normalize_answer(raw: dict | None, fallback_question: str = "") -> dict:
    answer = raw if isinstance(raw, dict) else {}
    source_type_used = answer.get("source_type_used")
    if not isinstance(source_type_used, list):
        source_type_used = []

    sources_raw = answer.get("sources")
    if not isinstance(sources_raw, list):
        sources_raw = []

    text = str(answer.get("answer") or "").strip() or "Not Found"
    confidence = str(answer.get("confidence") or "").strip() or "Low"

    return {
        "question": str(answer.get("question") or fallback_question),
        "answer": text,
        "confidence": confidence,
        "source_type_used": [str(item) for item in source_type_used if str(item).strip()],
        "sources": [_normalize_source(item) for item in sources_raw],
    }


def _normalize_retrieval_summary(raw: dict | RetrievalSummary | None) -> dict:
    if isinstance(raw, RetrievalSummary):
        raw = raw.model_dump()
    summary = raw if isinstance(raw, dict) else {}
    return {
        "internet_sources_found": int(summary.get("internet_sources_found") or 0),
        "scientific_paper_sources_found": int(
            summary.get("scientific_paper_sources_found") or 0
        ),
        "local_paper_database_enabled": bool(
            summary.get("local_paper_database_enabled")
        ),
    }


def normalize_result(
    evaluation: TechnologyEvaluation | dict,
    *,
    executive_summary: str = "",
) -> dict:
    """Return a frontend-safe result dict with all required fields present."""
    if isinstance(evaluation, TechnologyEvaluation):
        data = evaluation.model_dump()
    else:
        data = evaluation if isinstance(evaluation, dict) else {}

    answers_raw = data.get("answers")
    if not isinstance(answers_raw, list):
        answers_raw = []

    return {
        "technology": str(data.get("technology") or ""),
        "questions_file": str(data.get("questions_file") or ""),
        "executive_summary": str(
            executive_summary or data.get("executive_summary") or ""
        ),
        "answers": [_normalize_answer(item) for item in answers_raw],
        "retrieval_summary": _normalize_retrieval_summary(data.get("retrieval_summary")),
    }


def normalize_answers_from_questions(
    questions: list[str],
    answers: list[dict] | list[QuestionAnswer],
) -> list[dict]:
    """Ensure one normalized answer per configured question."""
    if answers and isinstance(answers[0], QuestionAnswer):
        answers = [item.model_dump() for item in answers]

    by_question: dict[str, dict] = {}
    unmatched: list[dict] = []
    for item in answers:
        if not isinstance(item, dict):
            continue
        question_text = str(item.get("question") or "").strip()
        if question_text and question_text not in by_question:
            by_question[question_text] = item
        else:
            unmatched.append(item)

    normalized: list[dict] = []
    used_unmatched = 0
    for question in questions:
        if question in by_question:
            normalized.append(_normalize_answer(by_question[question], question))
            continue
        if used_unmatched < len(unmatched):
            normalized.append(_normalize_answer(unmatched[used_unmatched], question))
            used_unmatched += 1
            continue
        normalized.append(
            _normalize_answer(
                {
                    "question": question,
                    "answer": "Not Found",
                    "confidence": "Low",
                    "source_type_used": [],
                    "sources": [],
                },
                question,
            )
        )
    return normalized
