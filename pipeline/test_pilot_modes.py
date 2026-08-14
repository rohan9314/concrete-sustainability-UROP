#!/usr/bin/env python3
"""Production-like --pilot-50 / --pilot-1000 modes: full taxonomy, lit+web, separate roots."""

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

from pipeline.cementitious.corpus_shards import (
    load_corpus_shards_manifest,
    materialize_corpus_shards,
    read_corpus_shard_records,
)
from pipeline.cementitious.workflow_launch import (
    DEFAULT_SAMPLE_SEED,
    PILOT_1000_MAX_RECORDS,
    PILOT_1000_RESULTS_SUFFIX,
    PILOT_1000_WEB_DEFAULTS,
    PILOT_50_MAX_RECORDS,
    PILOT_50_RESULTS_SUFFIX,
    PILOT_50_WEB_DEFAULTS,
    PILOT_RESULTS_SUFFIX,
    PILOT_TAXONOMY_SCOPE_ALL,
    PILOT_WEB_LEAF,
    PILOT_WEB_PARENT,
    build_launch_config,
    build_launch_metadata,
    build_workflow_dry_run,
    validate_launch_config,
    web_search_node_summaries_for_launch,
)
from pipeline.decarb_testlib import launch_env, paper_record, write_pickle


CHEMICAL_ABSORPTION_SLUGS = {PILOT_WEB_LEAF, "amine_absorption"}


def _assert_full_taxonomy_pilot(test: unittest.TestCase, cfg, *, cap: int, suffix: str) -> None:
    test.assertEqual(cfg.max_records, cap)
    test.assertTrue(cfg.literature_enabled)
    test.assertTrue(cfg.web_enabled)
    test.assertEqual(cfg.run_mode, "literature-and-web")
    test.assertEqual(cfg.pilot_taxonomy_scope, PILOT_TAXONOMY_SCOPE_ALL)
    test.assertEqual(cfg.selected_subcategories, [])
    test.assertEqual(cfg.selected_sub_subcategories, [])
    test.assertNotEqual(cfg.selected_subcategories, [PILOT_WEB_PARENT])
    test.assertNotEqual(cfg.selected_sub_subcategories, [PILOT_WEB_LEAF])
    test.assertEqual(cfg.web_search_scope, "canonical")
    test.assertTrue(cfg.telemetry_enabled)
    test.assertTrue(cfg.hierarchical_export_enabled)
    test.assertEqual(cfg.sample_seed, DEFAULT_SAMPLE_SEED)
    test.assertIn(suffix, Path(cfg.results_root).parts)
    test.assertIn(suffix, Path(cfg.output_dir).parts)
    nodes = web_search_node_summaries_for_launch(cfg)
    slugs = {n["slug"] for n in nodes}
    test.assertGreater(len(nodes), 50)
    test.assertFalse(slugs <= CHEMICAL_ABSORPTION_SLUGS)
    l1 = {n.get("level_1") for n in nodes if n.get("level_1")}
    test.assertGreaterEqual(len(l1), 2)
    test.assertIn("Cementitious Materials", l1)


class Pilot50ModeTests(unittest.TestCase):
    def test_pilot_50_caps_literature_at_fifty_with_lit_web_full_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot-50", dry_run=True, env=env)
            _assert_full_taxonomy_pilot(
                self, cfg, cap=PILOT_50_MAX_RECORDS, suffix=PILOT_50_RESULTS_SUFFIX
            )
            self.assertEqual(cfg.workers, 1)
            self.assertEqual(cfg.array_max_concurrency, 1)
            self.assertEqual(cfg.shard_size, 50)
            self.assertEqual(cfg.web_limits["WEB_MAX_TOTAL_URLS"], PILOT_50_WEB_DEFAULTS["WEB_MAX_TOTAL_URLS"])
            self.assertEqual(
                cfg.web_limits["WEB_MAX_TOTAL_QUERIES"],
                PILOT_50_WEB_DEFAULTS["WEB_MAX_TOTAL_QUERIES"],
            )
            self.assertEqual(
                cfg.web_limits["WEB_QUERIES_PER_NODE"],
                PILOT_50_WEB_DEFAULTS["WEB_QUERIES_PER_NODE"],
            )
            errors = validate_launch_config(cfg, environ=env)
            self.assertEqual(errors, [])


class Pilot1000ModeTests(unittest.TestCase):
    def test_pilot_1000_caps_literature_at_one_thousand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot-1000", dry_run=True, env=env)
            _assert_full_taxonomy_pilot(
                self, cfg, cap=PILOT_1000_MAX_RECORDS, suffix=PILOT_1000_RESULTS_SUFFIX
            )
            self.assertEqual(cfg.workers, 1)
            self.assertEqual(cfg.array_max_concurrency, 2)
            self.assertEqual(cfg.shard_size, 250)
            self.assertEqual(
                cfg.web_limits["WEB_MAX_TOTAL_URLS"],
                PILOT_1000_WEB_DEFAULTS["WEB_MAX_TOTAL_URLS"],
            )
            self.assertGreater(
                cfg.web_limits["WEB_MAX_TOTAL_URLS"],
                PILOT_50_WEB_DEFAULTS["WEB_MAX_TOTAL_URLS"],
            )
            self.assertGreaterEqual(
                cfg.web_limits["WEB_QUERIES_PER_NODE"],
                PILOT_50_WEB_DEFAULTS["WEB_QUERIES_PER_NODE"],
            )
            self.assertGreater(
                int(cfg.web_limits["WEB_QUERIES_PER_NODE"]),
                int(PILOT_50_WEB_DEFAULTS["WEB_QUERIES_PER_NODE"]),
            )
            errors = validate_launch_config(cfg, environ=env)
            self.assertEqual(errors, [])


