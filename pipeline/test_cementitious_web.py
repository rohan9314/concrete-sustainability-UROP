#!/usr/bin/env python3
"""Unit tests for Cementitious Materials web search workflow (mocked Tavily; no live APIs)."""

from __future__ import annotations

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

os.environ.setdefault(
    "TAXONOMY_PATH",
    str(REPO_ROOT / "config" / "cementitious_materials_taxonomy.json"),
)

from pipeline.cementitious.dedupe import deduplicate_records, exact_duplicate_key
from pipeline.cementitious.export_partitions import export_taxonomy_partitions
from pipeline.cementitious.schema import normalize_record
from pipeline.cementitious.shard_io import read_jsonl
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.cementitious.web_config import WebLimits, load_web_limits
from pipeline.cementitious.web_queries import plan_web_queries
from pipeline.cementitious.web_stages import (
    WebShardError,
    _screen_web_result,
    merge_literature_and_web,
    merge_web_extractions,
    merge_web_search,
    missing_web_extraction_shards,
    missing_web_search_shards,
    plan_web_extraction,
    plan_web_query_shards,
    web_extract_shard,
    web_search_shard,
)
from pipeline.cementitious.web_tavily import extract_page_text, get_tavily_api_key
from pipeline.cementitious.web_url import normalize_url
from pipeline.cementitious.export_partitions import write_csv
from pipeline.cementitious.schema import RECORD_FIELDS


class FakeTavilyClient:
    calls: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    def search(self, query: str, max_results: int = 10, include_raw_content: bool = True):
        FakeTavilyClient.calls.append(query)
        return {
            "results": [
                {
                    "title": f"Cement plant {query[:40]}",
                    "url": f"https://example.com/projects/{len(FakeTavilyClient.calls)}?utm_source=x#frag",
                    "content": "Cement kiln amine solvent CO2 capture pilot deployment.",
                    "raw_content": "Full page body about cement plant chemical absorption carbon capture.",
                    "score": 0.9,
                },
                {
                    "title": "Duplicate tracking URL",
                    "url": f"https://www.example.com/projects/{len(FakeTavilyClient.calls)}",
                    "content": "Same page mirrored.",
                    "raw_content": "",
                    "score": 0.5,
                },
            ][:max_results]
        }


def _web_limits(**overrides) -> WebLimits:
    base = dict(
        queries_per_subcategory=3,
        queries_per_sub_subcategory=2,
        results_per_query=3,
        max_urls_per_branch=50,
        max_total_urls=100,
        search_shard_size=2,
        extract_shard_size=2,
        concurrency=2,
        request_timeout=5,
        max_retries=1,
        page_max_chars=5000,
    )
    base.update(overrides)
    return WebLimits(**base)


class TestWebUrlNormalize(unittest.TestCase):
    def test_strips_tracking_and_fragments(self):
        a = normalize_url("https://WWW.Example.com/path/?utm_source=x&id=1#section")
        b = normalize_url("https://example.com/path?id=1")
        self.assertEqual(a, b)


