"""Tests for carbon capture methodology config, schema, merge, and export."""

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
    resolve_methodology_slug,
)
from pipeline.carbon_capture_extraction import CarbonCaptureRow
from pipeline.carbon_capture_export import export_pipeline_outputs
from pipeline.carbon_capture_merge import conservative_merge_rows
from pipeline.carbon_capture_outputs import (
    FINAL_OUTPUT_CSV_FILENAME,
    LITERATURE_CSV_FILENAME,
    LITERATURE_RECORDS_FILENAME,
    MERGED_RECORDS_FILENAME,
    WEB_CSV_FILENAME,
    WEB_RECORDS_FILENAME,
)
from pipeline.carbon_capture_schema import (
    CANONICAL_FIELDS,
    NA,
    ValidationStats,
    expand_record_to_rows,
    normalize_confidence,
    normalize_deployment_stage,
    normalize_missing,
    validate_and_normalize_row,
)
from pipeline.carbon_capture_web import (
    build_company_project_queries,
    build_technology_level_queries,
)


def _sample_literature_row(**overrides) -> CarbonCaptureRow:
    base = dict(
        record_id="amine_absorption:paper1:0",
        result_id="amine_absorption:paper1",
        methodology_slug="amine_absorption",
        methodology_display="Solvent-based / amine absorption",
        source_origin="literature",
        category="Carbon Capture",
        subcategory="Solvent-based / amine absorption",
        technology_type="amine absorption",
        company_or_organization="Example Corp",
        project_name="Brevik CCS",
        project_year=NA,
        project_location=NA,
        deployment_stage=NA,
        metric_dimension="CO2 Reduction",
        metric_name="CO2 capture rate",
        metric_value="85",
        metric_unit="%",
        metric_boundary="capture unit",
        co2_reduction="85%",
        energy_impact=NA,
        cost_impact=NA,
        primary_barriers=NA,
        source_type="Literature",
        source_title="Paper title",
        source_url_or_citation="https://example.org/paper",
        confidence="Medium",
        notes=NA,
    )
    base.update(overrides)
    return CarbonCaptureRow(**base)


def test_six_methodologies_configured() -> None:
    slugs = list_methodology_slugs()
    assert len(slugs) == 6
    assert set(slugs) == set(CARBON_CAPTURE_METHODOLOGIES.keys())


def test_global_output_filenames() -> None:
    assert LITERATURE_RECORDS_FILENAME == "literature_records.jsonl"
    assert LITERATURE_CSV_FILENAME == "literature_records.csv"
    assert WEB_RECORDS_FILENAME == "web_records.jsonl"
    assert WEB_CSV_FILENAME == "web_records.csv"
    assert MERGED_RECORDS_FILENAME == "merged_records.jsonl"
    assert FINAL_OUTPUT_CSV_FILENAME == "final_output.csv"


def test_metric_expansion_preserves_project_identity() -> None:
    rows = expand_record_to_rows(
        {
            "technology_type": "oxyfuel combustion",
            "company_or_organization": "Heidelberg Materials",
            "project_name": "Brevik CCS",
            "project_year": "2024",
            "deployment_stage": "Demonstration",
            "metrics": [
                {
                    "metric_dimension": "Energy",
                    "metric_name": "energy penalty",
                    "metric_value": "3.5",
                    "metric_unit": "GJ/tCO2",
                    "metric_boundary": "cement plant",
                },
                {
                    "metric_dimension": "CO2 Reduction",
                    "metric_name": "CO2 capture rate",
                    "metric_value": "90",
                    "metric_unit": "%",
                    "metric_boundary": "capture unit",
                },
            ],
        },
    )
    assert len(rows) == 2
    assert all(row["project_name"] == "Brevik CCS" for row in rows)
    assert all(row["technology_type"] == "oxyfuel combustion" for row in rows)
    assert rows[0]["energy_impact"] == "3.5 GJ/tCO2"
    assert rows[1]["co2_reduction"] == "90 %"


def test_missing_values_normalize_to_na() -> None:
    for value in ["Not Found", "Not Reported", "Unknown", "", None, "unavailable"]:
        assert normalize_missing(value) == NA


def test_controlled_vocab_normalization() -> None:
    stats = ValidationStats()
    assert normalize_confidence("The confidence is high because...", stats) == "High"
    assert normalize_deployment_stage("pilot-scale testing", stats) == "Pilot"
    assert normalize_deployment_stage("lab-scale study", stats) == "Laboratory"
    assert normalize_deployment_stage("commercially deployed", stats) == "Commercial"
    assert normalize_deployment_stage("expected to be commercial by 2030", stats) == NA


