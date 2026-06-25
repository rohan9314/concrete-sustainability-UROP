"""Export carbon capture extraction results to answers and citations CSV files."""

from __future__ import annotations

import csv
from pathlib import Path

from pipeline.carbon_capture_config import CarbonCaptureMethodology
from pipeline.carbon_capture_extraction import CarbonCaptureExtraction, question_ids


def _answers_fieldnames() -> list[str]:
    base = [
        "result_id",
        "category",
        "subcategory",
        "methodology",
        "technology_name",
        "solution_or_technology_type",
        "company_or_organization",
        "project_name",
        "deployment_stage",
    ]
    base.extend(question_ids())
    base.extend(
        [
            "co2_reduction",
            "cost_impact",
            "energy_impact",
            "confidence",
            "notes",
            "paper_id",
            "paper_title",
            "paper_year",
            "paper_doi",
            "paper_url",
            "rank_score",
            "extraction_error",
        ],
    )
    return base


CITATIONS_FIELDNAMES = [
    "citation_id",
    "result_id",
    "methodology",
    "question_id",
    "claim",
    "source_type",
    "source_title",
    "source_url",
    "paper_id",
    "quoted_evidence_or_summary",
    "confidence",
]


def _answers_row(result: CarbonCaptureExtraction) -> dict[str, str | float]:
    row: dict[str, str | float] = {
        "result_id": result.result_id,
        "category": result.category,
        "subcategory": result.subcategory,
        "methodology": result.methodology_display,
        "technology_name": result.technology_name,
        "solution_or_technology_type": result.solution_or_technology_type,
        "company_or_organization": result.company_or_organization,
        "project_name": result.project_name,
        "deployment_stage": result.deployment_stage,
        "co2_reduction": result.co2_reduction,
        "cost_impact": result.cost_impact,
        "energy_impact": result.energy_impact,
        "confidence": result.confidence,
        "notes": result.notes,
        "paper_id": result.paper_id,
        "paper_title": result.paper_title,
        "paper_year": result.paper_year,
        "paper_doi": result.paper_doi,
        "paper_url": result.paper_url,
        "rank_score": result.rank_score,
        "extraction_error": result.extraction_error,
    }
    answer_map = {answer.question_id: answer.answer for answer in result.answers}
    for question_id in question_ids():
        row[question_id] = answer_map.get(question_id, "Not Found")
    return row


def _citation_rows(result: CarbonCaptureExtraction) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for answer in result.answers:
        if answer.answer in {"", "Not Found"}:
            continue
        if not answer.sources:
            rows.append(
                {
                    "citation_id": f"{result.result_id}:{answer.question_id}:0",
                    "result_id": result.result_id,
                    "methodology": result.methodology_display,
                    "question_id": answer.question_id,
                    "claim": answer.answer,
                    "source_type": "scientific_paper",
                    "source_title": result.paper_title,
                    "source_url": result.paper_url,
                    "paper_id": result.paper_id,
                    "quoted_evidence_or_summary": answer.answer[:500],
                    "confidence": answer.confidence,
                },
            )
            continue

        for index, source in enumerate(answer.sources):
            metadata = source.get("metadata") or {}
            paper_id = str(source.get("paper_id") or metadata.get("paper_id") or result.paper_id)
            evidence = (
                str(source.get("snippet") or "").strip()
                or str(source.get("full_text") or "")[:500]
                or answer.answer[:500]
            )
            rows.append(
                {
                    "citation_id": f"{result.result_id}:{answer.question_id}:{index}",
                    "result_id": result.result_id,
                    "methodology": result.methodology_display,
                    "question_id": answer.question_id,
                    "claim": answer.answer,
                    "source_type": str(source.get("source_type") or "scientific_paper"),
                    "source_title": str(source.get("title") or result.paper_title),
                    "source_url": str(source.get("url") or result.paper_url),
                    "paper_id": paper_id,
                    "quoted_evidence_or_summary": evidence,
                    "confidence": answer.confidence,
                },
            )
    return rows


def write_methodology_csvs(
    results: list[CarbonCaptureExtraction],
    methodology: CarbonCaptureMethodology,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write answers and citations CSV files for one methodology."""
    output_dir.mkdir(parents=True, exist_ok=True)
    answers_path = output_dir / methodology.answers_filename
    citations_path = output_dir / methodology.citations_filename

    answers_fields = _answers_fieldnames()
    with answers_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=answers_fields)
        writer.writeheader()
        for result in results:
            writer.writerow(_answers_row(result))

    citation_rows: list[dict[str, str]] = []
    for result in results:
        citation_rows.extend(_citation_rows(result))

    with citations_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CITATIONS_FIELDNAMES)
        writer.writeheader()
        for row in citation_rows:
            writer.writerow(row)

    return answers_path, citations_path
