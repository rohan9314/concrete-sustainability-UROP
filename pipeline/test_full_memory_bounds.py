#!/usr/bin/env python3
"""Full-run memory bounds: sharding, concurrency, export, telemetry gate (offline)."""

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

from pipeline.cementitious.hierarchical_export import (
    _bucket_rows_by_node,
    _project,
    write_hierarchical_export,
)
from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy
from pipeline.cementitious.memory import cementitious_workers
from pipeline.cementitious.resource_calibration import (
    DEFAULT_SAFETY_FACTOR,
    ESTIMATED_FULL_CORPUS_RECORDS,
    FULL_ARRAY_CONCURRENCY_DEFAULT,
    FULL_SHARD_SIZE_DEFAULT,
    FULL_WORKERS_DEFAULT,
    build_full_run_recommendations,
    classify_job_failure,
)
from pipeline.cementitious.schema import RECORD_FIELDS
from pipeline.cementitious.stages import rank_and_plan_extraction
from pipeline.cementitious.workflow_launch import (
    FULL_ARRAY_MAX_CONCURRENCY,
    FULL_SHARD_SIZE,
    FULL_WORKERS,
    build_launch_config,
    build_workflow_dry_run,
    describe_pilot_telemetry_source,
    validate_launch_config,
)
from pipeline.cluster_shards import estimated_shard_count, plan_corpus_shards
from pipeline.decarb_testlib import REPRESENTATIVE_PATHS, launch_env, record_for_path
from pipeline.test_cementitious_resource_calibration import _seed_pilot_success


class ShardSizeAndConcurrencyTests(unittest.TestCase):
    def test_estimated_shard_count_matches_plan(self) -> None:
        self.assertEqual(estimated_shard_count(159_000, 10_000), 16)
        self.assertEqual(estimated_shard_count(50, 50), 1)
        self.assertEqual(estimated_shard_count(0, 10_000), 0)
        plan = plan_corpus_shards(159_000, 10_000)
        self.assertEqual(len(plan), estimated_shard_count(159_000, 10_000))
        with self.assertRaises(ValueError):
            estimated_shard_count(10, 0)

    def test_full_defaults_are_conservative(self) -> None:
        self.assertEqual(FULL_SHARD_SIZE, 10000)
        self.assertEqual(FULL_WORKERS, 1)
        self.assertEqual(FULL_ARRAY_MAX_CONCURRENCY, 1)
        self.assertEqual(FULL_SHARD_SIZE_DEFAULT, 10000)
        self.assertEqual(FULL_WORKERS_DEFAULT, 1)
        self.assertEqual(FULL_ARRAY_CONCURRENCY_DEFAULT, 1)

    def test_worker_count_is_capped(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CEMENTITIOUS_WORKERS": "32", "CEMENTITIOUS_MAX_WORKERS": "4"},
            clear=False,
        ):
            self.assertEqual(cementitious_workers(), 4)


class RecommendationAndGateTests(unittest.TestCase):
    def test_recommendations_include_safety_margin_and_plan_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_pilot_success(root)
            reco = build_full_run_recommendations(root, safety_factor=DEFAULT_SAFETY_FACTOR)
            self.assertGreaterEqual(reco["safety_factor"], 1.5)
            self.assertEqual(reco["shard_size"], 10000)
            self.assertEqual(reco["workers"], 1)
            self.assertEqual(reco["array_concurrency"], 1)
            self.assertEqual(reco["expected_shard_count"], 16)
            self.assertEqual(reco["estimated_full_corpus_records"], ESTIMATED_FULL_CORPUS_RECORDS)
            self.assertIn("recommended_preprocess_memory", reco)
            self.assertIn("recommended_worker_memory", reco)
            self.assertIn("recommended_finalize_export_memory", reco)
            self.assertEqual(reco["evidence_source_pilot"], str(root))
            screen = reco["stages"]["screen"]
            observed_gb = int((screen["pilot_observed_peak_rss_mb"] + 1023) // 1024) or 1
            self.assertGreaterEqual(screen["recommended_slurm_memory_gb"], observed_gb)

    def test_missing_pilot_telemetry_warns_in_dry_run_and_blocks_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True, env=env)
                dry = build_workflow_dry_run(cfg)
                source = dry["pilot_telemetry_source"]
                self.assertFalse(source["present"])
                self.assertIn("No pilot telemetry", source["warning"])
                self.assertEqual(dry["estimated_corpus_records"], ESTIMATED_FULL_CORPUS_RECORDS)
                self.assertEqual(dry["estimated_literature_shard_count"], 16)
                self.assertEqual(dry["workers"], 1)
                self.assertEqual(dry["array_max_concurrency"], 1)
                self.assertEqual(cfg.shard_size, 10000)
                blocked = build_launch_config("full", dry_run=False, env=env)
                errors = validate_launch_config(blocked, environ=env)
            self.assertTrue(any("pilot" in e.lower() or "calibrat" in e.lower() for e in errors))
            allowed = validate_launch_config(
                blocked, environ=env, allow_uncalibrated_resources=True
            )
            self.assertFalse(any("pilot" in e.lower() or "calibrat" in e.lower() for e in allowed))


