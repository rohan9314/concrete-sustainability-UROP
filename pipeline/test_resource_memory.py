#!/usr/bin/env python3
"""Resource recommendation, OOM distinction, and memory-safe sharding tests."""

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

from pipeline.cementitious.corpus_shards import materialize_corpus_shards
from pipeline.cementitious.memory import (
    STAGE_MEMORY_PROFILES,
    cementitious_batch_size,
    cementitious_workers,
)
from pipeline.cementitious.resource_calibration import (
    OOM_EXIT_CODES,
    UTILIZATION_WARN_PCT,
    _scan_job_states,
    build_full_run_recommendations,
    estimate_full_run_peak_mb,
    load_telemetry_rows,
    validate_pilot_calibration,
    write_resource_usage_summary,
)
from pipeline.decarb_testlib import paper_record, write_json, write_pickle
from pipeline.test_cementitious_resource_calibration import _write_tel


class UtilizationAndOomTests(unittest.TestCase):
    def test_oom_exit_codes_are_distinct_from_unrelated_failures(self) -> None:
        self.assertEqual(OOM_EXIT_CODES, {"137", "OUT_OF_MEMORY"})
        self.assertIn("137", OOM_EXIT_CODES)
        self.assertNotIn("1", OOM_EXIT_CODES)
        self.assertNotIn("TIMEOUT", OOM_EXIT_CODES)
        self.assertNotIn("9", OOM_EXIT_CODES)

    def test_maxrss_below_half_near_80_and_over_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tel(root, "screen", 200, req=8.0)  # ~2.4%
            _write_tel(root, "extract", 6550, req=8.0)  # ~80%
            _write_tel(root, "export", 9000, req=8.0)  # >100%
            rows = {r["stage"]: r for r in load_telemetry_rows(root)}
            self.assertLess(rows["screen"]["utilization_pct_of_request"], 50)
            self.assertGreaterEqual(rows["extract"]["utilization_pct_of_request"], UTILIZATION_WARN_PCT - 1)
            self.assertGreater(rows["export"]["utilization_pct_of_request"], 100)
            reco = build_full_run_recommendations(root)
            self.assertGreater(
                reco["stages"]["extract"]["recommended_slurm_memory_gb"],
                reco["stages"]["extract"]["pilot_requested_memory_gb"],
            )

    def test_oom_137_signal_9_timeout_and_node_failure_are_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            meta = root / "metadata"
            meta.mkdir(parents=True)
            write_json(meta / "job_a.json", {"ExitCode": "137", "stage": "screen"})
            write_json(meta / "job_b.json", {"completion_status": "OUT_OF_MEMORY"})
            _write_tel(root, "web_search", 100, status="killed")
            _write_tel(root, "web_extract", 100, status="timeout")
            _write_tel(root, "dedupe_qc", 100, status="node_failure")
            problems = _scan_job_states(root)
            joined = " ".join(problems)
            self.assertIn("137", joined)
            self.assertTrue(any("OUT_OF_MEMORY" in p or "OOM" in p or "definite OOM" in p for p in problems))
            self.assertTrue(any("web_search" in p and "killed" in p for p in problems))
            self.assertFalse(any("timeout" in p.lower() and "web_extract" in p for p in problems))
            self.assertFalse(any("node_failure" in p for p in problems))
            verdict = validate_pilot_calibration(root, require_all_stages=False)
            oom_errors = [
                e
                for e in verdict["errors"]
                if "137" in e or "OOM" in e or "OUT_OF_MEMORY" in e
            ]
            self.assertTrue(oom_errors)
            self.assertFalse(any("killed" in e and "definite" in e for e in verdict["errors"]))
            self.assertFalse(any("timeout" in e or "node_failure" in e for e in oom_errors))
            self.assertTrue(
                any("cgroup kill" in w or "killed" in w for w in verdict["warnings"])
            )

    def test_signal_9_is_not_definite_oom_without_corroboration(self) -> None:
        from pipeline.cementitious.resource_calibration import classify_job_failure

        uncorr = classify_job_failure(completion_status="killed")
        self.assertFalse(uncorr["is_oom"])
        self.assertEqual(uncorr["kind"], "possible_cgroup_kill")
        corr = classify_job_failure(
            completion_status="killed", utilization_pct=90.0, requested_mem_gb=8
        )
        self.assertTrue(corr["is_oom"])
        definite = classify_job_failure(exit_code="137")
        self.assertTrue(definite["definite"])
        timeout = classify_job_failure(state="TIMEOUT")
        self.assertEqual(timeout["kind"], "non_memory")


class RecommendationAndShardingTests(unittest.TestCase):
    def test_preprocess_vs_shard_local_scaling(self) -> None:
        pre, _, why = estimate_full_run_peak_mb("preprocess_plan", 18000)
        scr, _, why_s = estimate_full_run_peak_mb("screen", 400, shard_size_pilot=50, shard_size_full=10000)
        self.assertEqual(pre, 18000)
        self.assertGreater(scr, 400)
        self.assertIn("pickle", why.lower())
        self.assertIn("shard", why_s.lower())
        self.assertTrue(STAGE_MEMORY_PROFILES["preprocess_plan"].loads_full_pickle)
        self.assertFalse(STAGE_MEMORY_PROFILES["screen"].loads_full_pickle)

    def test_worker_and_batch_caps_are_bounded(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CEMENTITIOUS_WORKERS": "99", "CEMENTITIOUS_MAX_WORKERS": "4", "CEMENTITIOUS_BATCH_SIZE": "9999"},
            clear=False,
        ):
            self.assertEqual(cementitious_workers(), 4)
            self.assertEqual(cementitious_batch_size(), 500)

    def test_memory_safe_shards_never_reload_full_pickle_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "c.pkl"
            out = Path(tmp) / "out"
            write_pickle(pkl, [paper_record(i) for i in range(11)])
            manifest = materialize_corpus_shards(input_path=pkl, output_dir=out, shard_size=4)
            self.assertEqual(manifest["shard_count"], 3)
            self.assertEqual(manifest["record_count"], 11)
            for shard in manifest["shards"]:
                self.assertTrue(Path(shard["record_shard_path"]).is_file())
                self.assertLessEqual(shard["paper_count"], 4)
            summary = write_resource_usage_summary(out)
            self.assertIn("row_count", summary)


if __name__ == "__main__":
    unittest.main()
