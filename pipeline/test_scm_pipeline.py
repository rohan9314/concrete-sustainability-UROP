"""Tests for the SCM pipeline and carbon-capture compatibility regressions."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.carbon_capture_config import (
    CARBON_CAPTURE_METHODOLOGIES,
    list_methodology_slugs,
)
from pipeline.carbon_capture_schema import CANONICAL_FIELDS as CC_FIELDS
from pipeline.carbon_capture_schema import NA as CC_NA
from pipeline.scm import __main__ as scm_main
from pipeline.scm.classification import heuristic_groupings
from pipeline.scm.config import scm_output_root
from pipeline.scm.discovery import (
    aggregate_discovery_candidates,
    build_discovered_category_rows,
    recommend_action,
)
from pipeline.scm.export import export_combined_outputs, export_seed_category_outputs
from pipeline.scm.extraction import ScmDiscoveryRow, ScmEvidenceRow
from pipeline.scm.io import merge_screening_shards, write_screening_shard
from pipeline.scm.merge import conservative_merge_rows
from pipeline.scm.normalize import normalize_discovery_records, normalize_material_name
from pipeline.scm.postprocess import build_category_config_payload, write_category_config
from pipeline.scm.runner import (
    TEST_MODE_MAX_CORPUS_SPAN,
    ScmRunConfig,
    resolve_scm_output_dir,
)
from pipeline.scm.schema import (
    EVIDENCE_FIELDS,
    NA,
    decode_list_field,
    encode_list_field,
    validate_and_normalize_discovery_row,
    validate_and_normalize_evidence_row,
)
from pipeline.scm.screening import ScmScreeningResult
from pipeline.scm.seed_categories import (
    SCM_SEED_CATEGORIES,
    all_seed_categories,
    get_seed_category,
    list_seed_category_ids,
)


def _evidence(**overrides) -> ScmEvidenceRow:
    base = {
        "record_id": "slag_cement:p1:0",
        "category": "Supplementary Cementitious Materials",
        "seed_category": "slag_cement",
        "raw_material_name": "GGBFS",
        "canonical_material_name": "Slag Cement",
        "alternative_names": json.dumps(["GGBS"]),
        "replacement_percentage": "40",
        "replacement_basis": "cement mass",
        "strength_result": "45 MPa",
        "strength_test_age": "28 days",
        "source_type": "Literature",
        "source_id": "p1",
        "source_title": "Paper",
        "source_url_or_citation": "https://example.org/p1",
        "confidence": "Medium",
        "pipeline_branch": "seed_category",
        "source_origin": "literature",
        "deployment_stage": "Laboratory",
    }
    base.update(overrides)
    return ScmEvidenceRow.from_dict(base)


def _discovery(**overrides) -> ScmDiscoveryRow:
    base = {
        "discovery_record_id": "discovery:p1:0",
        "source_id": "p1",
        "source_type": "Literature",
        "source_title": "Novel ash paper",
        "source_url_or_citation": "https://example.org/p1",
        "raw_material_name": "Rice Husk Ash",
        "proposed_canonical_name": "Rice Husk Ash",
        "proposed_category_label": "Rice Husk Ash",
        "seed_category_match": "false",
        "matched_seed_category": NA,
        "classification_confidence": "Medium",
        "source_origin": "literature",
    }
    base.update(overrides)
    return ScmDiscoveryRow.from_dict(base)


def test_carbon_capture_commands_still_importable() -> None:
    from pipeline import run_carbon_capture
    from pipeline import run_carbon_capture_cluster

    assert hasattr(run_carbon_capture, "main")
    assert hasattr(run_carbon_capture_cluster, "main")
    assert len(list_methodology_slugs()) == 7
    assert set(list_methodology_slugs()) == set(CARBON_CAPTURE_METHODOLOGIES.keys())


def test_carbon_capture_schema_unchanged() -> None:
    assert list(CC_FIELDS) == [
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
    assert CC_NA == "N.A."


def test_every_scm_seed_category_loads() -> None:
    assert list(SCM_SEED_CATEGORIES.keys()) == list_seed_category_ids()
    assert len(list_seed_category_ids()) == 8
    for category in all_seed_categories():
        assert category.search_terms
        assert category.synonyms
        assert category.retrieval_query
        assert category.results_filename.endswith("_results.csv")
        assert category.citations_filename.endswith("_citations.csv")


def test_seed_category_separate_output_paths() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)
        paths = set()
        for category in all_seed_categories():
            summary = export_seed_category_outputs(
                literature_rows=[_evidence(seed_category=category.slug, record_id=f"{category.slug}:1:0")],
                web_rows=[],
                category=category,
                output_dir=output_dir,
            )
            assert Path(summary.results_path).name == f"{category.slug}_results.csv"
            assert Path(summary.citations_path).name == f"{category.slug}_citations.csv"
            paths.add(summary.results_path)
        assert len(paths) == 8


def test_discovery_accepts_unfamiliar_materials() -> None:
    row = validate_and_normalize_discovery_row(
        {
            "raw_material_name": "Banana Peel Ash",
            "proposed_category_label": "Agricultural Ash",
            "seed_category_match": False,
            "matched_seed_category": "NA",
        },
    )
    assert row["raw_material_name"] == "Banana Peel Ash"
    assert row["proposed_category_label"] == "Agricultural Ash"
    assert row["seed_category_match"] == "false"
    assert row["matched_seed_category"] == NA


def test_discovery_does_not_force_seed_category() -> None:
    row = _discovery()
    assert row.seed_category_match == "false"
    assert row.matched_seed_category == NA
    normalized = validate_and_normalize_discovery_row(row.to_discovery_dict())
    assert normalized["matched_seed_category"] == NA


def test_alias_normalization_preserves_raw_and_overrides() -> None:
    result = normalize_material_name(
        "GGBFS",
        proposed_canonical_name="something else",
        overrides={"GGBFS": "Slag Cement"},
    )
    assert result["raw_material_name"] == "GGBFS"
    assert result["final_canonical_name"] == "Slag Cement"
    assert result["manual_override_applied"] == "true"
    assert result["normalization_method"] == "manual_override"

    batch = normalize_discovery_records(
        [{"raw_material_name": "GGBS", "proposed_canonical_name": NA}],
        overrides={"GGBS": "Slag Cement"},
    )
    assert batch[0]["raw_material_name"] == "GGBS"
    assert batch[0]["final_canonical_name"] == "Slag Cement"


def test_corpus_level_clustering_uses_aggregated_records() -> None:
    rows = [
        _discovery(discovery_record_id=f"d{i}", source_id=f"s{i}", raw_material_name="Rice Husk Ash")
        for i in range(3)
    ]
    aggregated = aggregate_discovery_candidates(rows)
    assert len(aggregated) == 1
    assert aggregated[0]["total_record_count"] == 3
    groupings = heuristic_groupings(aggregated)
    assert groupings[0]["proposed_category"]
    discovered = build_discovered_category_rows(aggregated, llm_groupings=groupings)
    assert discovered[0]["proposed_category"]


def test_promotion_thresholds_respected() -> None:
    thresholds = {
        "min_strongly_relevant_records": 20,
        "min_unique_sources": 10,
        "min_independent_organizations": 5,
        "min_literature_sources": 5,
    }
    weak = {
        "total_record_count": 25,
        "unique_source_count": 12,
        "unique_organization_count": 2,
        "literature_source_count": 6,
        "seed_category_overlap": [NA],
    }
    action, _ = recommend_action(
        weak,
        thresholds=thresholds,
        llm_recommendation="CREATE_DEDICATED_PIPELINE",
        classification_coherence="High",
    )
    assert action == "INSUFFICIENT_EVIDENCE"

    strong = {
        "total_record_count": 25,
        "unique_source_count": 12,
        "unique_organization_count": 6,
        "literature_source_count": 6,
        "seed_category_overlap": [NA],
    }
    action, _ = recommend_action(
        strong,
        thresholds=thresholds,
        classification_coherence="High",
    )
    assert action == "CREATE_DEDICATED_PIPELINE"


def test_ternary_blends_preserve_constituents() -> None:
    constituents = [
        {"material_name": "Coal Fly Ash", "fraction_percent": 30},
        {"material_name": "Slag Cement", "fraction_percent": 40},
    ]
    row = validate_and_normalize_evidence_row(
        {
            "seed_category": "ternary_blends",
            "raw_material_name": "ternary blend",
            "constituent_materials": constituents,
            "binder_system": "OPC/slag/fly ash",
        },
    )
    decoded = decode_list_field(row["constituent_materials"])
    assert len(decoded) == 2
    assert decoded[0]["material_name"] == "Coal Fly Ash"
    assert row["canonical_material_name"] == NA or "Coal Fly Ash" not in row.get(
        "canonical_material_name",
        "",
    )


def test_missing_values_remain_na() -> None:
    row = validate_and_normalize_evidence_row({"raw_material_name": "fly ash", "notes": ""})
    assert row["notes"] == NA
    assert row["replacement_percentage"] == NA
    for field in EVIDENCE_FIELDS:
        assert row[field] != ""


def test_literature_web_provenance_distinguishable() -> None:
    lit = _evidence(source_type="Literature", source_origin="literature")
    web = _evidence(
        record_id="slag_cement:w1:0",
        source_type="Web",
        source_origin="web",
        source_id="https://example.org/web",
        replacement_percentage="50",
    )
    merged, _ = conservative_merge_rows([lit], [web])
    assert len(merged) == 2
    types = {row.source_type for row in merged}
    assert types == {"Literature", "Web"}


def test_merge_preserves_conflicting_measurements() -> None:
    a = _evidence(replacement_percentage="30", strength_test_age="7 days")
    b = _evidence(
        record_id="slag_cement:p1:1",
        replacement_percentage="50",
        strength_test_age="28 days",
    )
    merged, stats = conservative_merge_rows([a, b], [])
    assert len(merged) == 2
    assert stats.exact_duplicates_removed == 0


def test_test_mode_cannot_process_full_corpus() -> None:
    config = ScmRunConfig(
        slugs=["slag_cement"],
        test_mode=True,
        start=0,
        end=200000,
        paper_limit=5,
    )
    start, end = config.effective_start_end()
    assert end - start <= max(5, TEST_MODE_MAX_CORPUS_SPAN)
    assert end - start < 200000


def test_carbon_capture_and_scm_output_dirs_do_not_collide() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        os.environ.pop("SCM_OUTPUT_ROOT", None)
        scm_dir = scm_output_root()
        assert scm_dir.name == "scm"
        assert scm_dir.resolve() != (Path(tmp) / "carbon_capture").resolve()
        test_dir = resolve_scm_output_dir(raw="", test_mode=True)
        assert test_dir.as_posix().endswith("test/scm")
        assert test_dir != scm_dir


def test_cluster_scripts_use_env_paths() -> None:
    script = (REPO_ROOT / "scripts" / "engaging" / "scm" / "02_screen_array.sh").read_text()
    assert "PICKLE_PATH" in script
    assert "OUTPUT_DIR" in script or "SCM_OUTPUT_ROOT" in script
    assert "/home/rohan931" not in script
    assert "pipeline.scm.cluster" in script
    assert "run_carbon_capture" not in script
    assert "carbon_capture/" not in script


def test_resume_skips_completed_shards() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "screening_0_10.jsonl"
        result = ScmScreeningResult(
            paper_id="p1",
            title="t",
            year="2020",
            doi="",
            is_relevant=True,
            confidence=0.9,
            reason="test",
            mentioned_materials=["slag"],
            matched_seed_hints=["slag_cement"],
        )
        write_screening_shard([result], out, shard_start=0, shard_end=10)
        assert out.is_file() and out.stat().st_size > 0
        # Second write of merge should keep unique paper ids
        merged = Path(tmp) / "merged.jsonl"
        merge_screening_shards([out, out], merged)
        lines = [json.loads(line) for line in merged.read_text().splitlines() if line.strip()]
        paper_rows = [row for row in lines if row.get("paper_id")]
        assert len(paper_rows) == 1


def test_generate_category_config_is_proposed() -> None:
    payload = build_category_config_payload(category="Rice Husk Ash")
    assert payload["status"] == "proposed"
    assert payload["category_id"] == "rice_husk_ash"
    with tempfile.TemporaryDirectory() as tmp:
        path = write_category_config(payload, Path(tmp) / "rice_husk_ash.yaml")
        text = path.read_text()
        assert "status: proposed" in text
        assert "rice_husk_ash" in text


def test_cli_help_lists_commands() -> None:
    with patch("sys.argv", ["pipeline.scm", "--help"]):
        try:
            scm_main.main(["--help"])
        except SystemExit as exc:
            assert exc.code == 0


def test_combined_export_pipeline_branch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp)
        seed = _evidence()
        discovery = _evidence(
            record_id="discovery:rha:0",
            seed_category=NA,
            raw_material_name="Rice Husk Ash",
            pipeline_branch="open_discovery",
            source_id="rha1",
        )
        summary = export_combined_outputs(
            seed_rows=[seed],
            discovery_evidence_rows=[discovery],
            output_dir=output_dir,
        )
        with Path(summary.all_evidence_path).open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        branches = {row["pipeline_branch"] for row in rows}
        assert branches == {"seed_category", "open_discovery"}


def test_list_field_json_encoding() -> None:
    encoded = encode_list_field(["a", "b"])
    assert json.loads(encoded) == ["a", "b"]
    assert encode_list_field(None) == NA


def main() -> int:
    tests = [
        test_carbon_capture_commands_still_importable,
        test_carbon_capture_schema_unchanged,
        test_every_scm_seed_category_loads,
        test_seed_category_separate_output_paths,
        test_discovery_accepts_unfamiliar_materials,
        test_discovery_does_not_force_seed_category,
        test_alias_normalization_preserves_raw_and_overrides,
        test_corpus_level_clustering_uses_aggregated_records,
        test_promotion_thresholds_respected,
        test_ternary_blends_preserve_constituents,
        test_missing_values_remain_na,
        test_literature_web_provenance_distinguishable,
        test_merge_preserves_conflicting_measurements,
        test_test_mode_cannot_process_full_corpus,
        test_carbon_capture_and_scm_output_dirs_do_not_collide,
        test_cluster_scripts_use_env_paths,
        test_resume_skips_completed_shards,
        test_generate_category_config_is_proposed,
        test_cli_help_lists_commands,
        test_combined_export_pipeline_branch,
        test_list_field_json_encoding,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"All {len(tests)} SCM / compatibility tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
