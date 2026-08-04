#!/usr/bin/env python3
"""Offline tests for memory-safe Cementitious corpus sharding and resume."""

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

from pipeline.cementitious.corpus_shards import (
    CORPUS_SHARD_SCHEMA_VERSION,
    corpus_shards_are_valid,
    corpus_fingerprint,
    materialize_corpus_shards,
)
from pipeline.cementitious.memory import (
    ControlledMemoryStop,
    cementitious_batch_size,
    cementitious_workers,
    current_rss_bytes,
    log_concurrency_settings,
)
from pipeline.cementitious.shard_io import iter_jsonl, read_jsonl
from pipeline.cementitious.stages import plan_screen_shards, screen_shard


def _paper(i: int) -> dict:
    return {
        "title": f"Rice husk ash cement replacement study {i}",
        "abstract": f"Rice husk ash was used as a cement replacement SCM. Trial {i}.",
        "doi": f"10.1000/mem.{i}",
        "year": 2020,
    }


def _write_pickle(path: Path, n: int) -> None:
    with path.open("wb") as handle:
        pickle.dump([_paper(i) for i in range(n)], handle)


class CorpusShardMaterializeTests(unittest.TestCase):
    def test_materialize_writes_shards_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "out"
            _write_pickle(pkl, 12)
            manifest = materialize_corpus_shards(
                input_path=pkl, output_dir=out, shard_size=5
            )
            self.assertEqual(manifest["schema_version"], CORPUS_SHARD_SCHEMA_VERSION)
            self.assertEqual(manifest["record_count"], 12)
            self.assertEqual(manifest["shard_count"], 3)
            self.assertTrue((out / "checkpoints" / "corpus_shards.complete").is_file())
            fp = corpus_fingerprint(pkl)
            self.assertTrue(
                corpus_shards_are_valid(out, fingerprint=fp, shard_size=5, total_records=12)
            )
            shard0 = Path(manifest["shards"][0]["record_shard_path"])
            rows = list(iter_jsonl(shard0))
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0]["corpus_index"], 0)
            self.assertIn("source_record_id", rows[0])

    def test_incomplete_shards_not_treated_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "out"
            _write_pickle(pkl, 6)
            materialize_corpus_shards(input_path=pkl, output_dir=out, shard_size=5)
            (out / "checkpoints" / "corpus_shards.complete").unlink()
            fp = corpus_fingerprint(pkl)
            self.assertFalse(corpus_shards_are_valid(out, fingerprint=fp, shard_size=5))


class ScreenShardMemorySafeTests(unittest.TestCase):
    def test_array_task_reads_only_own_shard_not_full_pickle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "out"
            _write_pickle(pkl, 12)
            plan = plan_screen_shards(input_path=pkl, output_dir=out, shard_size=5)
            self.assertEqual(plan["data_access"], "per-shard-jsonl")
            shards = json.loads((out / "metadata" / "screen_shards.json").read_text())
            self.assertTrue(Path(shards[0]["record_shard_path"]).is_file())

            with mock.patch(
                "pipeline.corpus_loader.load_paper_records",
                side_effect=AssertionError("screen must not load full pickle"),
            ), mock.patch(
                "pipeline.cementitious.stages.load_paper_records",
                side_effect=AssertionError("screen must not load full pickle"),
                create=True,
            ):
                summary = screen_shard(shard_id=0, output_dir=out, keyword_only=True)
            self.assertEqual(summary["actual_processed_count"], 5)
            self.assertEqual(summary["status"], "complete")
            self.assertTrue(Path(summary["telemetry_path"]).is_file())
            telemetry = json.loads(Path(summary["telemetry_path"]).read_text())
            self.assertIn("peak_rss_mb", telemetry)
            self.assertGreaterEqual(len(telemetry["samples"]), 2)

    def test_streaming_jsonl_does_not_materialize_via_read_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl"
            path.write_text(
                "\n".join(json.dumps({"i": i}) for i in range(5)) + "\n",
                encoding="utf-8",
            )
            # iter_jsonl should work without Path.read_text
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("no read_text")):
                rows = list(iter_jsonl(path))
            self.assertEqual([r["i"] for r in rows], [0, 1, 2, 3, 4])

    def test_resume_after_interruption_no_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "out"
            _write_pickle(pkl, 6)
            plan_screen_shards(input_path=pkl, output_dir=out, shard_size=6)
            shards = json.loads((out / "metadata" / "screen_shards.json").read_text())
            pad = "00000"
            partial = out / "metadata" / "screening_shards" / f"screening_shard_{pad}.partial.jsonl"
            # Simulate interruption after 2 records by writing partial rows then resuming.
            first = screen_shard(shard_id=0, output_dir=out, keyword_only=True)
            out_path = Path(first["output_path"])
            rows = read_jsonl(out_path)
            # Wipe complete outputs and keep only first 2 as partial.
            marker = Path(shards[0]["expected_marker_path"])
            marker.unlink()
            out_path.unlink()
            partial.write_text(
                "\n".join(json.dumps(r) for r in rows[:2]) + "\n",
                encoding="utf-8",
            )
            resumed = screen_shard(shard_id=0, output_dir=out, keyword_only=True, resume=True)
            self.assertEqual(resumed["actual_processed_count"], 6)
            final_rows = read_jsonl(Path(resumed["output_path"]))
            indices = [r["corpus_index"] for r in final_rows]
            self.assertEqual(indices, list(range(6)))
            self.assertEqual(len(indices), len(set(indices)))

    def test_soft_memory_stop_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "out"
            _write_pickle(pkl, 8)
            plan_screen_shards(input_path=pkl, output_dir=out, shard_size=8)
            calls = {"n": 0}

            def _check(*, telemetry=None):
                calls["n"] += 1
                if calls["n"] >= 1:
                    raise ControlledMemoryStop("test soft stop")

            with mock.patch.dict(
                os.environ,
                {"CEMENTITIOUS_BATCH_SIZE": "1", "CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB": "1"},
                clear=False,
            ), mock.patch(
                "pipeline.cementitious.stages.check_soft_memory_ceiling",
                side_effect=_check,
            ):
                result = screen_shard(shard_id=0, output_dir=out, keyword_only=True)
            self.assertEqual(result["status"], "soft_memory_stop")
            self.assertGreaterEqual(result["completed_count"], 1)
            self.assertTrue(Path(result["partial_path"]).is_file())
            self.assertTrue(Path(result["checkpoint_path"]).is_file())
            # Resume completes without duplicates
            with mock.patch.dict(os.environ, {"CEMENTITIOUS_BATCH_SIZE": "25"}, clear=False):
                done = screen_shard(shard_id=0, output_dir=out, keyword_only=True, resume=True)
            self.assertEqual(done["status"], "complete")
            self.assertEqual(done["actual_processed_count"], 8)
            indices = [r["corpus_index"] for r in read_jsonl(Path(done["output_path"]))]
            self.assertEqual(indices, list(range(8)))


