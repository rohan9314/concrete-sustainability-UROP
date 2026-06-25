"""26-question extraction for carbon capture methodology results."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.carbon_capture_config import CarbonCaptureMethodology
from pipeline.carbon_capture_prompts import SYSTEM_PROMPT, build_extraction_prompt
from pipeline.concurrency import run_parallel_ordered
from pipeline.config import get_extraction_concurrency
from pipeline.llm_utils import DEFAULT_MODEL, InvalidJSONError, _parse_json_response
from pipeline.openai_client import call_openai
from pipeline.schema import NOT_REPORTED, RankedPaper

logger = logging.getLogger(__name__)

QUESTION_SET_PATH = (
    Path(__file__).resolve().parents[1] / "backend" / "questions" / "carbon_capture.json"
)
QUESTION_BATCH_SIZE = 13


@dataclass
class QuestionAnswerRow:
    question_id: str
    question: str
    answer: str
    confidence: str
    source_type_used: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)


@dataclass
class CarbonCaptureExtraction:
    result_id: str
    methodology_slug: str
    methodology_display: str
    category: str
    subcategory: str
    paper_id: str
    paper_title: str
    paper_year: str
    paper_doi: str
    paper_url: str
    rank_score: float
    technology_name: str
    solution_or_technology_type: str
    company_or_organization: str
    project_name: str
    deployment_stage: str
    co2_reduction: str
    cost_impact: str
    energy_impact: str
    confidence: str
    notes: str
    answers: list[QuestionAnswerRow] = field(default_factory=list)
    extraction_error: str = ""


def load_evaluation_questions() -> list[str]:
    data = json.loads(QUESTION_SET_PATH.read_text(encoding="utf-8"))
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"Invalid question set at {QUESTION_SET_PATH}")
    return [str(question).strip() for question in questions]


def question_ids(count: int = 26) -> list[str]:
    return [f"Q{index:02d}" for index in range(1, count + 1)]


def ranked_paper_to_source(paper: RankedPaper) -> dict:
    url = paper.url
    if not url and paper.doi:
        url = f"https://doi.org/{paper.doi}"
    body = paper.text or paper.abstract or paper.snippet
    return {
        "source_type": "scientific_paper",
        "title": paper.title,
        "url": url,
        "snippet": paper.snippet or paper.abstract[:500],
        "full_text": body,
        "metadata": {
            "authors": paper.authors,
            "year": paper.year,
            "journal": "",
            "doi": paper.doi,
        },
        "paper_id": paper.paper_id,
    }


def format_sources_for_llm(sources: list[dict]) -> str:
    sections: list[str] = []
    for index, source in enumerate(sources, start=1):
        metadata = source.get("metadata") or {}
        body = source.get("full_text") or source.get("snippet") or "No content available."
        meta_lines: list[str] = []
        authors = metadata.get("authors") or []
        if authors:
            meta_lines.append(f"Authors: {', '.join(authors)}")
        if metadata.get("year"):
            meta_lines.append(f"Year: {metadata['year']}")
        if metadata.get("journal"):
            meta_lines.append(f"Journal: {metadata['journal']}")
        if metadata.get("doi"):
            meta_lines.append(f"DOI: {metadata['doi']}")
        if source.get("paper_id"):
            meta_lines.append(f"Paper ID: {source['paper_id']}")

        metadata_block = "\n".join(meta_lines)
        if metadata_block:
            metadata_block = f"{metadata_block}\n"

        sections.append(
            f"--- SCIENTIFIC PAPER SOURCE {index} ---\n"
            f"Title: {source.get('title', '')}\n"
            f"URL: {source.get('url', '')}\n"
            f"Source Type: scientific_paper\n"
            f"{metadata_block}"
            f"Content:\n{body}\n",
        )
    return "\n".join(sections) if sections else "No sources available."


def _normalize_source(raw: dict | None) -> dict:
    source = raw if isinstance(raw, dict) else {}
    return {
        "title": str(source.get("title") or ""),
        "url": str(source.get("url") or ""),
        "source_type": "scientific_paper",
        "snippet": str(source.get("snippet") or ""),
        "full_text": str(source.get("full_text") or ""),
        "metadata": source.get("metadata") if isinstance(source.get("metadata"), dict) else {},
        "paper_id": str(source.get("paper_id") or ""),
    }


def _normalize_answer(raw: dict | None, fallback_question: str) -> QuestionAnswerRow:
    answer = raw if isinstance(raw, dict) else {}
    sources_raw = answer.get("sources")
    if not isinstance(sources_raw, list):
        sources_raw = []
    source_type_used = answer.get("source_type_used")
    if not isinstance(source_type_used, list):
        source_type_used = []

    return QuestionAnswerRow(
        question_id="",
        question=str(answer.get("question") or fallback_question),
        answer=str(answer.get("answer") or "").strip() or "Not Found",
        confidence=str(answer.get("confidence") or "").strip() or "Low",
        source_type_used=[str(item) for item in source_type_used if str(item).strip()],
        sources=[_normalize_source(item) for item in sources_raw],
    )


def _normalize_answers(
    data: dict,
    questions: list[str],
    ids: list[str],
) -> list[QuestionAnswerRow]:
    raw_answers = data.get("answers") or []
    if not isinstance(raw_answers, list):
        raw_answers = []

    by_question: dict[str, dict] = {}
    unmatched: list[dict] = []
    for item in raw_answers:
        if not isinstance(item, dict):
            continue
        question_text = str(item.get("question") or "").strip()
        if question_text and question_text not in by_question:
            by_question[question_text] = item
        else:
            unmatched.append(item)

    normalized: list[QuestionAnswerRow] = []
    used_unmatched = 0
    for question_id, expected_question in zip(ids, questions, strict=True):
        if expected_question in by_question:
            row = _normalize_answer(by_question[expected_question], expected_question)
        elif used_unmatched < len(unmatched):
            row = _normalize_answer(unmatched[used_unmatched], expected_question)
            used_unmatched += 1
        else:
            row = _normalize_answer(
                {
                    "question": expected_question,
                    "answer": "Not Found",
                    "confidence": "Low",
                    "source_type_used": [],
                    "sources": [],
                },
                expected_question,
            )
        row.question_id = question_id
        normalized.append(row)
    return normalized


def _extract_question_batch(
    *,
    methodology: CarbonCaptureMethodology,
    source: dict,
    questions: list[str],
    question_ids_batch: list[str],
    technology_name: str,
    model: str,
) -> list[QuestionAnswerRow]:
    prompt = build_extraction_prompt(
        technology_name=technology_name,
        methodology_name=methodology.display_name,
        methodology_subcategory=methodology.subcategory,
        source_content=format_sources_for_llm([source]),
        questions=questions,
    )
    raw = call_openai(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    data = _parse_json_response(raw)
    return _normalize_answers(data, questions, question_ids_batch)


def _answer_by_id(answers: list[QuestionAnswerRow], question_id: str) -> str:
    for row in answers:
        if row.question_id == question_id:
            return row.answer
    return NOT_REPORTED


def _combine_text(*values: str) -> str:
    parts = [value.strip() for value in values if value and value.strip() not in {"", NOT_REPORTED, "Not Found"}]
    return " | ".join(parts) if parts else NOT_REPORTED


def _infer_project_name(answers: list[QuestionAnswerRow]) -> str:
    text = _answer_by_id(answers, "Q23")
    if text in {NOT_REPORTED, "Not Found"}:
        return NOT_REPORTED
    match = re.search(r"(?:project|pilot|demonstration|plant|facility)\s+[A-Z][\w\s\-]{2,60}", text)
    return match.group(0).strip() if match else NOT_REPORTED


def _build_result(
    *,
    methodology: CarbonCaptureMethodology,
    paper: RankedPaper,
    answers: list[QuestionAnswerRow],
) -> CarbonCaptureExtraction:
    technology_name = _answer_by_id(answers, "Q01")
    if technology_name in {NOT_REPORTED, "Not Found"}:
        technology_name = paper.title[:120] or methodology.display_name

    overall_confidence = _answer_by_id(answers, "Q25")
    if overall_confidence in {NOT_REPORTED, "Not Found"}:
        overall_confidence = "Low"

    return CarbonCaptureExtraction(
        result_id=f"{methodology.slug}:{paper.paper_id}",
        methodology_slug=methodology.slug,
        methodology_display=methodology.display_name,
        category=methodology.category,
        subcategory=methodology.subcategory,
        paper_id=paper.paper_id,
        paper_title=paper.title,
        paper_year=paper.year,
        paper_doi=paper.doi,
        paper_url=paper.url,
        rank_score=paper.rank_score,
        technology_name=technology_name,
        solution_or_technology_type=_answer_by_id(answers, "Q06"),
        company_or_organization=_answer_by_id(answers, "Q03"),
        project_name=_infer_project_name(answers),
        deployment_stage=_answer_by_id(answers, "Q04"),
        co2_reduction=_combine_text(_answer_by_id(answers, "Q07"), _answer_by_id(answers, "Q09")),
        cost_impact=_combine_text(
            _answer_by_id(answers, "Q16"),
            _answer_by_id(answers, "Q17"),
            _answer_by_id(answers, "Q18"),
        ),
        energy_impact=_combine_text(
            _answer_by_id(answers, "Q13"),
            _answer_by_id(answers, "Q14"),
            _answer_by_id(answers, "Q15"),
        ),
        confidence=overall_confidence,
        notes=_answer_by_id(answers, "Q26"),
        answers=answers,
    )


def extract_methodology_paper(
    paper: RankedPaper,
    methodology: CarbonCaptureMethodology,
    *,
    questions: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> CarbonCaptureExtraction:
    """Run 26-question extraction for one ranked paper and methodology."""
    all_questions = questions or load_evaluation_questions()
    ids = question_ids(len(all_questions))
    source = ranked_paper_to_source(paper)
    technology_name = f"{methodology.display_name} — {paper.title[:80]}"

    batches = [
        (
            all_questions[start : start + QUESTION_BATCH_SIZE],
            ids[start : start + QUESTION_BATCH_SIZE],
        )
        for start in range(0, len(all_questions), QUESTION_BATCH_SIZE)
    ]

    merged_answers: list[QuestionAnswerRow] = []
    try:
        for batch_questions, batch_ids in batches:
            merged_answers.extend(
                _extract_question_batch(
                    methodology=methodology,
                    source=source,
                    questions=batch_questions,
                    question_ids_batch=batch_ids,
                    technology_name=technology_name,
                    model=model,
                ),
            )
    except (InvalidJSONError, Exception) as exc:
        message = str(exc) or exc.__class__.__name__
        logger.warning(
            "Extraction failed for %s (%s): %s",
            paper.paper_id,
            methodology.slug,
            message,
        )
        return CarbonCaptureExtraction(
            result_id=f"{methodology.slug}:{paper.paper_id}",
            methodology_slug=methodology.slug,
            methodology_display=methodology.display_name,
            category=methodology.category,
            subcategory=methodology.subcategory,
            paper_id=paper.paper_id,
            paper_title=paper.title,
            paper_year=paper.year,
            paper_doi=paper.doi,
            paper_url=paper.url,
            rank_score=paper.rank_score,
            technology_name=paper.title[:120] or methodology.display_name,
            solution_or_technology_type=NOT_REPORTED,
            company_or_organization=NOT_REPORTED,
            project_name=NOT_REPORTED,
            deployment_stage=NOT_REPORTED,
            co2_reduction=NOT_REPORTED,
            cost_impact=NOT_REPORTED,
            energy_impact=NOT_REPORTED,
            confidence="Low",
            notes=NOT_REPORTED,
            extraction_error=message,
        )

    return _build_result(methodology=methodology, paper=paper, answers=merged_answers)


def extract_methodology_papers_parallel(
    papers: list[RankedPaper],
    methodology: CarbonCaptureMethodology,
    *,
    model: str = DEFAULT_MODEL,
    concurrency: int | None = None,
) -> list[CarbonCaptureExtraction]:
    """Extract 26-question results for all ranked papers in parallel."""
    limit = concurrency or get_extraction_concurrency()

    def worker(paper: RankedPaper) -> CarbonCaptureExtraction:
        return extract_methodology_paper(paper, methodology, model=model)

    parallel = run_parallel_ordered(papers, worker, concurrency=limit, label=methodology.slug)
    results: list[CarbonCaptureExtraction] = []
    for item in parallel:
        if item.success and item.value is not None:
            results.append(item.value)
        elif item.item is not None:
            paper = item.item
            results.append(
                CarbonCaptureExtraction(
                    result_id=f"{methodology.slug}:{paper.paper_id}",
                    methodology_slug=methodology.slug,
                    methodology_display=methodology.display_name,
                    category=methodology.category,
                    subcategory=methodology.subcategory,
                    paper_id=paper.paper_id,
                    paper_title=paper.title,
                    paper_year=paper.year,
                    paper_doi=paper.doi,
                    paper_url=paper.url,
                    rank_score=paper.rank_score,
                    technology_name=paper.title[:120] or methodology.display_name,
                    solution_or_technology_type=NOT_REPORTED,
                    company_or_organization=NOT_REPORTED,
                    project_name=NOT_REPORTED,
                    deployment_stage=NOT_REPORTED,
                    co2_reduction=NOT_REPORTED,
                    cost_impact=NOT_REPORTED,
                    energy_impact=NOT_REPORTED,
                    confidence="Low",
                    notes=NOT_REPORTED,
                    extraction_error=item.error or "Extraction worker failed",
                ),
            )
    return results
