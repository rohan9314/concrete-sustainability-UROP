#!/usr/bin/env python3
"""Generated Slurm/workflow plans and manifests without submitting jobs."""

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

from pipeline.cementitious.memory import STAGE_MEMORY_PROFILES
from pipeline.cementitious.slurm_graph import build_dry_run_dependency_graph
from pipeline.cementitious.workflow_launch import (
    PILOT_WEB_LEAF,
    build_launch_config,
    build_workflow_dry_run,
    required_stage_names,
)
from pipeline.decarb_testlib import launch_env


def _by_stage(jobs: list[dict]) -> dict[str, dict]:
    return {j["stage"]: j for j in jobs}


class SlurmPlanTests(unittest.TestCase):
    def test_combined_dependency_order_finalize_then_export(self) -> None:
        graph = build_dry_run_dependency_graph(run_mode="literature-and-web")
        jobs = graph["jobs"]
        by_stage = _by_stage(jobs)
        self.assertIn("finalize_submit", by_stage)
        self.assertIn("export", by_stage)
        self.assertIn("merge_literature_web", by_stage)
        export = by_stage["export"]
        self.assertEqual(export["dependency_type"], "afterok")
        self.assertTrue(export["parent_job_ids"])
        merge = by_stage["merge_literature_web"]
        self.assertEqual(set(merge["parent_job_ids"]), {graph["literature_terminal_job_id"], graph["web_terminal_job_id"]})
        self.assertFalse(graph["uses_marker_poll_finalizer"])
        commands = " ".join(j.get("submission_command") or "" for j in jobs)
        self.assertIn("sbatch", commands)

    def test_literature_only_omits_web_array_jobs(self) -> None:
        graph = build_dry_run_dependency_graph(run_mode="literature-only")
        stages = {j["stage"] for j in graph["jobs"]}
        self.assertIn("screen", stages)
        self.assertNotIn("web_search", stages)
        self.assertIn("export", stages)
        self.assertIsNone(graph["web_terminal_job_id"])

    def test_web_only_omits_literature_array_jobs(self) -> None:
        graph = build_dry_run_dependency_graph(run_mode="web-only")
        stages = {j["stage"] for j in graph["jobs"]}
        self.assertIn("web_search", stages)
        self.assertNotIn("screen", stages)
        self.assertIn("export", stages)

    def test_pilot_and_full_dry_runs_record_scope_flags_and_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            smoke = launch_env(Path(tmp) / "smoke")
            full = launch_env(Path(tmp) / "full")
            all_tax = launch_env(
                Path(tmp) / "all",
                extra={"CEMENTITIOUS_PILOT_TAXONOMY_SCOPE": "all"},
            )
            with mock.patch.dict(os.environ, smoke, clear=False):
                smoke_cfg = build_launch_config("pilot", dry_run=True, env=smoke)
                smoke_plan = build_workflow_dry_run(smoke_cfg)
            with mock.patch.dict(os.environ, all_tax, clear=False):
                all_cfg = build_launch_config("pilot", dry_run=True, env=all_tax)
                all_plan = build_workflow_dry_run(all_cfg)
            with mock.patch.dict(os.environ, full, clear=False):
                full_cfg = build_launch_config("full", dry_run=True, env=full)
                full_plan = build_workflow_dry_run(full_cfg)

            self.assertTrue(smoke_plan["dependency_graph"]["acyclic"])
            self.assertTrue(full_plan["dependency_graph"]["acyclic"])
            self.assertTrue(smoke_plan["web_search_restricted_to_chemical_absorption"])
            self.assertFalse(all_plan["web_search_restricted_to_chemical_absorption"])
            self.assertFalse(full_plan["web_search_restricted_to_chemical_absorption"])
            self.assertEqual(smoke_plan["selected_sub_subcategories"], [PILOT_WEB_LEAF])
            self.assertEqual(full_plan["literature_record_cap"], "FULL")
            self.assertEqual(full_plan["shard_size"], 10000)
            self.assertEqual(full_plan["workers"], 1)
            self.assertEqual(full_plan["array_max_concurrency"], 1)
            self.assertGreater(full_plan["web_search_node_count"], 50)
            self.assertIn("Policy", full_plan["web_search_level_1_branches"])
            self.assertTrue(full_plan["literature_enabled"])
            self.assertTrue(full_plan["web_search_enabled"])
            self.assertTrue(full_plan["export_job_depends_on_lit_and_web"])
            for stage in STAGE_MEMORY_PROFILES:
                self.assertIn(stage, full_plan["resource_requests"])
                self.assertIn("mem", full_plan["resource_requests"][stage])
            self.assertIn("preprocess_plan", required_stage_names())
            self.assertIn("export", required_stage_names())
            self.assertTrue(str(full_plan["output_dir"]))
            self.assertNotIn("sbatch --wait", json_safe(full_plan))

    def test_array_ranges_and_worker_counts_are_recorded(self) -> None:
        graph = build_dry_run_dependency_graph(
            run_mode="literature-and-web",
            screen_array="0-3",
            extract_array="0-1",
            web_search_array="0-2",
            web_extract_array="0-1",
        )
        by_stage = _by_stage(graph["jobs"])
        self.assertEqual(by_stage["screen"]["array_range"], "0-3")
        self.assertEqual(by_stage["extract"]["array_range"], "0-1")
        self.assertEqual(by_stage["web_search"]["array_range"], "0-2")
        self.assertEqual(by_stage["web_extract"]["array_range"], "0-1")


def json_safe(payload: dict) -> str:
    import json

    return json.dumps(payload, default=str)


if __name__ == "__main__":
    unittest.main()