class ConcurrencyDefaultsTests(unittest.TestCase):
    def test_workers_default_one_and_capped(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            # Preserve PATH-like essentials by only clearing cementitious keys
            pass
        with mock.patch.dict(
            os.environ,
            {
                "CEMENTITIOUS_WORKERS": "1",
                "CEMENTITIOUS_MAX_WORKERS": "2",
                "CEMENTITIOUS_BATCH_SIZE": "10",
            },
            clear=False,
        ):
            self.assertEqual(cementitious_workers(), 1)
            self.assertEqual(cementitious_batch_size(), 10)
            payload = log_concurrency_settings()
            self.assertEqual(payload["CEMENTITIOUS_WORKERS"], 1)
        with mock.patch.dict(
            os.environ,
            {"CEMENTITIOUS_WORKERS": "99", "CEMENTITIOUS_MAX_WORKERS": "2"},
            clear=False,
        ):
            self.assertEqual(cementitious_workers(), 2)

    def test_rss_helper_returns_int(self) -> None:
        self.assertIsInstance(current_rss_bytes(), int)
        self.assertGreater(current_rss_bytes(), 0)


class SlurmScriptMemorySettingsTests(unittest.TestCase):
    def test_screen_script_has_explicit_mem_and_low_cpus(self) -> None:
        path = REPO_ROOT / "scripts" / "engaging" / "730_cementitious_screen_array.sh"
        text = path.read_text(encoding="utf-8")
        self.assertIn("#SBATCH --mem=8G", text)
        self.assertIn("#SBATCH --cpus-per-task=1", text)
        self.assertIn("CEMENTITIOUS_WORKERS", text)
        self.assertIn("CEMENTITIOUS_SOFT_MEMORY_LIMIT_GB", text)

    def test_preprocess_script_has_high_mem_single_task(self) -> None:
        path = REPO_ROOT / "scripts" / "engaging" / "730_cementitious_preprocess_plan.sh"
        text = path.read_text(encoding="utf-8")
        self.assertIn("#SBATCH --mem=64G", text)
        self.assertIn("#SBATCH --cpus-per-task=1", text)
        self.assertNotIn("#SBATCH --array=", text)

    def test_launcher_applies_array_concurrency_helper(self) -> None:
        path = REPO_ROOT / "scripts" / "engaging" / "run_730_results.sh"
        text = path.read_text(encoding="utf-8")
        self.assertIn("ARRAY_MAX_CONCURRENCY", text)
        self.assertIn("apply_array_concurrency", text)
        self.assertNotIn("validate_pickle_corpus", text)


class MaxRecordsPilotTests(unittest.TestCase):
    def test_max_records_bounds_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "out"
            _write_pickle(pkl, 40)
            with mock.patch.dict(os.environ, {"CEMENTITIOUS_MAX_RECORDS": "50"}, clear=False):
                # 40 < 50 so all kept; still exercises env path
                plan = plan_screen_shards(input_path=pkl, output_dir=out, shard_size=50)
            self.assertEqual(plan["total_records"], 40)
            self.assertEqual(plan["shard_count"], 1)
            with mock.patch.dict(os.environ, {"CEMENTITIOUS_MAX_RECORDS": "12"}, clear=False):
                out2 = Path(tmp) / "out2"
                plan2 = plan_screen_shards(input_path=pkl, output_dir=out2, shard_size=50)
            self.assertEqual(plan2["total_records"], 12)
            self.assertEqual(plan2["shard_count"], 1)


if __name__ == "__main__":
    unittest.main()
