#!/usr/bin/env python3
"""Focused tests: full-mode literature+web retrieval across the canonical taxonomy."""

from __future__ import annotations

import csv
import json
import os
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.dedupe import deduplicate_records, exact_duplicate_key
from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy
from pipeline.cementitious.hierarchical_export import write_hierarchical_export
from pipeline.cementitious.schema import RECORD_FIELDS, normalize_record
from pipeline.cementitious.source_classification import (
    SOURCE_TYPE_ACADEMIC_LITERATURE,
    SOURCE_TYPE_COMPANY,
    SOURCE_TYPE_GOVERNMENT,
    authority_rank_for_source_type,
)
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.cementitious.web_config import WebLimits
from pipeline.cementitious.web_queries import plan_canonical_web_queries, plan_web_queries
from pipeline.cementitious.web_scope import (
    WEB_SEARCH_SCOPE_CANONICAL,
    build_retrieval_coverage_manifest,
    node_search_role,
    resolve_web_search_scope,
    searchable_web_nodes,
    stamp_search_intent_taxonomy,
)
from pipeline.cementitious.web_stages import merge_literature_and_web, plan_web_query_shards
from pipeline.cementitious.workflow_launch import (
    PILOT_WEB_LEAF,
    build_launch_config,
    validate_launch_config,
    web_search_node_summaries_for_launch,
)


def _env(tmp: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    pkl = tmp / "corpus.pkl"
    with pkl.open("wb") as handle:
        pickle.dump([{"title": "t", "abstract": "a", "doi": "10.1/x"}], handle)
    base = {
        "OPENAI_API_KEY": "sk-test-not-real",
        "TAVILY_API_KEY": "tvly-test-not-real",
        "PICKLE_PATH": str(pkl),
        "RESULTS_ROOT": str(tmp / "results"),
    }
    if extra:
        base.update(extra)
    return base


def _limits(**overrides) -> WebLimits:
    payload = dict(
        queries_per_subcategory=1,
        queries_per_sub_subcategory=2,
        results_per_query=3,
        max_urls_per_branch=50,
        max_total_urls=100,
        max_total_queries=0,
        search_shard_size=10,
        extract_shard_size=10,
        concurrency=2,
        request_timeout=5,
        max_retries=1,
        page_max_chars=5000,
        rate_limit_sleep_s=0.0,
    )
    payload.update(overrides)
    return WebLimits(**payload)


class FullModeLiteratureAndWebTests(unittest.TestCase):
    def test_full_mode_enables_both_literature_and_web(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True)
            self.assertEqual(cfg.run_mode, "literature-and-web")
            self.assertTrue(cfg.literature_enabled)
            self.assertTrue(cfg.web_enabled)
            self.assertEqual(cfg.web_search_scope, WEB_SEARCH_SCOPE_CANONICAL)
            self.assertIsNone(cfg.max_records)
            errors = validate_launch_config(cfg, environ=env)
            self.assertEqual(errors, [])

    def test_full_mode_does_not_restrict_web_to_chemical_absorption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True)
            nodes = web_search_node_summaries_for_launch(cfg)
            slugs = {n["slug"] for n in nodes}
            self.assertNotEqual(slugs, {PILOT_WEB_LEAF})
            self.assertGreater(len(nodes), 50)
            l1 = {n.get("level_1") for n in nodes}
            self.assertIn("Cementitious Materials", l1)
            self.assertIn("Aggregate Procurement", l1)
            self.assertIn("Policy", l1)
            self.assertTrue(
                any(n.get("slug") not in {PILOT_WEB_LEAF, "amine_absorption"} for n in nodes)
            )


