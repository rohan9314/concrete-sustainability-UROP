#!/usr/bin/env python3
"""SMOKE / PILOT-50 / PILOT-1000 / FULL launch-profile isolation tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.workflow_launch import (
    PILOT_MAX_RECORDS,
    PILOT_TAXONOMY_SCOPE_ALL,
    PILOT_TAXONOMY_SCOPE_SMOKE,
    PILOT_WEB_LEAF,
    PILOT_WEB_PARENT,
    build_launch_config,
    web_search_node_summaries_for_launch,
)
from pipeline.decarb_testlib import launch_env


class WorkflowModeIsolationTests(unittest.TestCase):
    def test_smoke_uses_small_taxonomy_scope_and_record_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp), extra={"CEMENTITIOUS_MAX_RECORDS": "8"})
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=True, env=env)
            self.assertEqual(cfg.mode, "pilot")
            self.assertEqual(cfg.pilot_taxonomy_scope, PILOT_TAXONOMY_SCOPE_SMOKE)
            self.assertEqual(cfg.selected_subcategories, [PILOT_WEB_PARENT])
            self.assertEqual(cfg.selected_sub_subcategories, [PILOT_WEB_LEAF])
            self.assertEqual(cfg.max_records, 8)
            self.assertTrue(cfg.literature_enabled)
            self.assertTrue(cfg.web_enabled)
            nodes = web_search_node_summaries_for_launch(cfg)
            self.assertTrue({n["slug"] for n in nodes} <= {PILOT_WEB_LEAF, "amine_absorption"} or {n["slug"] for n in nodes} == {PILOT_WEB_LEAF})

    def test_pilot_50_full_taxonomy_via_smoke_scope_all_keeps_record_cap(self) -> None:
        """Legacy --pilot + CEMENTITIOUS_PILOT_TAXONOMY_SCOPE=all: 50 papers, full taxonomy."""
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(
                Path(tmp),
                extra={
                    "CEMENTITIOUS_MAX_RECORDS": "50",
                    "CEMENTITIOUS_PILOT_TAXONOMY_SCOPE": "all",
                },
            )
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=True, env=env)
            self.assertEqual(cfg.max_records, PILOT_MAX_RECORDS)
            self.assertEqual(cfg.pilot_taxonomy_scope, PILOT_TAXONOMY_SCOPE_ALL)
            self.assertEqual(cfg.selected_subcategories, [])
            self.assertEqual(cfg.selected_sub_subcategories, [])
            self.assertTrue(cfg.literature_enabled)
            self.assertTrue(cfg.web_enabled)
            self.assertEqual(cfg.web_search_scope, "canonical")
            nodes = web_search_node_summaries_for_launch(cfg)
            self.assertGreater(len(nodes), 50)
            self.assertFalse({n["slug"] for n in nodes} <= {PILOT_WEB_LEAF, "amine_absorption"})

    def test_smoke_pilot_clamps_1000_env_to_fifty(self) -> None:
        """Smoke --pilot still clamps CEMENTITIOUS_MAX_RECORDS=1000 to 50."""
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(
                Path(tmp),
                extra={
                    "CEMENTITIOUS_MAX_RECORDS": "1000",
                    "CEMENTITIOUS_PILOT_TAXONOMY_SCOPE": "all",
                },
            )
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=True, env=env)
            self.assertEqual(cfg.max_records, PILOT_MAX_RECORDS)
            self.assertNotEqual(cfg.max_records, 1000)
            self.assertEqual(cfg.pilot_taxonomy_scope, PILOT_TAXONOMY_SCOPE_ALL)
            self.assertEqual(cfg.selected_sub_subcategories, [])

    def test_first_class_pilot_50_and_pilot_1000_use_full_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env50 = launch_env(Path(tmp) / "p50")
            env1000 = launch_env(Path(tmp) / "p1000")
            with mock.patch.dict(os.environ, env50, clear=False):
                p50 = build_launch_config("pilot-50", dry_run=True, env=env50)
            with mock.patch.dict(os.environ, env1000, clear=False):
                p1000 = build_launch_config("pilot-1000", dry_run=True, env=env1000)
            self.assertEqual(p50.mode, "pilot-50")
            self.assertEqual(p50.max_records, 50)
            self.assertEqual(p1000.mode, "pilot-1000")
            self.assertEqual(p1000.max_records, 1000)
            for cfg in (p50, p1000):
                self.assertTrue(cfg.literature_enabled)
                self.assertTrue(cfg.web_enabled)
                self.assertEqual(cfg.pilot_taxonomy_scope, PILOT_TAXONOMY_SCOPE_ALL)
                self.assertEqual(cfg.selected_subcategories, [])
                self.assertEqual(cfg.selected_sub_subcategories, [])
                self.assertEqual(cfg.web_search_scope, "canonical")
                nodes = web_search_node_summaries_for_launch(cfg)
                self.assertGreater(len(nodes), 50)
                self.assertFalse({n["slug"] for n in nodes} <= {PILOT_WEB_LEAF, "amine_absorption"})
            self.assertNotEqual(p50.results_root, p1000.results_root)
            self.assertIn("concrete_decarbonization_pilot_50", p50.results_root)
            self.assertIn("concrete_decarbonization_pilot_1000", p1000.results_root)

    def test_full_mode_uncapped_canonical_and_memory_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True, env=env)
            self.assertIsNone(cfg.max_records)
            self.assertEqual(cfg.selected_subcategories, [])
            self.assertEqual(cfg.selected_sub_subcategories, [])
            self.assertEqual(cfg.web_search_scope, "canonical")
            self.assertTrue(cfg.literature_enabled)
            self.assertTrue(cfg.web_enabled)
            self.assertEqual(cfg.shard_size, 10000)
            self.assertEqual(cfg.workers, 1)
            self.assertEqual(cfg.array_max_concurrency, 1)
            self.assertIn("concrete_decarbonization_full_run", cfg.results_root)
            nodes = web_search_node_summaries_for_launch(cfg)
            self.assertGreater(len(nodes), 50)

    def test_modes_do_not_inherit_taxonomy_restrictions_from_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            smoke_env = launch_env(Path(tmp) / "smoke")
            all_env = launch_env(
                Path(tmp) / "all",
                extra={"CEMENTITIOUS_PILOT_TAXONOMY_SCOPE": "all"},
            )
            full_env = launch_env(Path(tmp) / "full")
            with mock.patch.dict(os.environ, smoke_env, clear=False):
                smoke = build_launch_config("pilot", dry_run=True, env=smoke_env)
            with mock.patch.dict(os.environ, all_env, clear=False):
                pilot_all = build_launch_config("pilot", dry_run=True, env=all_env)
            with mock.patch.dict(os.environ, full_env, clear=False):
                full = build_launch_config("full", dry_run=True, env=full_env)
            self.assertEqual(smoke.selected_sub_subcategories, [PILOT_WEB_LEAF])
            self.assertEqual(pilot_all.selected_sub_subcategories, [])
            self.assertEqual(full.selected_sub_subcategories, [])
            self.assertNotEqual(smoke.web_search_scope, full.web_search_scope)
            self.assertEqual(pilot_all.web_search_scope, "canonical")
            self.assertEqual(full.web_search_scope, "canonical")


if __name__ == "__main__":
    unittest.main()
