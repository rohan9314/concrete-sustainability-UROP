#!/usr/bin/env python3
"""Workflow / retrieval / export manifest field tests (offline)."""

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

from pipeline.cementitious.final_metadata import build_run_manifest
from pipeline.cementitious.hierarchical_export import write_hierarchical_export
from pipeline.cementitious.paths import TAXONOMY_EXPORT_MANIFEST_REL, ensure_730_layout
from pipeline.cementitious.schema import RECORD_FIELDS
from pipeline.cementitious.web_scope import (
    build_retrieval_coverage_manifest,
    searchable_node_summaries,
    write_web_search_scope_manifest,
)
from pipeline.cementitious.workflow_launch import build_launch_config, build_workflow_dry_run
from pipeline.decarb_testlib import (
    REPRESENTATIVE_PATHS,
    canonical_record,
    launch_env,
    record_for_path,
    write_json,
    write_jsonl,
)


class WorkflowManifestTests(unittest.TestCase):
    def test_taxonomy_export_manifest_row_counts_and_zero_record_nodes(self) -> None:
        rows = [
            record_for_path(REPRESENTATIVE_PATHS[0], record_id="opc"),
            record_for_path(REPRESENTATIVE_PATHS[1], record_id="amine"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_hierarchical_export(root, rows, fieldnames=RECORD_FIELDS)
            manifest = json.loads((root / TAXONOMY_EXPORT_MANIFEST_REL).read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_canonical_records"], 2)
            zero_l4 = [n for n in manifest["nodes"] if n["level"] == 4 and n["zero_records"]]
            populated_l4 = [n for n in manifest["nodes"] if n["level"] == 4 and not n["zero_records"]]
            self.assertGreaterEqual(len(zero_l4), 1)
            self.assertEqual(len(populated_l4), 2)
            self.assertTrue(all(n["csv_emitted"] for n in zero_l4))
            self.assertTrue(all(n["csv_emitted"] for n in populated_l4))
            self.assertTrue(all(n["csv_path"] for n in zero_l4))

    def test_web_scope_and_retrieval_coverage_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = ensure_730_layout(root)
            nodes = searchable_node_summaries()[:8]
            queries = [
                {
                    "query_id": f"wq_{i:05d}",
                    "taxonomy_path": n["path"],
                    "sub_subcategory_slug": n["slug"],
                    "taxonomy_level_1": n.get("level_1"),
                    "query_text": f"query {n['slug']}",
                }
                for i, n in enumerate(nodes)
            ]
            write_web_search_scope_manifest(root, queries=queries, scope="canonical", nodes=nodes)
            write_json(layout["metadata"] / "web_queries.json", queries)
            write_jsonl(
                layout["metadata"] / "web_search_results_raw.jsonl",
                [{"url": "https://ex.example/a", "taxonomy_path": nodes[0]["path"]}],
            )
            write_jsonl(
                layout["metadata"] / "web_records_raw.jsonl",
                [
                    canonical_record(
                        record_id="w1",
                        evidence_origin="Web",
                        taxonomy_level_4=nodes[0].get("label") or "Amine Absorption",
                    )
                ],
            )
            write_jsonl(
                layout["metadata"] / "literature_records_raw.jsonl",
                [canonical_record(record_id="l1", evidence_origin="Literature")],
            )
            master = layout["all_records"] / "cementitious_materials_all_records.csv"
            with master.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                writer.writerow(canonical_record(record_id="l1", evidence_origin="Literature"))
                writer.writerow(
                    canonical_record(
                        record_id="w1",
                        evidence_origin="Web",
                        source_url="https://ex.example/a",
                    )
                )
            coverage = build_retrieval_coverage_manifest(root)
            self.assertIn("totals_by_evidence_origin", coverage)
            origins = coverage["totals_by_evidence_origin"]
            self.assertGreaterEqual(int(origins.get("Literature") or 0), 1)
            self.assertGreaterEqual(int(origins.get("Web") or 0), 1)
            scope = json.loads((layout["metadata"] / "web_search_scope.json").read_text())
            self.assertEqual(scope["web_search_scope"], "canonical")
            self.assertEqual(scope["query_count"], len(queries))
            self.assertFalse(scope["restricted_to_chemical_absorption"])

    def test_run_manifest_includes_job_ids_taxonomy_and_totals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = ensure_730_layout(root)
            write_json(
                layout["metadata"] / "submitted_jobs.json",
                {"jobs": [{"name": "cm-export", "job_id": "12345"}]},
            )
            master = layout["all_records"] / "cementitious_materials_all_records.csv"
            with master.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                writer.writerow(canonical_record(record_id="l1", evidence_origin="Literature"))
            write_jsonl(
                layout["metadata"] / "literature_records_raw.jsonl",
                [canonical_record(record_id="l1", evidence_origin="Literature")],
            )
            (layout["checkpoints"] / "export.complete").write_text("ok\n", encoding="utf-8")
            manifest = build_run_manifest(
                root,
                environ={
                    "RUN_MODE": "literature-and-web",
                    "CEMENTITIOUS_MAX_RECORDS": "50",
                },
            )
            self.assertTrue(manifest.get("taxonomy_path"))
            self.assertEqual(manifest["submitted_job_ids"][0]["job_id"], "12345")
            self.assertIn("final_records_from_literature", manifest)
            self.assertIn("web_search_scope", manifest)
            self.assertIn("literature_record_cap", manifest)

    def test_dry_run_plan_records_export_paths_and_final_totals_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp), extra={"CEMENTITIOUS_PILOT_TAXONOMY_SCOPE": "all"})
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=True, env=env)
                plan = build_workflow_dry_run(cfg)
            self.assertIn("export_paths", plan)
            self.assertIn("user_facing_export", plan)
            self.assertTrue(plan["user_facing_export"]["master_csv"].endswith(".csv"))
            self.assertGreater(plan["web_search_node_count"], 1)
            self.assertEqual(plan["literature_record_cap"], 50)


if __name__ == "__main__":
    unittest.main()