class CanonicalWebScopeTests(unittest.TestCase):
    def test_web_scope_is_derived_from_canonical_taxonomy(self) -> None:
        tax = get_decarbonization_taxonomy()
        nodes = searchable_web_nodes(tax)
        self.assertTrue(nodes)
        self.assertTrue(all(n.level in {3, 4} for n in nodes))
        self.assertTrue(all(node_search_role(n) == "searchable_technology" for n in nodes))
        organizational = [n for n in tax.ordered_nodes() if n.level in {0, 1, 2}]
        self.assertTrue(organizational)
        org_paths = {n.path for n in organizational}
        self.assertTrue(org_paths.isdisjoint({n.path for n in nodes}))
        parent_l3 = [n for n in tax.nodes_at(3) if n.children_slugs]
        self.assertTrue(parent_l3)
        self.assertTrue({n.path for n in parent_l3}.isdisjoint({n.path for n in nodes}))
        l1 = {n.path_labels[1] for n in nodes if len(n.path_labels) > 1}
        self.assertGreaterEqual(len(l1), 5)
        from pipeline.cementitious.web_queries import _templates_for_decarb_node

        plc = next(
            n
            for n in tax.ordered_nodes()
            if "PLC" in n.aliases or n.slug.startswith("portland_limestone")
        )
        texts = " ".join(t for _qt, t in _templates_for_decarb_node(plc)).casefold()
        self.assertTrue("plc" in texts or "type il" in texts)
        queries = plan_canonical_web_queries(_limits(queries_per_sub_subcategory=1, max_total_queries=40))
        self.assertTrue(queries)
        q_l1 = {q.get("taxonomy_level_1") for q in queries}
        self.assertIn("Cementitious Materials", q_l1)
        self.assertGreaterEqual(len(q_l1), 2)

    def test_auto_scope_uses_runtime_only_when_selection_is_set(self) -> None:
        self.assertEqual(
            resolve_web_search_scope(selected_sub_subcategories=["chemical_absorption"]),
            "runtime",
        )
        self.assertEqual(resolve_web_search_scope(), WEB_SEARCH_SCOPE_CANONICAL)
        queries = plan_web_queries(
            get_taxonomy(),
            _limits(queries_per_sub_subcategory=2),
            selected_sub_subcategories=["chemical_absorption"],
        )
        self.assertTrue(queries)
        self.assertTrue(all(q["sub_subcategory_slug"] == "chemical_absorption" for q in queries))
        self.assertTrue(all(q.get("taxonomy_level_0") for q in queries))


