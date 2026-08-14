#!/usr/bin/env python3
"""Offline tests: canonical taxonomy drives literature, web, and export."""

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

from pipeline.cementitious.decarb_literature import (
    heuristic_classify_canonical,
    keyword_screen_canonical,
    literature_uses_canonical_taxonomy,
)
from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy
from pipeline.cementitious.extraction import classify_and_extract, keyword_screen, screen_records
from pipeline.cementitious.hierarchical_export import write_hierarchical_export
from pipeline.cementitious.paths import DECARBONIZATION_EXPORT_DIRNAME, TAXONOMY_EXPORT_MANIFEST_REL
from pipeline.cementitious.schema import RECORD_FIELDS
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.cementitious.taxonomy_coverage import write_taxonomy_coverage_report
from pipeline.cementitious.web_queries import plan_canonical_web_queries, plan_web_queries
from pipeline.cementitious.web_scope import (
    build_retrieval_coverage_manifest,
    searchable_web_nodes,
    write_web_search_scope_manifest,
)
from pipeline.cementitious.workflow_launch import (
    FULL_LAUNCH_MODE,
    PILOT_50_LAUNCH_MODE,
    PILOT_1000_LAUNCH_MODE,
    build_launch_config,
    build_workflow_dry_run,
    taxonomy_scope_label,
)
from pipeline.decarb_testlib import (
    SYNTHETIC_LITERATURE_CASES,
    canonical_record,
    launch_env,
    paper_record,
    record_for_path,
    web_limits,
    write_json,
    write_jsonl,
)


class LiteratureCanonicalTaxonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tax = get_taxonomy()
        self.decarb = get_decarbonization_taxonomy()

    def test_literature_screening_uses_canonical_not_old_9x58_scope(self) -> None:
        self.assertTrue(literature_uses_canonical_taxonomy())
        self.assertFalse(
            literature_uses_canonical_taxonomy(focus_ss_slugs=["chemical_absorption"])
        )
        row = keyword_screen(
            paper_record(
                1,
                title="Buy Clean programs for embodied-carbon procurement limits",
                abstract="Green public procurement of cement via Buy Clean programs.",
            ),
            0,
            taxonomy=self.tax,
        )
        self.assertTrue(row["is_relevant"])
        self.assertEqual(row.get("literature_taxonomy"), "canonical")
        self.assertIn("Policy", row.get("suggested_level_1") or [])

    def test_non_cementitious_literature_reaches_extraction(self) -> None:
        with mock.patch("pipeline.cementitious.extraction.call_json_llm") as llm:
            rec, _ = classify_and_extract(
                paper_record(
                    2,
                    title="Carbonated RCA treated recycled concrete aggregate",
                    abstract="Treated RCA carbonated recycled concrete aggregates for procurement.",
                ),
                taxonomy=self.tax,
                keyword_only=True,
            )
        llm.assert_not_called()
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["taxonomy_level_1"], "Aggregate Procurement")
        self.assertNotEqual(rec["taxonomy_level_1"], "Cementitious Materials")

    def test_all_seven_level1_categories_reachable_from_literature(self) -> None:
        seen: set[str] = set()
        with mock.patch("pipeline.cementitious.extraction.call_json_llm") as llm:
            for case in SYNTHETIC_LITERATURE_CASES:
                paper = paper_record(0, title=case["title"], abstract=case["abstract"])
                screen = keyword_screen_canonical(paper, 0)
                self.assertTrue(screen["is_relevant"], case["title"])
                rec, _ = classify_and_extract(paper, taxonomy=self.tax, keyword_only=True)
                self.assertIsNotNone(rec, case["title"])
                assert rec is not None
                self.assertEqual(rec["taxonomy_level_1"], case["level_1"], case["title"])
                if rec.get("taxonomy_level_4") not in {"", "N.A."}:
                    self.assertEqual(rec["taxonomy_level_4"], case["level_4"], case["title"])
                seen.add(rec["taxonomy_level_1"])
        llm.assert_not_called()
        self.assertEqual(
            seen,
            {
                "Cementitious Materials",
                "Aggregate Procurement",
                "Concrete Design",
                "Structural and Construction Design",
                "Operation",
                "Policy",
                "End-of-Life",
            },
        )

    def test_unsupported_deeper_levels_remain_na(self) -> None:
        paths = heuristic_classify_canonical(
            paper_record(
                3,
                title="Concrete decarbonization policy overview",
                abstract="Policy instruments for cement and concrete embodied carbon.",
            )
        )
        self.assertTrue(paths)
        self.assertEqual(paths[0]["taxonomy_level_1"], "Policy")
        if paths[0]["taxonomy_level_4"] not in {"", "N.A."}:
            self.fail("must not invent a Level-4 leaf without supporting evidence")

    def test_pilot_and_full_use_full_literature_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                for mode in (PILOT_50_LAUNCH_MODE, PILOT_1000_LAUNCH_MODE, FULL_LAUNCH_MODE):
                    cfg = build_launch_config(mode, dry_run=True, env=env)
                    self.assertEqual(taxonomy_scope_label(cfg), "FULL")
                    self.assertEqual(cfg.selected_subcategories, [])
                    self.assertEqual(cfg.selected_sub_subcategories, [])
                    dry = build_workflow_dry_run(cfg)
                    self.assertEqual(dry["taxonomy_scope"], "FULL")
                    self.assertEqual(dry["taxonomy_restriction"], "NONE")
                    self.assertEqual(dry["canonical_taxonomy"]["total_taxonomy_nodes"], 433)
                    self.assertEqual(dry["canonical_taxonomy"]["level_4_nodes"], 299)
                    self.assertEqual(dry["literature_taxonomy"], "canonical")