class TestWebQueryPlanner(unittest.TestCase):
    def test_selected_sub_subcategory_only(self):
        tax = get_taxonomy()
        queries = plan_web_queries(
            tax,
            _web_limits(queries_per_sub_subcategory=5),
            selected_sub_subcategories=["chemical_absorption"],
        )
        self.assertTrue(queries)
        self.assertTrue(all(q["sub_subcategory_slug"] == "chemical_absorption" for q in queries))
        self.assertTrue(all(q.get("query_scope") == "sub_subcategory" for q in queries))
        joined = " ".join(q["query_text"].casefold() for q in queries)
        self.assertIn("chemical", joined)
        self.assertNotIn("biomass ash", joined)
        self.assertNotIn("alkali-activated", joined)

    def test_selected_subcategory_emits_overview_and_child_queries(self):
        tax = get_taxonomy()
        queries = plan_web_queries(
            tax,
            _web_limits(queries_per_subcategory=3, queries_per_sub_subcategory=2),
            selected_subcategories=["cement_plant_carbon_capture"],
        )
        scopes = {q.get("query_scope") for q in queries}
        self.assertIn("subcategory", scopes)
        self.assertIn("sub_subcategory", scopes)
        overview = [q for q in queries if q.get("query_scope") == "subcategory"]
        self.assertGreaterEqual(len(overview), 1)
        self.assertLessEqual(len(overview), 3)
        self.assertTrue(all(q["subcategory_slug"] == "cement_plant_carbon_capture" for q in overview))
        self.assertTrue(all(not q["sub_subcategory_slug"] for q in overview))
        child = [q for q in queries if q.get("query_scope") == "sub_subcategory"]
        self.assertTrue(child)
        self.assertTrue(
            all(q["subcategory_slug"] == "cement_plant_carbon_capture" for q in child)
        )
        # Must not spill into unrelated branches
        self.assertTrue(all("biomass" not in q["sub_subcategory_slug"] for q in child))

    def test_uses_synonyms(self):
        tax = get_taxonomy()
        node = tax.sub_subcategories["chemical_absorption"]
        syn = (node.representative_synonyms or ["amine"])[0]
        queries = plan_web_queries(
            tax,
            _web_limits(queries_per_sub_subcategory=8),
            selected_sub_subcategories=["chemical_absorption"],
        )
        joined = " ".join(q["query_text"].casefold() for q in queries)
        self.assertTrue(syn.casefold() in joined or "chemical absorption" in joined)

    def test_query_limits_enforced(self):
        tax = get_taxonomy()
        queries = plan_web_queries(
            tax,
            _web_limits(queries_per_sub_subcategory=2),
            selected_sub_subcategories=["chemical_absorption"],
        )
        self.assertLessEqual(len(queries), 2)

    def test_subcategory_limit_enforced(self):
        tax = get_taxonomy()
        queries = plan_web_queries(
            tax,
            _web_limits(queries_per_subcategory=2, queries_per_sub_subcategory=0),
            selected_subcategories=["cement_plant_carbon_capture"],
        )
        overview = [q for q in queries if q.get("query_scope") == "subcategory"]
        self.assertEqual(len(overview), 2)
        self.assertTrue(all(not q["sub_subcategory_slug"] for q in overview))


