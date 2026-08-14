#!/usr/bin/env python3
"""One-line --full Concrete Decarbonization launcher: corpus, taxonomy, DAG, preflight."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.memory import STAGE_MEMORY_PROFILES
from pipeline.cementitious.workflow_launch import (
    FULL_ARRAY_MAX_CONCURRENCY,
    FULL_RESULTS_SUFFIX,
    FULL_SHARD_SIZE,
    FULL_WORKERS,
    PILOT_WEB_LEAF,
    PILOT_WEB_PARENT,
    build_launch_config,
    build_workflow_dry_run,
    conceptual_dag_stages,
    render_preflight_summary,
    required_stage_names,
    taxonomy_restriction_text,
    validate_launch_config,
    web_search_node_summaries_for_launch,
)
from pipeline.decarb_testlib import launch_env


CANONICAL = REPO_ROOT / "scripts" / "engaging" / "run_concrete_decarbonization_full_workflow.sh"
CHEMICAL_ABSORPTION_SLUGS = {PILOT_WEB_LEAF, "amine_absorption"}


class FullModeSelectionTests(unittest.TestCase):
    def test_full_selects_complete_corpus_lit_web_and_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True, env=env)
            self.assertEqual(cfg.mode, "full")
            self.assertIsNone(cfg.max_records)
            self.assertTrue(cfg.literature_enabled)
            self.assertTrue(cfg.web_enabled)
            self.assertEqual(cfg.run_mode, "literature-and-web")
            self.assertEqual(cfg.web_search_scope, "canonical")
            self.assertEqual(cfg.selected_subcategories, [])
            self.assertEqual(cfg.selected_sub_subcategories, [])
            self.assertNotEqual(cfg.selected_subcategories, [PILOT_WEB_PARENT])
            self.assertNotEqual(cfg.selected_sub_subcategories, [PILOT_WEB_LEAF])
            self.assertEqual(taxonomy_restriction_text(cfg), "NONE")
            nodes = web_search_node_summaries_for_launch(cfg)
            slugs = {n["slug"] for n in nodes}
            self.assertGreaterEqual(len(nodes), 299)
            self.assertFalse(slugs <= CHEMICAL_ABSORPTION_SLUGS)
            self.assertNotIn("chemical_absorption", cfg.selected_sub_subcategories)
            dry = build_workflow_dry_run(cfg)
            self.assertEqual(dry["literature_record_cap"], "FULL")
            self.assertEqual(dry["literature_record_cap_display"], "NONE / FULL CORPUS")
            self.assertEqual(dry["taxonomy_restriction"], "NONE")
            self.assertFalse(dry["web_search_restricted_to_chemical_absorption"])
            counts = dry["canonical_taxonomy"]
            self.assertEqual(counts["level_0_nodes"], 1)
            self.assertEqual(counts["level_1_nodes"], 7)
            self.assertEqual(counts["level_2_nodes"], 35)
            self.assertEqual(counts["level_3_nodes"], 91)
            self.assertEqual(counts["level_4_nodes"], 299)
            self.assertEqual(counts["total_taxonomy_nodes"], 433)
            self.assertGreaterEqual(dry["web_search_node_count"], 299)

    def test_full_uses_memory_safe_defaults_and_production_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True, env=env)
            self.assertEqual(cfg.shard_size, FULL_SHARD_SIZE)
            self.assertEqual(cfg.workers, FULL_WORKERS)
            self.assertEqual(cfg.array_max_concurrency, FULL_ARRAY_MAX_CONCURRENCY)
            self.assertEqual(cfg.shard_size, 10000)
            self.assertEqual(cfg.workers, 1)
            self.assertEqual(cfg.array_max_concurrency, 1)
            self.assertIn(FULL_RESULTS_SUFFIX, Path(cfg.results_root).parts)
            self.assertIn(FULL_RESULTS_SUFFIX, Path(cfg.output_dir).parts)
            self.assertTrue(cfg.output_dir.endswith("7-30 results") or Path(cfg.output_dir).name == "7-30 results")
            self.assertNotIn("cementitious_engaging_pilot", cfg.output_dir)
            self.assertNotIn("concrete_decarbonization_pilot_50", cfg.output_dir)
            self.assertNotIn("concrete_decarbonization_pilot_1000", cfg.output_dir)
            dry = build_workflow_dry_run(cfg)
            self.assertEqual(dry["resource_requests"]["preprocess_plan"]["mem"], "64G")
            self.assertEqual(dry["resource_requests"]["screen"]["mem"], "8G")
            self.assertEqual(dry["resource_requests"]["export"]["mem"], "16G")
            self.assertTrue(dry["hierarchical_export"]["master_csv"].endswith("concrete_decarbonization.csv"))
            self.assertIn("concrete_decarbonization_results", dry["hierarchical_export"]["root"])

    def test_full_plans_entire_dag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True, env=env)
            dry = build_workflow_dry_run(cfg)
            for stage in required_stage_names():
                if stage == "plan_web_queries":
                    continue
                self.assertIn(stage, dry["stage_order"])
            self.assertEqual(dry["stage_order"][-1], "export")
            self.assertTrue(dry["dependency_graph"]["acyclic"])
            self.assertTrue(dry["export_job_depends_on_lit_and_web"])
            conceptual = conceptual_dag_stages()
            self.assertEqual(conceptual[0], "preflight")
            self.assertEqual(conceptual[-1], "final completion checkpoint (export.complete)")
            self.assertIn("hierarchical export", conceptual)
            self.assertIn("resource accounting", conceptual)
            self.assertEqual(dry["conceptual_dag"], conceptual)
            stages = {j["stage"] for j in dry["dependency_graph"]["jobs"]}
            self.assertIn("preprocess_plan", stages)
            self.assertIn("screen", stages)
            self.assertIn("extract", stages)
            self.assertIn("web_search", stages)
            self.assertIn("web_extract", stages)
            self.assertIn("merge_literature_web", stages)
            self.assertIn("dedupe_qc", stages)
            self.assertIn("export", stages)


class FullPreflightFailureTests(unittest.TestCase):
    def test_missing_tavily_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            env.pop("TAVILY_API_KEY", None)
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("TAVILY_API_KEY", None)
                cfg = build_launch_config("full", dry_run=True, env=env)
            errors = validate_launch_config(cfg, environ=env)
            self.assertTrue(any("TAVILY_API_KEY" in e for e in errors))

    def test_missing_openai_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            env.pop("OPENAI_API_KEY", None)
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("OPENAI_API_KEY", None)
                cfg = build_launch_config("full", dry_run=True, env=env)
            errors = validate_launch_config(cfg, environ=env)
            self.assertTrue(any("OPENAI_API_KEY" in e for e in errors))


class FullExportProtectionTests(unittest.TestCase):
    def test_completed_export_blocks_unless_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=False, env=env)
            marker = Path(cfg.output_dir) / "checkpoints" / "export.complete"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("done\n", encoding="utf-8")
            blocked = validate_launch_config(
                cfg, environ=env, allow_uncalibrated_resources=True
            )
            self.assertTrue(any("export.complete" in e and "FORCE=1" in e for e in blocked))
            env_force = dict(env)
            env_force["FORCE"] = "1"
            with mock.patch.dict(os.environ, env_force, clear=False):
                forced = build_launch_config("full", dry_run=False, env=env_force)
            self.assertTrue(forced.force)
            errors = validate_launch_config(
                forced, environ=env_force, allow_uncalibrated_resources=True
            )
            self.assertFalse(any("export.complete" in e for e in errors))
            still = validate_launch_config(
                cfg, environ=env, allow_uncalibrated_resources=True
            )
            self.assertTrue(any("export.complete" in e for e in still))

    def test_export_complete_is_final_stage_only(self) -> None:
        self.assertEqual(required_stage_names()[-1], "export")
        self.assertNotIn("export.complete", required_stage_names()[:-1])
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True, env=env)
            dry = build_workflow_dry_run(cfg)
            self.assertTrue(dry["export_complete_path"].endswith("checkpoints/export.complete"))
            self.assertIn("final stage", dry["export_complete_written_when"])
            self.assertIn("validation", dry["export_complete_written_when"])


class PilotModesStillWorkTests(unittest.TestCase):
    def test_pilot_50_and_1000_and_smoke_remain_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                p50 = build_launch_config("pilot-50", dry_run=True, env=env)
                p1000 = build_launch_config("pilot-1000", dry_run=True, env=env)
                smoke = build_launch_config("smoke", dry_run=True, env=env)
                full = build_launch_config("full", dry_run=True, env=env)
            self.assertEqual(p50.max_records, 50)
            self.assertEqual(p1000.max_records, 1000)
            self.assertEqual(smoke.max_records, 50)
            self.assertIsNone(full.max_records)
            self.assertEqual(smoke.selected_sub_subcategories, [PILOT_WEB_LEAF])
            self.assertEqual(p50.selected_sub_subcategories, [])
            self.assertEqual(p1000.selected_sub_subcategories, [])
            self.assertEqual(taxonomy_restriction_text(smoke) != "NONE", True)
            self.assertEqual(taxonomy_restriction_text(p50), "NONE")
            self.assertEqual(taxonomy_restriction_text(p1000), "NONE")
            self.assertIn("concrete_decarbonization_pilot_50", p50.results_root)
            self.assertIn("concrete_decarbonization_pilot_1000", p1000.results_root)
            self.assertIn("cementitious_engaging_pilot", smoke.results_root)
            self.assertIn(FULL_RESULTS_SUFFIX, full.results_root)
            self.assertNotEqual(p50.output_dir, p1000.output_dir)
            self.assertNotEqual(p50.output_dir, full.output_dir)
            self.assertNotEqual(smoke.output_dir, full.output_dir)


class PreflightBannerTests(unittest.TestCase):
    def test_banner_makes_full_mode_and_restriction_obvious(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True, env=env)
            dry = build_workflow_dry_run(cfg)
            report = {
                "config": cfg.as_public_dict(),
                "taxonomy": {"canonical": dry["canonical_taxonomy"]},
                "dry_run": dry,
                "stage_memory_profiles": {
                    name: {"mem_slurm": p.mem_slurm} for name, p in STAGE_MEMORY_PROFILES.items()
                },
            }
            banner = render_preflight_summary(report, environ=env)
            self.assertIn("Concrete Decarbonization Full Workflow", banner)
            self.assertIn("mode=full", banner)
            self.assertIn("literature_enabled=yes", banner)
            self.assertIn("web_search_enabled=yes (Tavily)", banner)
            self.assertIn("taxonomy_scope=FULL", banner)
            self.assertIn("taxonomy_restriction=NONE", banner)
            self.assertIn("taxonomy_total_nodes=433", banner)
            self.assertIn("literature_record_cap=NONE / FULL CORPUS", banner)
            self.assertIn("taxonomy_level_4_nodes=299", banner)
            self.assertIn(FULL_RESULTS_SUFFIX, banner)
            self.assertIn("preprocess_mem=64G", banner)
            self.assertIn("worker_mem=8G", banner)
            self.assertIn("finalize_mem=16G", banner)
            self.assertIn("OPENAI_API_KEY=set", banner)
            self.assertIn("TAVILY_API_KEY=set", banner)
            self.assertNotIn("sk-", banner)
            self.assertNotIn(env["OPENAI_API_KEY"], banner)


class CanonicalScriptDryRunTests(unittest.TestCase):
    def test_full_dry_run_does_not_submit_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            proc_env = os.environ.copy()
            proc_env.update(env)
            proc = subprocess.run(
                ["bash", str(CANONICAL), "--full", "--dry-run"],
                cwd=str(REPO_ROOT),
                env=proc_env,
                capture_output=True,
                text=True,
            )
            combined = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, combined)
            self.assertIn("DRY-RUN complete", proc.stdout)
            self.assertIn("no sbatch", proc.stdout)
            self.assertIn("mode=full", proc.stdout)
            self.assertIn("literature_enabled=yes", proc.stdout)
            self.assertIn("web_search_enabled=yes (Tavily)", proc.stdout)
            self.assertIn("taxonomy_restriction=NONE", proc.stdout)
            self.assertIn("literature_record_cap=NONE / FULL CORPUS", proc.stdout)
            self.assertIn(FULL_RESULTS_SUFFIX, proc.stdout)
            self.assertIn("taxonomy_level_4_nodes=299", proc.stdout)
            self.assertNotIn("Submitted preprocess", proc.stdout)
            self.assertNotIn("Submitted bootstrap", proc.stdout)
            self.assertNotIn("WARNING: taxonomy restriction is ACTIVE", proc.stdout)
            out = Path(env["RESULTS_ROOT"]) / FULL_RESULTS_SUFFIX / "7-30 results"
            plan = out / "metadata" / "workflow_launch_plan.json"
            self.assertTrue(plan.is_file(), plan)
            self.assertFalse((out / "checkpoints" / "export.complete").is_file())

    def test_pilot_50_dry_run_still_works_via_canonical_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            proc_env = os.environ.copy()
            proc_env.update(env)
            proc = subprocess.run(
                ["bash", str(CANONICAL), "--pilot-50", "--dry-run"],
                cwd=str(REPO_ROOT),
                env=proc_env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn("mode=pilot-50", proc.stdout)
            self.assertIn("taxonomy_restriction=NONE", proc.stdout)
            self.assertIn("concrete_decarbonization_pilot_50", proc.stdout)
            self.assertIn("DRY-RUN complete", proc.stdout)

    def test_missing_openai_bash_preflight_fails_before_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            proc_env = os.environ.copy()
            proc_env.update(env)
            proc_env["OPENAI_API_KEY"] = ""
            proc = subprocess.run(
                ["bash", str(CANONICAL), "--full", "--dry-run"],
                cwd=str(REPO_ROOT),
                env=proc_env,
                capture_output=True,
                text=True,
            )
            combined = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, combined)
            self.assertIn("OPENAI_API_KEY", combined)
            self.assertNotIn("Submitted preprocess", combined)

    def test_missing_tavily_bash_preflight_fails_before_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            proc_env = os.environ.copy()
            proc_env.update(env)
            # Empty string beats dotenv (load_dotenv does not override existing vars).
            proc_env["TAVILY_API_KEY"] = ""
            proc = subprocess.run(
                ["bash", str(CANONICAL), "--full", "--dry-run"],
                cwd=str(REPO_ROOT),
                env=proc_env,
                capture_output=True,
                text=True,
            )
            combined = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, combined)
            self.assertIn("TAVILY_API_KEY", combined)
            self.assertNotIn("Submitted preprocess", combined)


if __name__ == "__main__":
    unittest.main()