def test_web_query_templates() -> None:
    methodology = get_methodology("amine_absorption")
    tech_queries = build_technology_level_queries(methodology.subcategory)
    assert any("pilot project" in query for query in tech_queries)
    followups = build_company_project_queries(
        company="Heidelberg",
        technology_type="amine absorption",
        project_name="Brevik CCS",
    )
    assert any("Heidelberg" in query and "Brevik CCS" in query for query in followups)


def test_metric_expansion_creates_separate_rows() -> None:
    rows = expand_record_to_rows(
        {
            "technology_type": "amine absorption",
            "project_name": "Pilot A",
            "metrics": [
                {
                    "metric_dimension": "CO2 Reduction",
                    "metric_name": "CO2 capture rate",
                    "metric_value": "90",
                    "metric_unit": "%",
                    "metric_boundary": "capture unit",
                },
                {
                    "metric_dimension": "Energy",
                    "metric_name": "energy penalty",
                    "metric_value": "3.5",
                    "metric_unit": "GJ/tCO2",
                    "metric_boundary": "capture unit",
                },
            ],
        },
    )
    assert len(rows) == 2


def test_conservative_merge_fills_na_without_overwriting() -> None:
    literature = _sample_literature_row()
    web = _sample_literature_row(
        record_id="amine_absorption:web1:0",
        result_id="amine_absorption:web1",
        source_origin="web",
        source_type="Web",
        project_year="2024",
        deployment_stage="Demonstration",
        source_title="Web page",
        source_url_or_citation="https://example.org/web",
        metric_name="energy penalty",
        metric_value="3.5",
        metric_unit="GJ/tCO2",
        metric_dimension="Energy",
        co2_reduction=NA,
    )
    merged, stats = conservative_merge_rows([literature], [web])
    assert len(merged) == 2
    assert stats.complementary_fields_filled >= 1
    lit = next(row for row in merged if row.source_origin == "literature")
    assert lit.project_year == "2024"
    assert lit.deployment_stage == "Demonstration"
    assert lit.co2_reduction == "85%"


def test_global_pipeline_export_shape() -> None:
    methodology = get_methodology("amine_absorption")
    literature_row = _sample_literature_row()
    web_row = _sample_literature_row(
        record_id="amine_absorption:web1:0",
        result_id="amine_absorption:web1",
        source_origin="web",
        source_type="Web",
        source_title="Company page",
        source_url_or_citation="https://example.org/web",
        confidence="Low",
        project_name=NA,
        metric_dimension=NA,
        metric_name=NA,
        metric_value=NA,
        metric_unit=NA,
        co2_reduction=NA,
    )

    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)
        _, _, merged_path, csv_path, summary = export_pipeline_outputs(
            literature_rows=[literature_row],
            web_rows=[web_row],
            output_dir=output_dir,
        )
        with csv_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        assert merged_path.name == MERGED_RECORDS_FILENAME
        assert csv_path.name == FINAL_OUTPUT_CSV_FILENAME
        assert (output_dir / LITERATURE_RECORDS_FILENAME).is_file()
        assert (output_dir / LITERATURE_CSV_FILENAME).is_file()
        assert (output_dir / WEB_RECORDS_FILENAME).is_file()
        assert (output_dir / WEB_CSV_FILENAME).is_file()
        assert list(rows[0].keys()) == list(CANONICAL_FIELDS)
        assert summary.literature_records == 1
        assert summary.web_records == 1
        assert summary.final_csv_rows == len(rows)


def test_validate_row_fills_missing_fields() -> None:
    row = validate_and_normalize_row({"technology_type": "calcium looping"})
    assert set(row.keys()) == set(CANONICAL_FIELDS)
    assert row["technology_type"] == "calcium looping"
    assert row["project_name"] == NA


def test_resolve_subcategory_slug() -> None:
    assert resolve_methodology_slug("oxyfuel combustion") == "oxyfuel_combustion"
    assert resolve_methodology_slug("oxyfuel_combustion") == "oxyfuel_combustion"
    assert resolve_methodology_slug("Oxyfuel combustion") == "oxyfuel_combustion"


def test_test_mode_default_output_dir() -> None:
    from pipeline.carbon_capture_runner import resolve_output_dir

    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["OUTPUT_DIR"] = tmp
        path = resolve_output_dir(raw="", test_mode=True)
        assert path.name == "test_run"


def test_run_config_effective_limits() -> None:
    from pipeline.carbon_capture_runner import CarbonCaptureRunConfig

    config = CarbonCaptureRunConfig(slugs=["oxyfuel_combustion"], test_mode=True)
    assert config.effective_paper_limit() == 5
    assert config.effective_web_limit() == 5
    assert config.mode_label == "TEST MODE"

    custom = CarbonCaptureRunConfig(
        slugs=["oxyfuel_combustion"],
        test_mode=True,
        paper_limit=3,
        web_limit=2,
    )
    assert custom.effective_paper_limit() == 3
    assert custom.effective_web_limit() == 2