class TaxonomyColumnAndProvenanceTests(unittest.TestCase):
    def test_literature_and_web_share_taxonomy_columns_and_provenance(self) -> None:
        lit = normalize_record(
            {
                "record_id": "lit-rca",
                "evidence_origin": "Literature",
                "source_type": "Academic Literature",
                "source_id": "10.1000/lit-rca",
                "source_title": "RCA paper",
                "canonical_technology_name": "Recycled Concrete Aggregate",
                "taxonomy_level_0": "Concrete Decarbonization",
                "taxonomy_level_1": "Aggregate Procurement",
                "taxonomy_level_2": "Recycled Concrete Aggregates",
                "taxonomy_level_3": "Treated RCA",
                "taxonomy_level_4": "N.A.",
                "project_name": "Plant A",
                "evidence_text": "literature evidence for treated RCA",
            }
        )
        web_raw = {
            "record_id": "web-rca",
            "evidence_origin": "Web",
            "source_type": "Company Website",
            "source_url": "https://company.example/rca",
            "source_title": "Company RCA project",
            "organization_or_publisher": "company.example",
            "retrieval_timestamp": "2026-08-13T00:00:00+00:00",
            "canonical_technology_name": "Recycled Concrete Aggregate",
            "taxonomy_level_0": "Concrete Decarbonization",
            "taxonomy_level_1": "Aggregate Procurement",
            "taxonomy_level_2": "Recycled Concrete Aggregates",
            "taxonomy_level_3": "Treated RCA",
            "taxonomy_level_4": "N.A.",
            "project_name": "Plant A",
            "evidence_text": "company webpage treated RCA",
        }
        stamp_search_intent_taxonomy(web_raw, web_raw)
        web = normalize_record(web_raw)
        for col in (
            "taxonomy_level_0",
            "taxonomy_level_1",
            "taxonomy_level_2",
            "taxonomy_level_3",
            "taxonomy_level_4",
        ):
            self.assertEqual(lit[col], web[col])
            self.assertIn(col, RECORD_FIELDS)
        self.assertEqual(lit["evidence_origin"], "Literature")
        self.assertEqual(web["evidence_origin"], "Web")
        self.assertEqual(web["source_url"], "https://company.example/rca")
        self.assertEqual(web["source_title"], "Company RCA project")
        self.assertTrue(web.get("retrieval_timestamp"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "7-30 results"
            (out / "metadata").mkdir(parents=True)
            (out / "checkpoints").mkdir(parents=True)
            (out / "metadata" / "literature_records_raw.jsonl").write_text(
                json.dumps(lit) + "\n", encoding="utf-8"
            )
            (out / "metadata" / "web_records_raw.jsonl").write_text(
                json.dumps(web) + "\n", encoding="utf-8"
            )
            summary = merge_literature_and_web(output_dir=out)
            self.assertEqual(summary["literature_records"], 1)
            self.assertEqual(summary["web_records"], 1)
            combined = [
                json.loads(line)
                for line in (out / "metadata" / "combined_records_pre_dedupe.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            self.assertEqual(len(combined), 2)
            origins = {r["evidence_origin"] for r in combined}
            self.assertEqual(origins, {"Literature", "Web"})
            for row in combined:
                self.assertEqual(row["taxonomy_level_1"], "Aggregate Procurement")
                self.assertEqual(row["evidence_origin"] in {"Literature", "Web"}, True)


class TavilyPreflightTests(unittest.TestCase):
    def test_missing_tavily_key_fails_when_web_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            env.pop("TAVILY_API_KEY", None)
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("TAVILY_API_KEY", None)
                cfg = build_launch_config("full", dry_run=True)
            errors = validate_launch_config(cfg, environ={k: v for k, v in env.items() if k != "TAVILY_API_KEY"})
            self.assertTrue(any("TAVILY_API_KEY" in e for e in errors))
            self.assertEqual(cfg.run_mode, "literature-and-web")
            self.assertTrue(cfg.web_enabled)

    def test_explicit_web_disable_skips_tavily_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp), extra={"WEB_SEARCH_ENABLED": "0", "RUN_MODE": "literature-only"})
            env.pop("TAVILY_API_KEY", None)
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("TAVILY_API_KEY", None)
                cfg = build_launch_config("full", dry_run=True, env=env)
            self.assertEqual(cfg.run_mode, "literature-only")
            self.assertFalse(cfg.web_enabled)
            self.assertTrue(cfg.literature_enabled)
            errors = validate_launch_config(cfg, environ={k: v for k, v in env.items() if k != "TAVILY_API_KEY"})
            self.assertFalse(any("TAVILY_API_KEY" in e for e in errors))


class DedupeGranularityTests(unittest.TestCase):
    def test_distinct_projects_same_company_are_not_collapsed(self) -> None:
        shared = {
            "evidence_origin": "Web",
            "source_type": "Company Website",
            "canonical_technology_name": "Chemical Absorption",
            "company_or_organization": "Acme Capture",
            "taxonomy_level_0": "Concrete Decarbonization",
            "taxonomy_level_1": "Cementitious Materials",
            "taxonomy_level_2": "Cement-Plant Carbon Capture",
            "taxonomy_level_3": "Chemical Absorption",
            "taxonomy_level_4": "Amine Absorption",
            "subcategory_slug": "cement_plant_carbon_capture",
            "sub_subcategory_slug": "chemical_absorption",
            "evidence_text": "deployment evidence",
        }
        a = normalize_record(
            {
                **shared,
                "record_id": "proj-a",
                "project_name": "Plant A amine unit",
                "location": "Norway",
                "source_url": "https://acme.example/plant-a",
            }
        )
        b = normalize_record(
            {
                **shared,
                "record_id": "proj-b",
                "project_name": "Plant B amine unit",
                "location": "Texas",
                "source_url": "https://acme.example/plant-b",
            }
        )
        self.assertNotEqual(exact_duplicate_key(a), exact_duplicate_key(b))
        kept, _audit = deduplicate_records([a, b])
        self.assertEqual(len(kept), 2)
        names = {r.get("project_name") for r in kept}
        self.assertEqual(names, {"Plant A amine unit", "Plant B amine unit"})


class HierarchicalWebExportTests(unittest.TestCase):
    def test_web_records_appear_in_hierarchical_csvs(self) -> None:
        web = normalize_record(
            {
                "record_id": "web-hier-1",
                "evidence_origin": "Web",
                "source_type": "Company Website",
                "source_url": "https://company.example/rca-project",
                "source_title": "RCA project page",
                "retrieval_timestamp": "2026-08-13T00:00:00+00:00",
                "canonical_technology_name": "Treated RCA",
                "taxonomy_level_0": "Concrete Decarbonization",
                "taxonomy_level_1": "Aggregate Procurement",
                "taxonomy_level_2": "Recycled Concrete Aggregates",
                "taxonomy_level_3": "Treated RCA",
                "taxonomy_level_4": "N.A.",
                "evidence_text": "web evidence for treated recycled concrete aggregate.",
                "extraction_confidence": "High",
                "taxonomy_confidence": "High",
                "classification_basis": "Web search intent",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            root.mkdir()
            result = write_hierarchical_export(root, [web])
            self.assertTrue(result["ok"])
            l1 = (
                root
                / "concrete_decarbonization_results"
                / "aggregate_procurement"
                / "aggregate_procurement.csv"
            )
            self.assertTrue(l1.is_file())
            text = l1.read_text(encoding="utf-8")
            self.assertIn("Web", text)
            self.assertIn("company.example", text)
            self.assertIn("web-hier-1", text)


class ManifestCoverageTests(unittest.TestCase):
    def test_manifest_summarizes_literature_vs_web_and_searched_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "7-30 results"
            meta = out / "metadata"
            meta.mkdir(parents=True)
            (out / "all_records").mkdir(parents=True)
            plan = plan_web_query_shards(
                output_dir=out,
                limits=_limits(queries_per_sub_subcategory=1, max_total_queries=12),
                selected_subcategories=None,
                selected_sub_subcategories=None,
            )
            self.assertEqual(plan["web_search_scope"], "canonical")
            self.assertGreater(plan["searched_node_count"], 10)
            scope = json.loads((meta / "web_search_scope.json").read_text(encoding="utf-8"))
            self.assertFalse(scope.get("restricted_to_chemical_absorption"))
            self.assertGreaterEqual(len(scope.get("level_1_branches_searched") or []), 2)
            queries = json.loads((meta / "web_queries.json").read_text(encoding="utf-8"))
            self.assertTrue(any("plc" in q["query_text"].casefold() or "alias" in q or q.get("aliases_used") for q in queries) or queries)

            lit = normalize_record(
                {
                    "record_id": "m-lit",
                    "evidence_origin": "Literature",
                    "source_type": "Academic Literature",
                    "taxonomy_level_0": "Concrete Decarbonization",
                    "taxonomy_level_1": "Cementitious Materials",
                    "taxonomy_level_2": "Cement-Plant Carbon Capture",
                    "taxonomy_level_3": "Chemical Absorption",
                    "taxonomy_level_4": "Amine Absorption",
                    "evidence_text": "lit",
                    "source_id": "doi:1",
                }
            )
            web = normalize_record(
                {
                    "record_id": "m-web",
                    "evidence_origin": "Web",
                    "source_type": "Company Website",
                    "source_url": "https://example.com/x",
                    "taxonomy_level_0": "Concrete Decarbonization",
                    "taxonomy_level_1": "Aggregate Procurement",
                    "taxonomy_level_2": "Recycled Concrete Aggregates",
                    "taxonomy_level_3": "Treated RCA",
                    "taxonomy_level_4": "N.A.",
                    "evidence_text": "web",
                }
            )
            with (out / "all_records" / "cementitious_materials_all_records.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                writer.writerow(lit)
                writer.writerow(web)
            coverage = build_retrieval_coverage_manifest(out)
            self.assertEqual(coverage["totals"]["literature_final_records"], 1)
            self.assertEqual(coverage["totals"]["web_final_records"], 1)
            self.assertIn("Literature", coverage["totals_by_evidence_origin"])
            self.assertIn("Web", coverage["totals_by_evidence_origin"])
            self.assertTrue(coverage["per_searched_node"])
            self.assertIn("nodes_with_zero_web_results", coverage)

    def test_authority_rank_is_explicit(self) -> None:
        self.assertEqual(authority_rank_for_source_type(SOURCE_TYPE_ACADEMIC_LITERATURE), 1)
        self.assertEqual(authority_rank_for_source_type(SOURCE_TYPE_GOVERNMENT), 2)
        self.assertEqual(authority_rank_for_source_type(SOURCE_TYPE_COMPANY), 5)
        self.assertGreater(
            authority_rank_for_source_type("Other Web Source"),
            authority_rank_for_source_type(SOURCE_TYPE_ACADEMIC_LITERATURE),
        )


if __name__ == "__main__":
    unittest.main()
