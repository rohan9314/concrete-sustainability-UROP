"""Tests for carbon capture methodology config and CSV export."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.carbon_capture_config import (
    CARBON_CAPTURE_METHODOLOGIES,
    all_methodologies,
    get_methodology,
    list_methodology_slugs,
)
from pipeline.carbon_capture_export import CITATIONS_FIELDNAMES, write_methodology_csvs
from pipeline.carbon_capture_extraction import (
    CarbonCaptureExtraction,
    QuestionAnswerRow,
    load_evaluation_questions,
    question_ids,
)


def test_six_methodologies_configured() -> None:
    slugs = list_methodology_slugs()
    assert len(slugs) == 6
    assert set(slugs) == set(CARBON_CAPTURE_METHODOLOGIES.keys())


def test_expected_output_filenames() -> None:
    expected = {
        "amine_absorption": ("amine_absorption_answers.csv", "amine_absorption_citations.csv"),
        "membrane_separation": (
            "membrane_separation_answers.csv",
            "membrane_separation_citations.csv",
        ),
        "calcium_looping": ("calcium_looping_answers.csv", "calcium_looping_citations.csv"),
        "oxyfuel_combustion": (
            "oxyfuel_combustion_answers.csv",
            "oxyfuel_combustion_citations.csv",
        ),
        "cryogenic_capture": ("cryogenic_capture_answers.csv", "cryogenic_capture_citations.csv"),
        "mineralization": ("mineralization_answers.csv", "mineralization_citations.csv"),
    }
    for slug, (answers_name, citations_name) in expected.items():
        methodology = get_methodology(slug)
        assert methodology.answers_filename == answers_name
        assert methodology.citations_filename == citations_name
        assert methodology.category == "Carbon Capture"
        assert methodology.subcategory != "Carbon Capture"


def test_twenty_six_questions_loaded() -> None:
    questions = load_evaluation_questions()
    assert len(questions) == 26
    assert question_ids() == [f"Q{index:02d}" for index in range(1, 27)]


def test_csv_export_shape() -> None:
    methodology = get_methodology("amine_absorption")
    answers = [
        QuestionAnswerRow(
            question_id=question_id,
            question=f"Question {question_id}",
            answer="Example answer",
            confidence="Medium",
            source_type_used=["scientific_paper"],
            sources=[
                {
                    "title": "Paper title",
                    "url": "https://example.org/paper",
                    "source_type": "scientific_paper",
                    "snippet": "Evidence snippet",
                    "full_text": "",
                    "metadata": {"authors": ["A. Author"], "year": "2020", "doi": "10.1/example"},
                    "paper_id": "doi:10.1/example",
                },
            ],
        )
        for question_id in question_ids()
    ]
    result = CarbonCaptureExtraction(
        result_id="amine_absorption:doi:10.1/example",
        methodology_slug=methodology.slug,
        methodology_display=methodology.display_name,
        category=methodology.category,
        subcategory=methodology.subcategory,
        paper_id="doi:10.1/example",
        paper_title="Paper title",
        paper_year="2020",
        paper_doi="10.1/example",
        paper_url="https://example.org/paper",
        rank_score=12.5,
        technology_name="Test capture technology",
        solution_or_technology_type="Amine scrubbing",
        company_or_organization="Example Corp",
        project_name="Pilot plant",
        deployment_stage="Pilot",
        co2_reduction="30% CO2 reduction",
        cost_impact="Higher OPEX",
        energy_impact="Increased thermal demand",
        confidence="Medium",
        notes="Limited pilot data",
        answers=answers,
    )

    with tempfile.TemporaryDirectory() as tmp:
        answers_path, citations_path = write_methodology_csvs(
            [result],
            methodology,
            Path(tmp),
        )
        with answers_path.open(encoding="utf-8") as handle:
            answers_rows = list(csv.DictReader(handle))
        with citations_path.open(encoding="utf-8") as handle:
            citation_rows = list(csv.DictReader(handle))

    assert len(answers_rows) == 1
    assert answers_rows[0]["methodology"] == methodology.display_name
    assert answers_rows[0]["Q01"] == "Example answer"
    assert answers_rows[0]["result_id"] == "amine_absorption:doi:10.1/example"
    assert len(citation_rows) == 26
    assert set(citation_rows[0].keys()) == set(CITATIONS_FIELDNAMES)
    assert all(row["methodology"] == methodology.display_name for row in citation_rows)


def test_all_methodologies_have_keywords() -> None:
    for methodology in all_methodologies():
        assert methodology.search_keywords
        assert methodology.synonyms
        assert methodology.retrieval_query
        assert "carbon" in methodology.retrieval_query.lower() or "co2" in methodology.retrieval_query.lower()


def main() -> int:
    tests = [
        test_six_methodologies_configured,
        test_expected_output_filenames,
        test_twenty_six_questions_loaded,
        test_csv_export_shape,
        test_all_methodologies_have_keywords,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"All {len(tests)} carbon capture tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