def test_all_methodologies_have_keywords() -> None:
    for methodology in all_methodologies():
        assert methodology.search_keywords
        assert methodology.synonyms
        assert methodology.retrieval_query


def test_legacy_field_mapping() -> None:
    row = validate_and_normalize_row(
        {
            "year": "2024",
            "location": "Norway",
            "value": "260 million RMB",
            "unit": "",
            "boundary": "cement plant",
            "source": "Web",
            "title": "Project page",
            "url_citation": "https://example.org/project",
            "cost": "260 million RMB",
            "metric_dimension": "Cost",
        },
    )
    assert row["project_year"] == "2024"
    assert row["project_location"] == "Norway"
    assert row["metric_value"] == "260 million"
    assert row["metric_unit"] == "RMB"
    assert row["metric_boundary"] == "cement plant"
    assert row["source_type"] == "Web"
    assert row["source_title"] == "Project page"
    assert row["source_url_or_citation"] == "https://example.org/project"
    assert row["metric_name"] == "total investment"
    assert row["cost_impact"] == "260 million RMB"


def test_mineralization_screening_subpath_mapped() -> None:
    from pipeline.carbon_capture_config import get_methodology
    from pipeline.screening import CCS_SUBPATHS, normalize_subpaths

    assert "mineralization" in CCS_SUBPATHS
    methodology = get_methodology("mineralization")
    assert methodology.screening_subpath == "mineralization"
    assert normalize_subpaths(["mineralization", "carbonation curing", "CO2 curing"]) == [
        "mineralization",
    ]


def test_canonical_csv_headers_exact() -> None:
    assert list(CANONICAL_FIELDS) == [
        "category",
        "subcategory",
        "technology_type",
        "company_or_organization",
        "project_name",
        "project_year",
        "project_location",
        "deployment_stage",
        "metric_dimension",
        "metric_name",
        "metric_value",
        "metric_unit",
        "metric_boundary",
        "co2_reduction",
        "energy_impact",
        "cost_impact",
        "primary_barriers",
        "source_type",
        "source_title",
        "source_url_or_citation",
        "confidence",
        "notes",
    ]


def test_cluster_web_stage_writes_web_rows() -> None:
    import tempfile
    from unittest.mock import patch

    from pipeline.carbon_capture_io import read_extraction_shard
    from pipeline.carbon_capture_stages import extract_web_for_methodology

    methodology = get_methodology("oxyfuel_combustion")
    seed = _sample_literature_row(
        company_or_organization="China United Cement",
        project_name="Qingzhou Oxy-fuel",
        technology_type="oxyfuel combustion",
    )
    fake_sources = [
        {
            "source_type": "Web",
            "title": "Project page",
            "url": "https://example.org/oxyfuel",
            "snippet": "oxyfuel pilot",
            "full_text": "oxyfuel pilot plant",
            "search_query": "oxyfuel",
        },
    ]
    fake_rows = [
        _sample_literature_row(
            record_id="oxyfuel_combustion:web1:0",
            result_id="oxyfuel_combustion:web1",
            source_origin="web",
            source_type="Web",
            source_title="Project page",
            source_url_or_citation="https://example.org/oxyfuel",
            methodology_slug="oxyfuel_combustion",
        ),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "oxyfuel_combustion_web.jsonl"
        with (
            patch(
                "pipeline.carbon_capture_stages.discover_web_sources",
                return_value=fake_sources,
            ) as discover,
            patch(
                "pipeline.carbon_capture_stages.extract_web_sources_parallel",
                return_value=fake_rows,
            ) as extract,
        ):
            written = extract_web_for_methodology(
                methodology,
                literature_rows=[seed],
                output_path=out_path,
                max_total_sources=10,
            )
            discover.assert_called_once()
            extract.assert_called_once()
            assert written == out_path

        loaded = read_extraction_shard(out_path)
        assert len(loaded) == 1
        assert loaded[0].source_origin == "web"
        assert loaded[0].source_type == "Web"


def main() -> int:
    tests = [
        test_six_methodologies_configured,
        test_global_output_filenames,
        test_metric_expansion_preserves_project_identity,
        test_missing_values_normalize_to_na,
        test_controlled_vocab_normalization,
        test_web_query_templates,
        test_metric_expansion_creates_separate_rows,
        test_conservative_merge_fills_na_without_overwriting,
        test_global_pipeline_export_shape,
        test_validate_row_fills_missing_fields,
        test_resolve_subcategory_slug,
        test_test_mode_default_output_dir,
        test_run_config_effective_limits,
        test_all_methodologies_have_keywords,
        test_legacy_field_mapping,
        test_mineralization_screening_subpath_mapped,
        test_canonical_csv_headers_exact,
        test_cluster_web_stage_writes_web_rows,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"All {len(tests)} carbon capture tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