class WebCanonicalTaxonomyTests(unittest.TestCase):
    def test_tavily_scope_covers_all_searchable_level4_nodes(self) -> None:
        tax = get_decarbonization_taxonomy()
        nodes = searchable_web_nodes(tax)
        l4 = {n.path for n in tax.nodes_at(4)}
        searched_l4 = {n.path for n in nodes if n.level == 4}
        self.assertEqual(searched_l4, l4)
        queries = plan_canonical_web_queries(web_limits(queries_per_sub_subcategory=1))
        covered = {q.get("taxonomy_path") for q in queries}
        self.assertTrue(l4 <= covered)
        self.assertGreaterEqual(len(queries), 299)

    def test_web_queries_span_level1_and_use_aliases_or_context(self) -> None:
        queries = plan_canonical_web_queries(web_limits(queries_per_sub_subcategory=1))
        l1 = {q.get("taxonomy_level_1") for q in queries}
        self.assertGreaterEqual(len(l1), 7)
        self.assertNotEqual(l1, {"Cementitious Materials"})
        joined = " ".join(q["query_text"] for q in queries).casefold()
        self.assertIn("ordinary portland", joined)
        self.assertIn("decarbonization", joined)
        self.assertTrue("buy clean" in joined or "procurement" in joined)
        slugs = {q.get("web_search_node_slug") or q.get("sub_subcategory_slug") for q in queries}
        self.assertGreater(len(slugs), 1)
        self.assertFalse(slugs <= {"chemical_absorption", "amine_absorption"})

    def test_web_coverage_manifest_has_one_entry_per_level4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "metadata").mkdir(parents=True)
            (root / "all_records").mkdir()
            nodes = [
                {
                    "path": n.path,
                    "path_labels": list(n.path_labels),
                    "slug": n.slug,
                    "label": n.label,
                    "level": n.level,
                    "level_1": n.path_labels[1],
                    "aliases": list(n.aliases),
                }
                for n in get_decarbonization_taxonomy().nodes_at(4)
            ]
            queries = [
                {
                    "query_id": f"wq_{i:05d}",
                    "taxonomy_path": n["path"],
                    "query_text": f"{n['label']} cement concrete decarbonization",
                    "sub_subcategory_slug": n["slug"],
                }
                for i, n in enumerate(nodes)
            ]
            write_web_search_scope_manifest(root, queries=queries, scope="canonical", nodes=nodes)
            write_json(root / "metadata" / "web_queries.json", queries)
            write_jsonl(root / "metadata" / "web_search_results_raw.jsonl", [])
            write_jsonl(root / "metadata" / "web_records_raw.jsonl", [])
            write_jsonl(root / "metadata" / "web_screening_results.jsonl", [])
            write_json(root / "metadata" / "web_search_merge_summary.json", {})
            write_json(root / "metadata" / "web_extraction_merge_summary.json", {})
            with (root / "all_records" / "cementitious_materials_all_records.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS))
                writer.writeheader()
            coverage = build_retrieval_coverage_manifest(root)
            l4_entries = [n for n in coverage["per_searched_node"] if n.get("level") == 4]
            self.assertEqual(len(l4_entries), 299)
            self.assertTrue(all(n.get("query_count", n.get("web_queries")) == 1 for n in l4_entries))


class HierarchicalExportEveryNodeTests(unittest.TestCase):
    def test_every_taxonomy_node_gets_csv_including_zero_row_level4(self) -> None:
        tax = get_decarbonization_taxonomy()
        rows = [
            record_for_path(
                (
                    "Concrete Decarbonization",
                    "Cementitious Materials",
                    "Cement-Plant Carbon Capture",
                    "Chemical Absorption",
                    "Amine Absorption",
                ),
                record_id="amine-1",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_hierarchical_export(root, rows, fieldnames=RECORD_FIELDS)
            export = root / DECARBONIZATION_EXPORT_DIRNAME
            missing = []
            for node in tax.ordered_nodes():
                if node.level == 0:
                    path = export / "concrete_decarbonization.csv"
                elif node.level == 4:
                    path = export.joinpath(*node.path_slugs[1:-1]) / node.csv_filename(
                        parent_slug=node.parent_slug
                    )
                else:
                    path = export.joinpath(*node.path_slugs[1:]) / f"{node.slug}.csv"
                if not path.is_file():
                    missing.append(str(path))
            self.assertEqual(missing[:5], [])
            self.assertEqual(len(missing), 0)
            amine = (
                export
                / "cementitious_materials"
                / "cement_plant_carbon_capture"
                / "chemical_absorption"
                / "amine_absorption.csv"
            )
            self.assertTrue(amine.is_file())
            self.assertTrue(amine.parent.is_dir())
            self.assertFalse((amine.parent / "amine_absorption").is_dir())
            empty = (
                export
                / "policy"
                / "green_public_procurement"
                / "embodied_carbon_procurement_limits"
                / "buy_clean_programs.csv"
            )
            self.assertTrue(empty.is_file())
            with empty.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(list(reader.fieldnames or []), list(RECORD_FIELDS))
                self.assertEqual(list(reader), [])
            manifest = json.loads((root / TAXONOMY_EXPORT_MANIFEST_REL).read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_csvs_generated"], tax.count())
            zero_l4 = [n for n in manifest["nodes"] if n["level"] == 4 and n["zero_records"]]
            self.assertTrue(zero_l4)
            self.assertTrue(all(n["csv_emitted"] is True for n in zero_l4))
            self.assertTrue(all(n["csv_path"] for n in zero_l4))
            master_ids = {
                r["record_id"]
                for r in csv.DictReader(
                    (export / "concrete_decarbonization.csv").open(encoding="utf-8", newline="")
                )
            }
            l1_ids = {
                r["record_id"]
                for r in csv.DictReader(
                    (export / "cementitious_materials" / "cementitious_materials.csv").open(
                        encoding="utf-8", newline=""
                    )
                )
            }
            self.assertTrue(l1_ids <= master_ids)

    def test_pilot_coverage_report_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            meta = root / "metadata"
            meta.mkdir()
            write_hierarchical_export(
                root,
                [canonical_record(record_id="amine-cov")],
                fieldnames=RECORD_FIELDS,
            )
            nodes = [
                {
                    "path": n.path,
                    "path_labels": list(n.path_labels),
                    "slug": n.slug,
                    "label": n.label,
                    "level": 4,
                    "level_1": n.path_labels[1],
                    "aliases": list(n.aliases),
                }
                for n in get_decarbonization_taxonomy().nodes_at(4)
            ]
            queries = [
                {
                    "taxonomy_path": n["path"],
                    "query_text": n["label"],
                    "sub_subcategory_slug": n["slug"],
                }
                for n in nodes
            ]
            write_web_search_scope_manifest(root, queries=queries, scope="canonical", nodes=nodes)
            write_json(meta / "web_queries.json", queries)
            write_jsonl(meta / "web_search_results_raw.jsonl", [])
            write_jsonl(meta / "web_records_raw.jsonl", [])
            write_jsonl(meta / "web_screening_results.jsonl", [])
            write_json(meta / "web_search_merge_summary.json", {})
            write_json(meta / "web_extraction_merge_summary.json", {})
            (root / "all_records").mkdir()
            with (root / "all_records" / "cementitious_materials_all_records.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS))
                writer.writeheader()
                writer.writerow(canonical_record(record_id="amine-cov"))
            coverage = build_retrieval_coverage_manifest(root)
            report = write_taxonomy_coverage_report(root, retrieval_coverage=coverage)
            self.assertEqual(len(report["level_4"]), 299)
            self.assertEqual(len(report["level_1"]), 7)
            self.assertTrue((meta / "taxonomy_coverage_report.json").is_file())
            self.assertIn("level_4_zero_final_records", report["summary"])

    def test_no_live_api_calls_in_this_module(self) -> None:
        with mock.patch("pipeline.openai_client.call_openai") as openai:
            with mock.patch("pipeline.cementitious.web_tavily.tavily_search") as tavily:
                screen_records(
                    [paper_record(0, title="Buy Clean programs", abstract="Green public procurement cement")],
                    taxonomy=get_taxonomy(),
                    keyword_only=True,
                )
                plan_web_queries(get_taxonomy(), web_limits(queries_per_sub_subcategory=1))
        openai.assert_not_called()
        tavily.assert_not_called()


if __name__ == "__main__":
    unittest.main()