class HierarchicalExportMemoryTests(unittest.TestCase):
    def test_buckets_share_row_objects_not_copied_dataframes(self) -> None:
        tax = get_decarbonization_taxonomy()
        rows = [
            record_for_path(REPRESENTATIVE_PATHS[0], record_id="opc"),
            record_for_path(REPRESENTATIVE_PATHS[1], record_id="amine"),
        ]
        canonical = _project(rows, list(RECORD_FIELDS))
        buckets = _bucket_rows_by_node(canonical, tax)
        root = tax.root().path
        self.assertGreater(len(buckets[root]), 0)
        self.assertIs(buckets[root][0], canonical[0] if buckets[root][0]["record_id"] == canonical[0]["record_id"] else canonical[1])
        # Every bucketed row is the same object as some canonical row.
        canon_ids = {id(r) for r in canonical}
        for group in buckets.values():
            for row in group:
                self.assertIn(id(row), canon_ids)

    def test_write_still_emits_tree_without_retaining_all_node_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            rows = [record_for_path(REPRESENTATIVE_PATHS[i], record_id=f"r{i}") for i in range(5)]
            result = write_hierarchical_export(root, rows, fieldnames=RECORD_FIELDS)
            self.assertTrue(result["ok"])
            self.assertGreaterEqual(result["total_csvs_generated"], 1)


class RankStreamingTests(unittest.TestCase):
    def test_rank_streams_screening_jsonl_and_caps_top_n(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "7-30 results"
            meta = out / "metadata"
            meta.mkdir(parents=True)
            path = meta / "screening_results.jsonl"
            import json

            with path.open("w", encoding="utf-8") as handle:
                for i in range(40):
                    handle.write(
                        json.dumps(
                            {
                                "corpus_index": i,
                                "paper_id": f"p{i}",
                                "title": f"cement scm study {i}",
                                "abstract": "rice husk ash concrete",
                                "is_relevant": True,
                                "screening_score": i / 40,
                            }
                        )
                        + "\n"
                    )
            with mock.patch(
                "pipeline.cementitious.stages.read_jsonl",
                side_effect=AssertionError("rank must stream, not read_jsonl the full file"),
            ):
                plan = rank_and_plan_extraction(output_dir=out, top_n=7, extract_shard_size=3)
            self.assertEqual(plan["candidate_count"], 7)
            self.assertEqual(plan["shard_count"], 3)


class OomClassifierTests(unittest.TestCase):
    def test_timeout_and_node_fail_are_not_oom(self) -> None:
        self.assertEqual(classify_job_failure(state="TIMEOUT")["kind"], "non_memory")
        self.assertEqual(classify_job_failure(state="NODE_FAIL")["kind"], "non_memory")
        self.assertEqual(
            classify_job_failure(completion_status="soft_memory_stop")["kind"],
            "soft_memory_stop",
        )


class DescribeTelemetrySourceTests(unittest.TestCase):
    def test_prefers_pilot_1000_path_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "results"
            p1000 = root / "concrete_decarbonization_pilot_1000" / "7-30 results"
            p1000.mkdir(parents=True)
            info = describe_pilot_telemetry_source(results_root=str(root))
            self.assertTrue(info["present"])
            self.assertEqual(info["profile"], "pilot-1000")
            self.assertIsNone(info["warning"])


if __name__ == "__main__":
    unittest.main()