class TestWebSearchShards(unittest.TestCase):
    def setUp(self):
        FakeTavilyClient.calls = []
        self._tmpdir = tempfile.TemporaryDirectory()
        self.out = Path(self._tmpdir.name) / "7-30 results"
        self.out.mkdir(parents=True)
        os.environ["TAVILY_API_KEY"] = "test-key-not-real"
        os.environ["WEB_SEARCH_SHARD_SIZE"] = "2"
        os.environ["WEB_QUERIES_PER_SUB_SUBCATEGORY"] = "4"
        os.environ["WEB_RESULTS_PER_QUERY"] = "3"

    def tearDown(self):
        self._tmpdir.cleanup()
        FakeTavilyClient.calls = []

    def test_search_shards_disjoint_and_separate_outputs(self):
        plan = plan_web_query_shards(
            output_dir=self.out,
            limits=_web_limits(search_shard_size=2, queries_per_sub_subcategory=4),
            selected_sub_subcategories=["chemical_absorption"],
        )
        self.assertGreaterEqual(plan["shard_count"], 1)
        shards = json.loads((self.out / "metadata" / "web_query_shards.json").read_text())
        all_qids = []
        with mock.patch(
            "pipeline.cementitious.web_stages.get_tavily_client",
            return_value=FakeTavilyClient(),
        ):
            for entry in shards:
                web_search_shard(
                    shard_id=int(entry["shard_id"]),
                    output_dir=self.out,
                    limits=_web_limits(results_per_query=2, search_shard_size=2),
                )
                all_qids.extend(entry["query_ids"])
                outp = Path(entry["expected_output_path"])
                self.assertTrue(outp.is_file())
                self.assertTrue(Path(entry["expected_marker_path"]).is_file())
                rows = read_jsonl(outp)
                for row in rows:
                    self.assertEqual(int(row["shard_id"]), int(entry["shard_id"]))
                    self.assertIn(row["query_id"], entry["query_ids"])
        self.assertEqual(len(all_qids), len(set(all_qids)))
        # Separate output files
        outs = [Path(e["expected_output_path"]) for e in shards]
        self.assertEqual(len(outs), len(set(outs)))

    def test_merge_fails_when_shard_missing(self):
        plan_web_query_shards(
            output_dir=self.out,
            limits=_web_limits(search_shard_size=1, queries_per_sub_subcategory=2),
            selected_sub_subcategories=["chemical_absorption"],
        )
        with self.assertRaises(WebShardError):
            merge_web_search(output_dir=self.out)

    def test_url_dedupe_and_query_provenance(self):
        plan_web_query_shards(
            output_dir=self.out,
            limits=_web_limits(search_shard_size=10, queries_per_sub_subcategory=2),
            selected_sub_subcategories=["chemical_absorption"],
        )
        shards = json.loads((self.out / "metadata" / "web_query_shards.json").read_text())
        with mock.patch(
            "pipeline.cementitious.web_stages.get_tavily_client",
            return_value=FakeTavilyClient(),
        ):
            for entry in shards:
                web_search_shard(shard_id=int(entry["shard_id"]), output_dir=self.out)
        summary = merge_web_search(output_dir=self.out)
        self.assertGreater(summary["raw_result_count"], 0)
        self.assertGreaterEqual(summary["duplicate_url_count"], 0)
        qmap = read_jsonl(self.out / "metadata" / "web_url_query_map.jsonl")
        self.assertTrue(qmap)
        deduped = read_jsonl(self.out / "metadata" / "web_search_results_deduplicated.jsonl")
        for row in deduped:
            self.assertTrue(row.get("query_ids"))


class TestWebScreening(unittest.TestCase):
    def test_rejects_unrelated_industry(self):
        decision = _screen_web_result(
            {
                "title": "Steel mill amine capture project",
                "snippet": "CO2 capture at a steel mill natural gas processing site",
                "url": "https://news.example/steel",
                "domain": "news.example",
                "sub_subcategory_slug": "chemical_absorption",
            }
        )
        self.assertEqual(decision["relevance_decision"], "irrelevant")

    def test_biomass_fuel_vs_ash(self):
        decision = _screen_web_result(
            {
                "title": "Biomass as kiln alternative fuel",
                "snippet": "Using biomass kiln fuel and RDF co-processing fuel in cement kilns",
                "url": "https://example.com/fuel",
                "domain": "example.com",
                "sub_subcategory_slug": "biomass_ashes",
            }
        )
        self.assertEqual(decision["relevance_decision"], "irrelevant")


class TestPageRetrievalFallback(unittest.TestCase):
    def test_snippet_fallback_marked(self):
        text, source = extract_page_text(
            tavily_raw_content="",
            snippet="Short snippet text",
            page_max_chars=1000,
            allow_http_fetch=False,
        )
        self.assertEqual(source, "Tavily Snippet")
        self.assertIn("snippet", text.casefold())

    def test_http_fetch_used_when_tavily_raw_missing(self):
        def fake_fetch(url, timeout=30, page_max_chars=50000):
            return (
                "Full HTML body about cement plant chemical absorption carbon capture.",
                {"ok": True, "status_code": 200, "error": "", "final_url": url},
            )

        text, source = extract_page_text(
            tavily_raw_content="",
            snippet="tiny",
            page_max_chars=5000,
            url="https://example.com/chem-abs",
            allow_http_fetch=True,
            http_fetcher=fake_fetch,
        )
        self.assertEqual(source, "HTTP Page Fetch")
        self.assertIn("chemical absorption", text.casefold())

    def test_prefers_tavily_raw_over_http(self):
        def boom(*args, **kwargs):
            raise AssertionError("HTTP fetch should not run when Tavily raw exists")

        text, source = extract_page_text(
            tavily_raw_content="Tavily raw page body",
            snippet="snip",
            page_max_chars=5000,
            url="https://example.com/x",
            http_fetcher=boom,
        )
        self.assertEqual(source, "Tavily Raw Content")
        self.assertIn("Tavily raw", text)