class PilotIsolationTests(unittest.TestCase):
    def test_neither_pilot_inherits_smoke_taxonomy_restriction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(
                Path(tmp),
                extra={"CEMENTITIOUS_PILOT_TAXONOMY_SCOPE": "smoke"},
            )
            with mock.patch.dict(os.environ, env, clear=False):
                p50 = build_launch_config("pilot-50", dry_run=True, env=env)
                p1000 = build_launch_config("pilot-1000", dry_run=True, env=env)
                smoke = build_launch_config("pilot", dry_run=True, env=env)
            self.assertEqual(smoke.selected_sub_subcategories, [PILOT_WEB_LEAF])
            self.assertEqual(p50.selected_sub_subcategories, [])
            self.assertEqual(p1000.selected_sub_subcategories, [])
            self.assertEqual(p50.pilot_taxonomy_scope, PILOT_TAXONOMY_SCOPE_ALL)
            self.assertEqual(p1000.pilot_taxonomy_scope, PILOT_TAXONOMY_SCOPE_ALL)

    def test_output_roots_and_checkpoints_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                p50 = build_launch_config("pilot-50", dry_run=False, env=env)
                p1000 = build_launch_config("pilot-1000", dry_run=False, env=env)
                full = build_launch_config("full", dry_run=True, env=env)
            self.assertNotEqual(p50.output_dir, p1000.output_dir)
            self.assertNotEqual(p50.output_dir, full.output_dir)
            self.assertNotEqual(p1000.output_dir, full.output_dir)
            self.assertNotIn(PILOT_50_RESULTS_SUFFIX, Path(p1000.output_dir).parts)
            self.assertNotIn(PILOT_1000_RESULTS_SUFFIX, Path(p50.output_dir).parts)
            self.assertNotIn(PILOT_RESULTS_SUFFIX, Path(p50.output_dir).parts)
            for suffix in (PILOT_50_RESULTS_SUFFIX, PILOT_1000_RESULTS_SUFFIX, PILOT_RESULTS_SUFFIX):
                self.assertNotIn(suffix, Path(full.output_dir).parts)

            marker50 = Path(p50.output_dir) / "checkpoints" / "export.complete"
            marker50.parent.mkdir(parents=True, exist_ok=True)
            marker50.write_text("done\n", encoding="utf-8")
            blocked50 = validate_launch_config(p50, environ=env)
            self.assertTrue(any("export.complete" in e for e in blocked50))
            free1000 = validate_launch_config(p1000, environ=env)
            self.assertFalse(any("export.complete" in e for e in free1000))

            marker1000 = Path(p1000.output_dir) / "checkpoints" / "export.complete"
            marker1000.parent.mkdir(parents=True, exist_ok=True)
            marker1000.write_text("done\n", encoding="utf-8")
            free_full = validate_launch_config(full, environ=env)
            self.assertFalse(any("export.complete" in e for e in free_full))

            env_force = dict(env)
            env_force["FORCE"] = "1"
            with mock.patch.dict(os.environ, env_force, clear=False):
                forced50 = build_launch_config("pilot-50", dry_run=False, env=env_force)
            self.assertTrue(forced50.force)
            self.assertEqual(forced50.output_dir, p50.output_dir)
            self.assertNotEqual(forced50.output_dir, p1000.output_dir)
            errors = validate_launch_config(forced50, environ=env_force)
            self.assertFalse(any("export.complete" in e for e in errors))
            still_blocked_1000 = validate_launch_config(p1000, environ=env)
            self.assertTrue(any("export.complete" in e for e in still_blocked_1000))

    def test_web_caps_are_configurable_and_differ_by_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(
                Path(tmp),
                extra={"WEB_MAX_TOTAL_URLS": "25", "WEB_MAX_TOTAL_QUERIES": "18"},
            )
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot-50", dry_run=True, env=env)
            self.assertEqual(cfg.web_limits["WEB_MAX_TOTAL_URLS"], 25)
            self.assertEqual(cfg.web_limits["WEB_MAX_TOTAL_QUERIES"], 18)


