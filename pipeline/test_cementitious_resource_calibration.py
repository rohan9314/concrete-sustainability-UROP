#!/usr/bin/env python3
"""Tests for pilot telemetry consolidation and full-run memory calibration gates."""

from __future__ import annotations

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

from pipeline.cementitious.memory import DEFAULT_SAFETY_FACTOR, STAGE_MEMORY_PROFILES
from pipeline.cementitious.resource_calibration import (
    build_full_run_recommendations,
    estimate_full_run_peak_mb,
    validate_pilot_calibration,
    write_resource_usage_summary,
)
from pipeline.cementitious.workflow_launch import build_launch_config, build_workflow_dry_run, validate_launch_config


def _write_tel(root: Path, stage: str, peak_mb: float, *, status: str = "complete", req: float | None = None) -> None:
    logs = root / "logs" / "resource_telemetry"
    logs.mkdir(parents=True, exist_ok=True)
    profile = STAGE_MEMORY_PROFILES[stage]
    req = float(req if req is not None else profile.mem_gb)
    peak_bytes = int(peak_mb * 1024 * 1024)
    payload = {
        "stage": stage,
        "job_id": "1001",
        "array_task_id": "0",
        "hostname": "testnode",
        "requested_mem_gb": req,
        "allocated_cpus": 1,
        "input_record_count": 50,
        "shard_file_bytes": 1234,
        "worker_count": 1,
        "batch_size": 10,
        "peak_rss_bytes": peak_bytes,
        "peak_rss_mb": peak_mb,
        "utilization_pct_of_request": round(100.0 * peak_bytes / (req * 1024**3), 2),
        "soft_limit_gb": profile.soft_limit_gb,
        "elapsed_seconds": 1.0,
        "records_processed": 50,
        "completion_status": status,
    }
    (logs / f"{stage}_job_1001.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _seed_pilot_success(root: Path, *, high_util_screen: bool = False) -> None:
    (root / "checkpoints").mkdir(parents=True, exist_ok=True)
    (root / "checkpoints" / "export.complete").write_text("ok\n", encoding="utf-8")
    for stage, peak in {
        "preprocess_plan": 20000,
        "screen": 500 if not high_util_screen else 7000,
        "extract": 400,
        "web_search": 300,
        "web_extract": 600,
        "dedupe_qc": 800,
        "export": 900,
    }.items():
        req = None
        if high_util_screen and stage == "screen":
            req = 8.0  # 7000MB of 8GB ~ 85%
        _write_tel(root, stage, peak, req=req)


class StageMemoryProfileTests(unittest.TestCase):
    def test_soft_ceiling_is_eighty_percent(self) -> None:
        for profile in STAGE_MEMORY_PROFILES.values():
            self.assertAlmostEqual(profile.soft_limit_gb, profile.mem_gb * 0.8, places=3)

    def test_pilot_dry_run_includes_explicit_memory_every_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "c.pkl"
            with pkl.open("wb") as handle:
                pickle.dump([{"title": "t", "abstract": "a", "doi": "1"}], handle)
            env = {
                "OPENAI_API_KEY": "sk-test",
                "TAVILY_API_KEY": "tvly-test",
                "PICKLE_PATH": str(pkl),
                "RESULTS_ROOT": str(Path(tmp) / "results"),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=True)
                dry = build_workflow_dry_run(cfg)
            reqs = dry["resource_requests"]
            for stage in STAGE_MEMORY_PROFILES:
                self.assertIn(stage, reqs)
                self.assertIn("mem", reqs[stage])
                self.assertIn("soft_limit_gb", reqs[stage])
            self.assertEqual(dry["soft_fraction_of_slurm_mem"], 0.80)


class CalibrationTests(unittest.TestCase):
    def test_safety_factor_at_least_1_5_and_recommendations_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_pilot_success(root)
            reco = build_full_run_recommendations(root, safety_factor=DEFAULT_SAFETY_FACTOR)
            self.assertGreaterEqual(reco["safety_factor"], 1.5)
            self.assertTrue((root / "metadata" / "full_run_resource_recommendations.json").is_file())
            self.assertTrue((root / "metadata" / "resource_usage_summary.csv").is_file())
            for stage, info in reco["stages"].items():
                self.assertGreaterEqual(info["safety_factor"], 1.5)
                self.assertLessEqual(
                    info["recommended_soft_ceiling_gb"],
                    info["recommended_slurm_memory_gb"] * 0.80 + 1e-6,
                )

    def test_preprocess_treated_differently_from_shard_local(self) -> None:
        pre_mb, pre_conf, pre_why = estimate_full_run_peak_mb("preprocess_plan", 18000)
        scr_mb, scr_conf, scr_why = estimate_full_run_peak_mb(
            "screen", 400, shard_size_pilot=50, shard_size_full=10000
        )
        self.assertEqual(pre_mb, 18000)
        self.assertIn("full pickle", pre_why.lower())
        self.assertGreater(scr_mb, 400)
        self.assertIn("shard", scr_why.lower())

    def test_high_utilization_increases_full_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_pilot_success(root, high_util_screen=True)
            reco = build_full_run_recommendations(root)
            screen = reco["stages"]["screen"]
            self.assertGreater(screen["recommended_slurm_memory_gb"], screen["pilot_requested_memory_gb"])

    def test_full_command_refuses_without_pilot_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "c.pkl"
            with pkl.open("wb") as handle:
                pickle.dump([{"title": "t", "abstract": "a", "doi": "1"}], handle)
            env = {
                "OPENAI_API_KEY": "sk-test",
                "TAVILY_API_KEY": "tvly-test",
                "PICKLE_PATH": str(pkl),
                "RESULTS_ROOT": str(Path(tmp) / "results"),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=False)
                errors = validate_launch_config(cfg, environ=env)
            self.assertTrue(any("pilot" in e.lower() or "calibrat" in e.lower() for e in errors))

    def test_override_exists_but_not_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "c.pkl"
            with pkl.open("wb") as handle:
                pickle.dump([{"title": "t", "abstract": "a", "doi": "1"}], handle)
            env = {
                "OPENAI_API_KEY": "sk-test",
                "TAVILY_API_KEY": "tvly-test",
                "PICKLE_PATH": str(pkl),
                "RESULTS_ROOT": str(Path(tmp) / "results"),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=False)
                blocked = validate_launch_config(cfg, environ=env, allow_uncalibrated_resources=False)
                allowed = validate_launch_config(cfg, environ=env, allow_uncalibrated_resources=True)
            self.assertTrue(blocked)
            self.assertFalse(any("pilot" in e.lower() or "calibrat" in e.lower() for e in allowed))

    def test_oom_or_soft_stop_blocks_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_pilot_success(root)
            _write_tel(root, "screen", 100, status="soft_memory_stop")
            verdict = validate_pilot_calibration(root)
            self.assertFalse(verdict["ok"])
            self.assertTrue(any("soft_memory" in e for e in verdict["errors"]))

    def test_missing_maxrss_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "checkpoints").mkdir(parents=True)
            (root / "checkpoints" / "export.complete").write_text("ok\n", encoding="utf-8")
            # Only one stage present
            _write_tel(root, "screen", 100)
            verdict = validate_pilot_calibration(root)
            self.assertFalse(verdict["ok"])
            self.assertTrue(any("Missing peak RSS" in e for e in verdict["errors"]))

    def test_web_scaling_model_mentions_leaves(self) -> None:
        mb, conf, why = estimate_full_run_peak_mb(
            "web_extract", 500, pilot_leaf_count=1, full_leaf_count=58
        )
        self.assertGreaterEqual(mb, 500)
        self.assertIn("leaves", why.lower())


class ScriptGuardTests(unittest.TestCase):
    def test_full_workflow_script_mentions_calibration_override(self) -> None:
        text = (
            REPO_ROOT / "scripts" / "engaging" / "run_concrete_decarbonization_full_workflow.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--allow-uncalibrated-resources", text)
        self.assertIn("resource_usage_summary", text)
        self.assertIn("full_run_resource_recommendations", text)
        self.assertIn("MaxRSS", text)


if __name__ == "__main__":
    unittest.main()