class TestWebExtraction(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.out = Path(self._tmpdir.name) / "7-30 results"
        self.out.mkdir(parents=True)
        os.environ["TAVILY_API_KEY"] = "test-key-not-real"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _prepare_ranked(self, n: int = 3):
        plan_web_query_shards(
            output_dir=self.out,
            limits=_web_limits(search_shard_size=10, queries_per_sub_subcategory=2),
            selected_sub_subcategories=["chemical_absorption"],
        )
        shards = json.loads((self.out / "metadata" / "web_query_shards.json").read_text())
        with mock.patch(
            "pipeline.cementitious.web_stages.get_tavily_client",
            return_value=FakeTavilyClient(),
        ):
            for entry in shards:
                web_search_shard(shard_id=int(entry["shard_id"]), output_dir=self.out)
        merge_web_search(output_dir=self.out)
        plan_web_extraction(output_dir=self.out, limits=_web_limits(extract_shard_size=2))
        ranked = read_jsonl(self.out / "metadata" / "web_ranked_sources.jsonl")
        self.assertTrue(ranked)
        return ranked[:n]

    def test_extract_shards_disjoint_no_final_partitions(self):
        self._prepare_ranked()
        shards = json.loads((self.out / "metadata" / "web_extraction_shards.json").read_text())
        self.assertTrue(shards)
        seen = set()
        for entry in shards:
            result = web_extract_shard(
                shard_id=int(entry["shard_id"]),
                output_dir=self.out,
                keyword_only=True,
                limits=_web_limits(extract_shard_size=2),
            )
            self.assertIn("extracted_count", result)
            self.assertEqual(int(result["shard_id"]), int(entry["shard_id"]))
            for wid in entry["web_source_ids"]:
                self.assertNotIn(wid, seen)
                seen.add(wid)
            self.assertTrue(Path(entry["expected_output_path"]).is_file())
            self.assertFalse((self.out / "checkpoints" / "export.complete").is_file())
            self.assertFalse((self.out / "all_records" / "cementitious_materials_all_records.csv").is_file())

    def test_merge_fails_when_extract_shard_missing(self):
        self._prepare_ranked()
        with self.assertRaises(WebShardError):
            merge_web_extractions(output_dir=self.out)

    def test_failed_fetches_logged_and_urls_preserved(self):
        self._prepare_ranked()
        # Force snippet-only / unavailable for one source via patch
        shards = json.loads((self.out / "metadata" / "web_extraction_shards.json").read_text())
        with mock.patch(
            "pipeline.cementitious.web_stages.extract_page_text",
            return_value=("", "Unavailable"),
        ):
            web_extract_shard(
                shard_id=int(shards[0]["shard_id"]),
                output_dir=self.out,
                keyword_only=True,
            )
        fail_csv = self.out / "rejected_records" / "web_fetch_failures.csv"
        self.assertTrue(fail_csv.is_file())
        text = fail_csv.read_text(encoding="utf-8")
        self.assertIn("web_source_id", text)

    def test_web_records_preserve_url_and_timestamp(self):
        self._prepare_ranked()
        shards = json.loads((self.out / "metadata" / "web_extraction_shards.json").read_text())
        for entry in shards:
            web_extract_shard(
                shard_id=int(entry["shard_id"]),
                output_dir=self.out,
                keyword_only=True,
            )
        merge_web_extractions(output_dir=self.out)
        rows = read_jsonl(self.out / "metadata" / "web_records_raw.jsonl")
        ok = [r for r in rows if not r.get("extraction_error")]
        self.assertTrue(ok)
        for row in ok:
            self.assertTrue(row.get("source_url") or row.get("normalized_url"))
            self.assertTrue(row.get("retrieval_timestamp"))
            self.assertEqual(row.get("evidence_origin"), "Web")


class TestLiteratureWebMerge(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.out = Path(self._tmpdir.name) / "7-30 results"
        (self.out / "metadata").mkdir(parents=True)
        (self.out / "checkpoints").mkdir(parents=True)
        (self.out / "rejected_records").mkdir(parents=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_distinguishable_and_linked_not_collapsed(self):
        lit = normalize_record(
            {
                "record_id": "lit1",
                "evidence_origin": "Literature",
                "source_type": "Academic Literature",
                "source_id": "10.1000/lit",
                "canonical_technology_name": "Chemical Absorption",
                "subcategory_slug": "cement_plant_carbon_capture",
                "sub_subcategory_slug": "chemical_absorption",
                "project_name": "Plant A Pilot",
                "evidence_text": "Paper evidence",
                "category": "Cementitious Materials",
                "subcategory": "Cement Plant Carbon Capture",
                "sub_subcategory": "Chemical Absorption",
            }
        )
        web = normalize_record(
            {
                "record_id": "web1",
                "evidence_origin": "Web",
                "source_type": "Company Website",
                "source_url": "https://company.example/project-a",
                "canonical_technology_name": "Chemical Absorption",
                "subcategory_slug": "cement_plant_carbon_capture",
                "sub_subcategory_slug": "chemical_absorption",
                "project_name": "Plant A Pilot",
                "evidence_text": "Company webpage claim",
                "category": "Cementitious Materials",
                "subcategory": "Cement Plant Carbon Capture",
                "sub_subcategory": "Chemical Absorption",
            }
        )
        (self.out / "metadata" / "literature_records_raw.jsonl").write_text(
            json.dumps(lit) + "\n", encoding="utf-8"
        )
        (self.out / "metadata" / "web_records_raw.jsonl").write_text(
            json.dumps(web) + "\n", encoding="utf-8"
        )
        summary = merge_literature_and_web(output_dir=self.out)
        self.assertEqual(summary["literature_records"], 1)
        self.assertEqual(summary["web_records"], 1)
        combined = read_jsonl(self.out / "metadata" / "combined_records_pre_dedupe.jsonl")
        self.assertEqual(len(combined), 2)
        origins = {r["evidence_origin"] for r in combined}
        self.assertEqual(origins, {"Literature", "Web"})
        web_row = next(r for r in combined if r["evidence_origin"] == "Web")
        self.assertTrue(web_row.get("related_record_ids"))
        # Exact duplicate keys differ by origin/url
        self.assertNotEqual(exact_duplicate_key(lit), exact_duplicate_key(web))
        kept, audit = deduplicate_records(combined)
        self.assertEqual(len(kept), 2)

    def test_exact_duplicate_web_removed(self):
        base = {
            "evidence_origin": "Web",
            "source_type": "Company Website",
            "source_url": "https://company.example/same",
            "normalized_url": "https://company.example/same",
            "canonical_technology_name": "Chemical Absorption",
            "sub_subcategory_slug": "chemical_absorption",
            "project_name": "Same",
            "company_or_organization": "Acme",
            "evidence_text": "same",
            "category": "Cementitious Materials",
            "subcategory": "Cement Plant Carbon Capture",
            "subcategory_slug": "cement_plant_carbon_capture",
            "sub_subcategory": "Chemical Absorption",
        }
        a = normalize_record({**base, "record_id": "a"})
        b = normalize_record({**base, "record_id": "b"})
        kept, audit = deduplicate_records([a, b])
        self.assertEqual(len(kept), 1)
        self.assertTrue(any(x.get("duplicate_status") == "Exact Duplicate Removed" for x in audit) or len(kept) == 1)


class TestWebExportPartitions(unittest.TestCase):
    def test_web_records_in_partitions_and_citations(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "7-30 results"
            out.mkdir()
            tax = get_taxonomy()
            sub = tax.subcategories["cement_plant_carbon_capture"]
            ss = tax.sub_subcategories["chemical_absorption"]
            row = normalize_record(
                {
                    "record_id": "web_exp_1",
                    "evidence_origin": "Web",
                    "source_type": "Company Website",
                    "source_id": "web:000001",
                    "source_url": "https://company.example/chem-abs",
                    "citation": "https://company.example/chem-abs",
                    "retrieval_timestamp": "2026-07-30T00:00:00+00:00",
                    "canonical_technology_name": ss.display_name,
                    "category": tax.category_display,
                    "subcategory": sub.display_name,
                    "subcategory_slug": sub.slug,
                    "sub_subcategory": ss.display_name,
                    "sub_subcategory_slug": ss.slug,
                    "evidence_text": "Pilot at cement plant using amine solvent.",
                    "taxonomy_confidence": "High",
                    "extraction_confidence": "Medium",
                },
                taxonomy=tax,
            )
            merged = out / "metadata"
            merged.mkdir(parents=True)
            write_csv(merged / "merged_records.csv", RECORD_FIELDS, [row])
            summary = export_taxonomy_partitions(
                input_path=merged / "merged_records.csv",
                output_dir=out,
                taxonomy=tax,
                force=True,
            )
            self.assertGreaterEqual(summary["accepted"], 1)
            all_csv = (out / "all_records" / "cementitious_materials_all_records.csv").read_text()
            self.assertIn("Web", all_csv)
            ss_csv = out / "sub_subcategories" / "chemical_absorption.csv"
            self.assertTrue(ss_csv.is_file())
            self.assertIn("company.example", ss_csv.read_text())
            cit = out / "citations" / "sub_subcategories" / "chemical_absorption_citations.csv"
            self.assertTrue(cit.is_file())
            part = (out / "all_records" / "partition_summary.csv").read_text()
            self.assertIn("web_record_count", part)


class TestModeGuards(unittest.TestCase):
    def test_literature_only_no_tavily_key_required_for_planning(self):
        # get_tavily_api_key should not be needed; literature-only build_plan ok
        os.environ.pop("TAVILY_API_KEY", None)
        from pipeline.cementitious.runner import RunConfig, build_plan

        plan = build_plan(RunConfig(mode="literature-only", planning=True), get_taxonomy())
        self.assertEqual(plan["mode"], "literature-only")

    def test_web_modes_require_tavily(self):
        os.environ.pop("TAVILY_API_KEY", None)
        from pipeline.cementitious.runner import RunConfig, run_pipeline

        with self.assertRaises(RuntimeError):
            run_pipeline(
                RunConfig(
                    mode="literature-and-web",
                    keyword_only=True,
                    sample_size=1,
                    output_dir=tempfile.mkdtemp(),
                )
            )

    def test_web_only_does_not_load_pickle(self):
        os.environ["TAVILY_API_KEY"] = "test-key-not-real"
        from pipeline.cementitious.runner import RunConfig, run_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "pipeline.cementitious.runner.load_paper_records",
                side_effect=AssertionError("pickle should not load"),
            ), mock.patch(
                "pipeline.cementitious.web_stages.get_tavily_client",
                return_value=FakeTavilyClient(),
            ):
                # Minimal web-only path through stages with keyword extract
                FakeTavilyClient.calls = []
                result = run_pipeline(
                    RunConfig(
                        mode="web-only",
                        keyword_only=True,
                        sub_subcategory="chemical_absorption",
                        output_dir=str(Path(tmp) / "7-30 results"),
                        web_limit=6,
                    )
                )
                self.assertEqual(result["status"], "ok")
                self.assertFalse(
                    (Path(result["output_dir"]) / "metadata" / "working_sample.jsonl").is_file()
                )

    def test_literature_only_never_calls_tavily(self):
        # Ensure FakeTavily is never constructed when literature-only with keyword path
        FakeTavilyClient.calls = []
        os.environ.pop("TAVILY_API_KEY", None)
        # Only verify web_search_shard is not imported/called via plan_web
        from pipeline.cementitious import web_stages

        with mock.patch.object(web_stages, "get_tavily_client", side_effect=AssertionError("no tavily")):
            # Planning literature does not touch tavily
            from pipeline.cementitious.runner import RunConfig, build_plan

            build_plan(RunConfig(mode="literature-only"), get_taxonomy())

    def test_tavily_key_from_env_only(self):
        os.environ["TAVILY_API_KEY"] = "secret-test-key"
        self.assertEqual(get_tavily_api_key(), "secret-test-key")


class TestResumeAndRerun(unittest.TestCase):
    def setUp(self):
        FakeTavilyClient.calls = []
        self._tmpdir = tempfile.TemporaryDirectory()
        self.out = Path(self._tmpdir.name) / "7-30 results"
        self.out.mkdir(parents=True)
        os.environ["TAVILY_API_KEY"] = "test-key-not-real"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_resume_and_missing_shard_spec(self):
        plan_web_query_shards(
            output_dir=self.out,
            limits=_web_limits(search_shard_size=1, queries_per_sub_subcategory=3),
            selected_sub_subcategories=["chemical_absorption"],
        )
        shards = json.loads((self.out / "metadata" / "web_query_shards.json").read_text())
        self.assertGreaterEqual(len(shards), 2)
        with mock.patch(
            "pipeline.cementitious.web_stages.get_tavily_client",
            return_value=FakeTavilyClient(),
        ):
            web_search_shard(shard_id=0, output_dir=self.out)
            # Resume should skip
            again = web_search_shard(shard_id=0, output_dir=self.out, resume=True)
            self.assertEqual(again["status"], "skipped_resume")
        missing = missing_web_search_shards(output_dir=self.out)
        self.assertTrue(missing)
        self.assertNotIn("0", missing.split(",")[0] if missing.startswith("0") else "x" + missing)
        # shard 0 complete so missing should not be only 0
        self.assertNotEqual(missing.strip(), "0")


class TestEngagingWebLauncherWiring(unittest.TestCase):
    def test_launcher_and_array_scripts_invoke_web_path(self):
        root = REPO_ROOT / "scripts" / "engaging"
        launcher = (root / "run_730_results.sh").read_text(encoding="utf-8")
        self.assertIn("NEED_WEB", launcher)
        self.assertIn("730_cementitious_plan_web_queries.sh", launcher)
        self.assertIn("730_cementitious_web_search_array.sh", launcher)
        self.assertIn("730_cementitious_orchestrate_web.sh", launcher)
        extract = (root / "730_cementitious_web_extract_array.sh").read_text(encoding="utf-8")
        self.assertIn("pipeline.cementitious.cluster web-extract", extract)
        search = (root / "730_cementitious_web_search_array.sh").read_text(encoding="utf-8")
        self.assertIn("pipeline.cementitious.cluster web-search", search)


class TestConfigValidation(unittest.TestCase):
    def test_invalid_web_limit_rejected(self):
        os.environ["WEB_RESULTS_PER_QUERY"] = "not-an-int"
        with self.assertRaises(ValueError):
            load_web_limits()
        os.environ.pop("WEB_RESULTS_PER_QUERY", None)


if __name__ == "__main__":
    unittest.main()