class PilotDryRunAndMetadataTests(unittest.TestCase):
    def test_dry_run_reflects_configuration_and_not_chemical_absorption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                p50 = build_launch_config("pilot-50", dry_run=True, env=env)
                p1000 = build_launch_config("pilot-1000", dry_run=True, env=env)
            for cfg, cap, suffix in (
                (p50, 50, PILOT_50_RESULTS_SUFFIX),
                (p1000, 1000, PILOT_1000_RESULTS_SUFFIX),
            ):
                dry = build_workflow_dry_run(cfg)
                self.assertEqual(dry["literature_record_cap"], cap)
                self.assertTrue(dry["literature_enabled"])
                self.assertTrue(dry["web_search_enabled"])
                self.assertFalse(dry["web_search_restricted_to_chemical_absorption"])
                self.assertGreater(len(dry["web_search_level_1_branches"]), 1)
                self.assertGreater(dry["web_search_node_count"], 50)
                self.assertEqual(dry["sample_seed"], DEFAULT_SAMPLE_SEED)
                self.assertTrue(dry["telemetry_enabled"])
                self.assertEqual(dry["results_suffix"], suffix)
                counts = dry["canonical_taxonomy"]
                self.assertEqual(counts["taxonomy_root"], "Concrete Decarbonization")
                self.assertEqual(counts["level_0_nodes"], 1)
                self.assertEqual(counts["level_1_nodes"], 7)
                self.assertEqual(counts["level_4_nodes"], 299)
                self.assertIn("concrete_decarbonization_results", dry["hierarchical_export"]["root"])
                meta = build_launch_metadata(cfg)
                self.assertEqual(meta["mode"], cfg.mode)
                self.assertEqual(meta["literature_record_cap"], cap)
                self.assertTrue(meta["literature_enabled"])
                self.assertTrue(meta["web_enabled"])
                self.assertTrue(meta["telemetry_enabled"])
                self.assertTrue(meta["hierarchical_export_enabled"])
                self.assertEqual(meta["random_seed"], DEFAULT_SAMPLE_SEED)
                self.assertIn("preprocess_plan", meta["requested_slurm_resources"])
                self.assertTrue(meta["run_timestamp"])
                self.assertEqual(meta["taxonomy_node_counts_by_level"]["level_4"], 299)


class PilotSamplingTests(unittest.TestCase):
    def tearDown(self) -> None:
        import pipeline.corpus_loader as cl

        cl._cached_records = None
        cl._cached_path = None

    def test_literature_sampling_is_deterministic_not_first_n(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            write_pickle(pkl, [paper_record(i) for i in range(40)])
            out_a = Path(tmp) / "a"
            out_b = Path(tmp) / "b"
            out_c = Path(tmp) / "c"
            env_a = {"CEMENTITIOUS_MAX_RECORDS": "8", "CEMENTITIOUS_SAMPLE_SEED": "42"}
            env_b = {"CEMENTITIOUS_MAX_RECORDS": "8", "CEMENTITIOUS_SAMPLE_SEED": "42"}
            env_c = {"CEMENTITIOUS_MAX_RECORDS": "8", "CEMENTITIOUS_SAMPLE_SEED": "99"}
            with mock.patch.dict(os.environ, env_a, clear=False):
                a = materialize_corpus_shards(
                    input_path=pkl, output_dir=out_a, shard_size=8, max_records=8
                )
            with mock.patch.dict(os.environ, env_b, clear=False):
                b = materialize_corpus_shards(
                    input_path=pkl, output_dir=out_b, shard_size=8, max_records=8
                )
            with mock.patch.dict(os.environ, env_c, clear=False):
                c = materialize_corpus_shards(
                    input_path=pkl, output_dir=out_c, shard_size=8, max_records=8
                )
            self.assertEqual(a["sample_seed"], 42)
            self.assertEqual(a["record_count"], 8)
            dois_a = [
                row["doi"]
                for shard in a["shards"]
                for row in read_corpus_shard_records(shard["record_shard_path"])
            ]
            dois_b = [
                row["doi"]
                for shard in b["shards"]
                for row in read_corpus_shard_records(shard["record_shard_path"])
            ]
            dois_c = [
                row["doi"]
                for shard in c["shards"]
                for row in read_corpus_shard_records(shard["record_shard_path"])
            ]
            self.assertEqual(dois_a, dois_b)
            self.assertNotEqual(dois_a, dois_c)
            self.assertNotEqual(dois_a, [f"10.1000/test.{i}" for i in range(8)])
            with mock.patch.dict(os.environ, env_a, clear=False):
                reused = materialize_corpus_shards(
                    input_path=pkl, output_dir=out_a, shard_size=8, max_records=8
                )
            self.assertEqual(reused["sample_seed"], 42)
            self.assertEqual(load_corpus_shards_manifest(out_a)["sample_seed"], 42)


class PilotScriptSurfaceTests(unittest.TestCase):
    def test_one_line_commands_are_documented(self) -> None:
        launcher = REPO_ROOT / "scripts" / "engaging" / "run_concrete_decarbonization_full_workflow.sh"
        alias = REPO_ROOT / "scripts" / "engaging" / "run_cementitious_full_workflow.sh"
        text = launcher.read_text(encoding="utf-8")
        self.assertIn("--pilot-50", text)
        self.assertIn("--pilot-1000", text)
        self.assertIn("--full", text)
        self.assertIn("--smoke", text)
        self.assertTrue(alias.is_file())
        self.assertIn("run_concrete_decarbonization_full_workflow.sh", alias.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
