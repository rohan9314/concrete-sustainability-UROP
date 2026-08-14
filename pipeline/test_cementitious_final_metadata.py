#!/usr/bin/env python3
"""Tests for final run_manifest.json / validation_report.json contract."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.final_metadata import (
    FinalMetadataError,
    finalize_metadata,
    write_final_metadata,
)
from pipeline.cementitious.paths import ensure_730_layout, safe_partition_filename
from pipeline.cementitious.schema import CITATION_FIELDS, RECORD_FIELDS, normalize_record
from pipeline.cementitious.stages import export_final
from pipeline.cementitious.taxonomy import get_taxonomy


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def _record(*, rid: str, sub: str, leaf: str) -> dict:
    tax = get_taxonomy()
    return normalize_record(
        {
            "record_id": rid,
            "category": "Cementitious Materials",
            "subcategory": tax.subcategories[sub].display_name,
            "subcategory_slug": sub,
            "sub_subcategory": tax.sub_subcategories[leaf].display_name,
            "sub_subcategory_slug": leaf,
            "technology_variant": "Amine Scrubbing",
            "canonical_technology_name": "Amine Scrubbing",
            "raw_technology_name": "amine",
            "taxonomy_version": tax.taxonomy_version,
            "taxonomy_confidence": "High",
            "classification_basis": "Explicit",
            "classification_reasoning": "test",
            "technology_domain": "Carbon Capture",
            "functional_role": "CO2 Capture",
            "evidence_origin": "Literature",
            "source_type": "Academic Literature",
            "source_id": f"doi:{rid}",
            "source_title": f"Title {rid}",
            "citation": f"doi:{rid}",
            "evidence_text": "explicit amine scrubbing evidence text",
            "extraction_confidence": "High",
        },
        taxonomy=tax,
    )


def _citation(rec: dict) -> dict:
    return {k: rec.get(k, "") for k in CITATION_FIELDS}


def _seed_full_empty_partitions(root: Path, tax) -> None:
    layout = ensure_730_layout(root)
    for node in tax.subcategories.values():
        _write_csv(layout["subcategories"] / safe_partition_filename(node.slug), RECORD_FIELDS, [])
        _write_csv(
            layout["citations_subcategories"] / safe_partition_filename(f"{node.slug}_citations"),
            CITATION_FIELDS,
            [],
        )
    for node in tax.sub_subcategories.values():
        _write_csv(
            layout["sub_subcategories"] / safe_partition_filename(node.slug), RECORD_FIELDS, []
        )
        _write_csv(
            layout["citations_sub_subcategories"]
            / safe_partition_filename(f"{node.slug}_citations"),
            CITATION_FIELDS,
            [],
        )


def _seed_pilot_style_output(root: Path, *, n: int = 5, wrong_leaf: bool = False) -> list[dict]:
    tax = get_taxonomy()
    layout = ensure_730_layout(root)
    _seed_full_empty_partitions(root, tax)
    records = [
        _record(rid=f"r{i}", sub="cement_plant_carbon_capture", leaf="chemical_absorption")
        for i in range(n)
    ]
    if wrong_leaf and records:
        # Place first record into wrong leaf file later.
        pass
    cites = [_citation(r) for r in records]
    _write_csv(layout["all_records"] / "cementitious_materials_all_records.csv", RECORD_FIELDS, records)
    _write_csv(layout["all_records"] / "citations_all.csv", CITATION_FIELDS, cites)
    # Populate correct partitions.
    leaf_rows = list(records)
    if wrong_leaf and leaf_rows:
        # Put record into biomass_ashes instead of chemical_absorption.
        _write_csv(
            layout["sub_subcategories"] / safe_partition_filename("chemical_absorption"),
            RECORD_FIELDS,
            leaf_rows[1:],
        )
        _write_csv(
            layout["sub_subcategories"] / safe_partition_filename("biomass_ashes"),
            RECORD_FIELDS,
            [leaf_rows[0]],
        )
    else:
        _write_csv(
            layout["subcategories"] / safe_partition_filename("cement_plant_carbon_capture"),
            RECORD_FIELDS,
            records,
        )
        _write_csv(
            layout["sub_subcategories"] / safe_partition_filename("chemical_absorption"),
            RECORD_FIELDS,
            records,
        )
    if not wrong_leaf:
        _write_csv(
            layout["citations_subcategories"]
            / safe_partition_filename("cement_plant_carbon_capture_citations"),
            CITATION_FIELDS,
            cites,
        )
        _write_csv(
            layout["citations_sub_subcategories"]
            / safe_partition_filename("chemical_absorption_citations"),
            CITATION_FIELDS,
            cites,
        )
    # partition summary rows (one per node)
    summary_rows = []
    for node in tax.subcategories.values():
        summary_rows.append(
            {
                "level": "subcategory",
                "slug": node.slug,
                "display_name": node.display_name,
                "record_count": str(n if node.slug == "cement_plant_carbon_capture" and not wrong_leaf else 0),
                "output_path": f"subcategories/{node.slug}.csv",
            }
        )
    for node in tax.sub_subcategories.values():
        count = 0
        if not wrong_leaf and node.slug == "chemical_absorption":
            count = n
        summary_rows.append(
            {
                "level": "sub_subcategory",
                "slug": node.slug,
                "display_name": node.display_name,
                "record_count": str(count),
                "output_path": f"sub_subcategories/{node.slug}.csv",
            }
        )
    _write_csv(
        layout["all_records"] / "partition_summary.csv",
        ("level", "slug", "display_name", "record_count", "output_path"),
        summary_rows,
    )
    # Empty audits
    for name in (
        "missing_partition_citations.csv",
        "invalid_taxonomy_records.csv",
        "missing_screen_shards.csv",
        "missing_web_search_shards.csv",
        "missing_web_extraction_shards.csv",
    ):
        _write_csv(layout["rejected_records"] / name, ("record_id",), [])
    # Workflow checkpoints for lit+web pilot
    for name in (
        "plan_screen.complete",
        "screen_merge.complete",
        "extract_merge.complete",
        "plan_web_queries.complete",
        "web_search_merge.complete",
        "web_extract_merge.complete",
        "merge_literature_web.complete",
        "dedupe_qc.complete",
    ):
        (layout["checkpoints"] / name).write_text("ok\n", encoding="utf-8")
    # Resource files
    (layout["metadata"] / "resource_usage_summary.json").write_text(
        json.dumps({"rows": [], "generated_at": "t"}, indent=2) + "\n", encoding="utf-8"
    )
    (layout["metadata"] / "full_run_resource_recommendations.json").write_text(
        json.dumps({"stages": {}, "safety_factor": 1.5}, indent=2) + "\n", encoding="utf-8"
    )
    (layout["metadata"] / "merged_records.csv").write_text(
        (layout["all_records"] / "cementitious_materials_all_records.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return records


class FinalMetadataContractTests(unittest.TestCase):
    def test_successful_pilot_style_output_generates_both_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "results parent" / "cementitious_engaging_pilot" / "7-30 results"
            _seed_pilot_style_output(root, n=5)
            env = {
                "RUN_MODE": "literature-and-web",
                "WORKFLOW_MODE": "pilot",
                "SELECTED_SUBCATEGORIES": "cement_plant_carbon_capture",
                "SELECTED_SUB_SUBCATEGORIES": "chemical_absorption",
                "REPO_ROOT": str(REPO_ROOT),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                result = write_final_metadata(root, environ=env, ensure_resources=False)
            self.assertEqual(result["overall_status"], "pass")
            self.assertTrue((root / "metadata" / "run_manifest.json").is_file())
            self.assertTrue((root / "metadata" / "validation_report.json").is_file())
            manifest = json.loads((root / "metadata" / "run_manifest.json").read_text())
            report = json.loads((root / "metadata" / "validation_report.json").read_text())
            self.assertEqual(manifest["schema_version"], "cementitious-run-manifest-v1")
            self.assertEqual(report["schema_version"], "cementitious-validation-report-v1")
            self.assertEqual(manifest["taxonomy_subcategory_count"], 9)
            self.assertEqual(manifest["taxonomy_leaf_count"], 58)
            self.assertEqual(manifest["master_record_count"], 5)
            self.assertFalse(manifest.get("secrets_included"))
            self.assertNotIn("sk-", json.dumps(manifest))
            self.assertEqual(report["overall_status"], "pass")
            # Empty partitions still recognized.
            self.assertTrue(any(c["check_name"] == "all_leaf_record_csvs_exist" and c["status"] == "pass" for c in report["checks"]))
            self.assertTrue(any(c["check_name"] == "all_subcategory_record_csvs_exist" and c["status"] == "pass" for c in report["checks"]))

    def test_missing_from_leaf_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            records = _seed_pilot_style_output(root, n=3)
            # Remove one id from leaf file.
            layout = ensure_730_layout(root)
            _write_csv(
                layout["sub_subcategories"] / safe_partition_filename("chemical_absorption"),
                RECORD_FIELDS,
                records[1:],
            )
            env = {"RUN_MODE": "literature-and-web", "WORKFLOW_MODE": "pilot"}
            result = write_final_metadata(root, environ=env, ensure_resources=False)
            self.assertEqual(result["overall_status"], "fail")

    def test_wrong_subcategory_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            records = _seed_pilot_style_output(root, n=2)
            layout = ensure_730_layout(root)
            # Put records into wrong subcategory file and clear correct one.
            _write_csv(
                layout["subcategories"] / safe_partition_filename("cement_plant_carbon_capture"),
                RECORD_FIELDS,
                [],
            )
            _write_csv(
                layout["subcategories"] / safe_partition_filename("emerging_supplementary_cementitious_materials"),
                RECORD_FIELDS,
                records,
            )
            env = {"RUN_MODE": "literature-and-web", "WORKFLOW_MODE": "pilot"}
            result = write_final_metadata(root, environ=env, ensure_resources=False)
            self.assertEqual(result["overall_status"], "fail")

    def test_duplicate_record_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            records = _seed_pilot_style_output(root, n=2)
            records.append(dict(records[0]))
            layout = ensure_730_layout(root)
            _write_csv(layout["all_records"] / "cementitious_materials_all_records.csv", RECORD_FIELDS, records)
            env = {"RUN_MODE": "literature-and-web", "WORKFLOW_MODE": "pilot"}
            result = write_final_metadata(root, environ=env, ensure_resources=False)
            self.assertEqual(result["overall_status"], "fail")

    def test_missing_citation_partition_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            _seed_pilot_style_output(root, n=2)
            layout = ensure_730_layout(root)
            (
                layout["citations_sub_subcategories"]
                / safe_partition_filename("chemical_absorption_citations")
            ).unlink()
            env = {"RUN_MODE": "literature-and-web", "WORKFLOW_MODE": "pilot"}
            result = write_final_metadata(root, environ=env, ensure_resources=False)
            self.assertEqual(result["overall_status"], "fail")

    def test_malformed_header_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            _seed_pilot_style_output(root, n=1)
            layout = ensure_730_layout(root)
            path = layout["all_records"] / "cementitious_materials_all_records.csv"
            path.write_text("not_a_real_header\nx\n", encoding="utf-8")
            env = {"RUN_MODE": "literature-and-web", "WORKFLOW_MODE": "pilot"}
            result = write_final_metadata(root, environ=env, ensure_resources=False)
            self.assertEqual(result["overall_status"], "fail")

    def test_missing_resource_summary_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            _seed_pilot_style_output(root, n=1)
            (root / "metadata" / "resource_usage_summary.json").unlink()
            env = {"RUN_MODE": "literature-and-web", "WORKFLOW_MODE": "pilot"}
            result = write_final_metadata(root, environ=env, ensure_resources=False)
            self.assertEqual(result["overall_status"], "fail")

    def test_missing_recommendations_fails_for_pilot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cementitious_engaging_pilot" / "7-30 results"
            _seed_pilot_style_output(root, n=1)
            (root / "metadata" / "full_run_resource_recommendations.json").unlink()
            env = {"RUN_MODE": "literature-and-web", "WORKFLOW_MODE": "pilot"}
            result = write_final_metadata(root, environ=env, ensure_resources=False)
            self.assertEqual(result["overall_status"], "fail")

    def test_web_audits_skipped_when_web_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            _seed_pilot_style_output(root, n=1)
            # Remove web checkpoints so mode can be literature-only
            for name in (
                "plan_web_queries.complete",
                "web_search_merge.complete",
                "web_extract_merge.complete",
                "merge_literature_web.complete",
            ):
                (root / "checkpoints" / name).unlink(missing_ok=True)
            (root / "rejected_records" / "missing_web_search_shards.csv").unlink()
            env = {"RUN_MODE": "literature-only", "WORKFLOW_MODE": "pilot"}
            result = write_final_metadata(root, environ=env, ensure_resources=False)
            report = result["validation_report"]
            web_checks = [c for c in report["checks"] if "web_search_shard" in c["check_name"]]
            self.assertTrue(web_checks)
            self.assertTrue(all(c["status"] == "pass" for c in web_checks))

    def test_web_audits_fail_when_enabled_and_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            _seed_pilot_style_output(root, n=1)
            _write_csv(
                root / "rejected_records" / "missing_web_search_shards.csv",
                ("shard_id",),
                [{"shard_id": "0"}],
            )
            env = {"RUN_MODE": "literature-and-web", "WORKFLOW_MODE": "pilot"}
            result = write_final_metadata(root, environ=env, ensure_resources=False)
            self.assertEqual(result["overall_status"], "fail")

    def test_atomic_write_and_no_export_complete_on_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            _seed_pilot_style_output(root, n=1)
            # Break a required leaf CSV so validation fails.
            (
                root / "sub_subcategories" / safe_partition_filename("chemical_absorption")
            ).unlink()
            marker = root / "checkpoints" / "export.complete"
            self.assertFalse(marker.is_file())
            with self.assertRaises(FinalMetadataError):
                finalize_metadata(output_dir=root, require_pass=True, write_export_complete=True)
            self.assertFalse(marker.is_file())
            # Direct write still produces JSON for inspection.
            write_final_metadata(
                root,
                environ={"WORKFLOW_MODE": "pilot", "RUN_MODE": "literature-and-web"},
                ensure_resources=False,
            )
            self.assertTrue((root / "metadata" / "validation_report.json").is_file())
            report = json.loads((root / "metadata" / "validation_report.json").read_text())
            self.assertEqual(report["overall_status"], "fail")

    def test_repair_replaces_missing_manifests_even_with_old_export_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cementitious_engaging_pilot" / "7-30 results"
            _seed_pilot_style_output(root, n=2)
            marker = root / "checkpoints" / "export.complete"
            marker.write_text("old-incomplete\n", encoding="utf-8")
            # Simulate missing metadata from older run.
            for rel in ("metadata/run_manifest.json", "metadata/validation_report.json"):
                path = root / rel
                if path.is_file():
                    path.unlink()
            env = {
                "RUN_MODE": "literature-and-web",
                "WORKFLOW_MODE": "pilot",
                "SELECTED_SUBCATEGORIES": "cement_plant_carbon_capture",
                "SELECTED_SUB_SUBCATEGORIES": "chemical_absorption",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                result = finalize_metadata(output_dir=root, force=True, require_pass=True)
            self.assertEqual(result["overall_status"], "pass")
            self.assertTrue((root / "metadata" / "run_manifest.json").is_file())
            self.assertTrue((root / "metadata" / "validation_report.json").is_file())
            self.assertTrue(marker.is_file())

    def test_no_api_clients_during_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cementitious_engaging_pilot" / "7-30 results"
            _seed_pilot_style_output(root, n=1)
            env = {"RUN_MODE": "literature-and-web", "WORKFLOW_MODE": "pilot"}
            with mock.patch("pipeline.openai_client.call_openai") as oa, mock.patch(
                "pipeline.cementitious.web_tavily.get_tavily_client"
            ) as tv:
                finalize_metadata(output_dir=root, require_pass=True)
                oa.assert_not_called()
                tv.assert_not_called()
            # env unused except mode detection via finalize reading os.environ — set explicitly
            self.assertTrue((root / "metadata" / "run_manifest.json").is_file())

    def test_export_final_writes_metadata_before_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            records = _seed_pilot_style_output(root, n=1)
            layout = ensure_730_layout(root)
            # export_final reads metadata/merged_records.csv
            _write_csv(layout["metadata"] / "merged_records.csv", RECORD_FIELDS, records)
            env = {
                "RUN_MODE": "literature-only",
                "WORKFLOW_MODE": "full",
            }
            # Remove web checkpoints so literature-only validation applies.
            for name in (
                "plan_web_queries.complete",
                "web_search_merge.complete",
                "web_extract_merge.complete",
                "merge_literature_web.complete",
            ):
                (layout["checkpoints"] / name).unlink(missing_ok=True)
            with mock.patch.dict(os.environ, env, clear=False):
                summary = export_final(output_dir=root, force=True)
            self.assertEqual(summary.get("final_validation_status"), "pass")
            self.assertTrue((root / "metadata" / "run_manifest.json").is_file())
            self.assertTrue((root / "checkpoints" / "export.complete").is_file())
            self.assertTrue(
                (root / "cementitious_materials_results" / "cementitious_materials_all_records.csv").is_file()
            )


if __name__ == "__main__":
    unittest.main()
