#!/usr/bin/env python3
"""Tavily/web retrieval tests with fully mocked clients (no network)."""

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

from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.cementitious.web_queries import plan_canonical_web_queries, plan_web_queries
from pipeline.cementitious.web_scope import searchable_web_nodes
from pipeline.cementitious.web_stages import merge_web_search, plan_web_query_shards, web_search_shard
from pipeline.cementitious.web_tavily import tavily_search
from pipeline.cementitious.workflow_launch import (
    PILOT_WEB_LEAF,
    build_launch_config,
    validate_launch_config,
    web_search_node_summaries_for_launch,
)
from pipeline.decarb_testlib import FakeTavilyClient, launch_env, web_limits


class WebEnablementTests(unittest.TestCase):
    def test_web_enabled_full_and_explicit_disable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                full = build_launch_config("full", dry_run=True, env=env)
            self.assertTrue(full.web_enabled)
            disabled = launch_env(Path(tmp), extra={"WEB_SEARCH_ENABLED": "0", "RUN_MODE": "literature-only"})
            with mock.patch.dict(os.environ, disabled, clear=False):
                cfg = build_launch_config("full", dry_run=True, env=disabled)
            self.assertFalse(cfg.web_enabled)
            self.assertEqual(cfg.run_mode, "literature-only")

    def test_missing_tavily_key_fails_when_web_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            env.pop("TAVILY_API_KEY", None)
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("TAVILY_API_KEY", None)
                cfg = build_launch_config("full", dry_run=True, env=env)
            errors = validate_launch_config(cfg, environ=env)
            self.assertTrue(any("TAVILY_API_KEY" in e for e in errors))

    def test_web_disable_does_not_require_tavily(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp), extra={"RUN_MODE": "literature-only", "WEB_SEARCH_ENABLED": "0"})
            env.pop("TAVILY_API_KEY", None)
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("TAVILY_API_KEY", None)
                cfg = build_launch_config("full", dry_run=True, env=env)
            errors = validate_launch_config(cfg, environ=env)
            self.assertFalse(any("TAVILY_API_KEY" in e for e in errors))


class WebScopeAndQueryTests(unittest.TestCase):
    def test_taxonomy_derived_scope_covers_multiple_branches(self) -> None:
        nodes = searchable_web_nodes(get_decarbonization_taxonomy())
        l1 = {n.path_labels[1] for n in nodes if len(n.path_labels) > 1}
        self.assertGreaterEqual(len(l1), 5)
        self.assertIn("Aggregate Procurement", l1)
        self.assertIn("Policy", l1)
        slugs = {n.slug for n in nodes}
        self.assertGreater(len(slugs), 1)
        self.assertFalse(slugs <= {PILOT_WEB_LEAF, "amine_absorption"})

    def test_full_mode_not_hardcoded_to_chemical_absorption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True, env=env)
            nodes = web_search_node_summaries_for_launch(cfg)
            self.assertGreater(len(nodes), 50)
            self.assertNotEqual({n["slug"] for n in nodes}, {PILOT_WEB_LEAF})

    def test_aliases_used_in_queries(self) -> None:
        tax = get_decarbonization_taxonomy()
        plc = next(n for n in tax.ordered_nodes() if "PLC" in n.aliases)
        from pipeline.cementitious.web_queries import _templates_for_decarb_node

        joined = " ".join(text for _qt, text in _templates_for_decarb_node(plc)).casefold()
        self.assertTrue("plc" in joined or "type il" in joined)

    def test_query_cap_preserves_one_query_per_searchable_node(self) -> None:
        from pipeline.cementitious.web_scope import searchable_web_nodes

        queries = plan_canonical_web_queries(
            web_limits(queries_per_sub_subcategory=3, max_total_queries=10)
        )
        nodes = searchable_web_nodes()
        covered = {q.get("taxonomy_path") for q in queries}
        self.assertEqual(len(covered), len(nodes))
        self.assertGreaterEqual(len(queries), len(nodes))
        extras = len(queries) - len(nodes)
        self.assertLessEqual(extras, max(0, 10 - len(nodes)))


class MockedTavilyBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeTavilyClient.calls = []
        self._tmpdir = tempfile.TemporaryDirectory()
        self.out = Path(self._tmpdir.name) / "7-30 results"
        self.out.mkdir(parents=True)
        os.environ["TAVILY_API_KEY"] = "test-key-not-real"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        FakeTavilyClient.calls = []

    def test_duplicate_urls_empty_and_malformed_results(self) -> None:
        plan_web_query_shards(
            output_dir=self.out,
            limits=web_limits(search_shard_size=5, queries_per_sub_subcategory=2, max_total_urls=10),
            selected_sub_subcategories=["chemical_absorption"],
        )
        client = FakeTavilyClient()
        with mock.patch(
            "pipeline.cementitious.web_stages.get_tavily_client",
            return_value=client,
        ):
            shards = json.loads((self.out / "metadata" / "web_query_shards.json").read_text())
            for entry in shards:
                web_search_shard(
                    shard_id=int(entry["shard_id"]),
                    output_dir=self.out,
                    limits=web_limits(results_per_query=2, max_retries=0, rate_limit_sleep_s=0),
                    tavily_client=client,
                )
        summary = merge_web_search(output_dir=self.out)
        self.assertGreaterEqual(summary["unique_url_count"], 1)
        self.assertGreaterEqual(summary.get("duplicate_url_count", 0), 0)

        empty, meta = tavily_search(FakeTavilyClient(results=[]), "q", max_results=3, max_retries=0)
        self.assertEqual(empty, [])
        self.assertTrue(meta["ok"])

        parsed, meta2 = tavily_search(
            FakeTavilyClient(results=[None, "bad", {"url": ""}, {"url": "https://ok.example/x", "title": "Ok"}]),
            "q",
            max_results=5,
            max_retries=0,
        )
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["url"], "https://ok.example/x")

        capped, _meta = tavily_search(
            FakeTavilyClient(),
            "cement capture",
            max_results=1,
            max_retries=0,
        )
        self.assertLessEqual(len(capped), 1)

    def test_retries_then_success(self) -> None:
        client = FakeTavilyClient(
            results=[{"url": "https://retry.example/a", "title": "A", "content": "cement"}],
            fail_times=2,
        )
        with mock.patch("pipeline.cementitious.web_tavily.time.sleep", return_value=None):
            parsed, meta = tavily_search(client, "cement capture", max_results=1, max_retries=3)
        self.assertTrue(meta["ok"])
        self.assertEqual(meta["attempts"], 3)
        self.assertEqual(parsed[0]["url"], "https://retry.example/a")

    def test_retries_exhausted_returns_empty_without_raising(self) -> None:
        client = FakeTavilyClient(fail_times=5)
        with mock.patch("pipeline.cementitious.web_tavily.time.sleep", return_value=None):
            parsed, meta = tavily_search(client, "q", max_results=1, max_retries=1)
        self.assertFalse(meta["ok"])
        self.assertEqual(parsed, [])
        self.assertGreaterEqual(meta["attempts"], 2)

    def test_result_cap_and_provenance_fields_on_queries(self) -> None:
        queries = plan_web_queries(
            get_taxonomy(),
            web_limits(queries_per_sub_subcategory=2),
            selected_sub_subcategories=["chemical_absorption"],
        )
        self.assertTrue(queries)
        for q in queries:
            self.assertTrue(q.get("taxonomy_level_0"))
            self.assertTrue(q.get("query_text"))
            self.assertEqual(q.get("sub_subcategory_slug"), "chemical_absorption")

    def test_search_result_provenance_is_persisted(self) -> None:
        plan_web_query_shards(
            output_dir=self.out,
            limits=web_limits(search_shard_size=5, queries_per_sub_subcategory=1, max_total_urls=10),
            selected_sub_subcategories=["chemical_absorption"],
        )
        client = FakeTavilyClient()
        shards = json.loads((self.out / "metadata" / "web_query_shards.json").read_text())
        web_search_shard(
            shard_id=int(shards[0]["shard_id"]),
            output_dir=self.out,
            limits=web_limits(results_per_query=2, max_retries=0, rate_limit_sleep_s=0),
            tavily_client=client,
        )
        raw = (self.out / "metadata" / "web_search_shards").glob("web_search_shard_*.jsonl")
        rows = []
        for path in raw:
            if path.name.endswith("_summary.json"):
                continue
            for line in path.read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        self.assertTrue(rows)
        self.assertTrue(any(r.get("query_id") and r.get("url") for r in rows))
        self.assertTrue(any(r.get("query_text") for r in rows))


if __name__ == "__main__":
    unittest.main()
