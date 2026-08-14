#!/usr/bin/env python3
"""Export checkpoint, FORCE overwrite, and resume-without-duplication tests."""

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

from pipeline.cementitious.corpus_shards import materialize_corpus_shards
from pipeline.cementitious.final_metadata import FinalMetadataError
from pipeline.cementitious.resume_stages import stage_is_complete
from pipeline.cementitious.shard_io import iter_jsonl, write_marker
from pipeline.cementitious.stages import export_final
from pipeline.cementitious.workflow_launch import build_launch_config, validate_launch_config
from pipeline.decarb_testlib import launch_env, paper_record, write_pickle


class ExportCheckpointTests(unittest.TestCase):
    def test_export_complete_written_only_after_successful_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "7-30 results"
            out.mkdir()
            with mock.patch(
                "pipeline.cementitious.stages.export_taxonomy_partitions",
                return_value={"exported_record_count": 0},
            ), mock.patch(
                "pipeline.cementitious.final_metadata.write_final_metadata",
                return_value={"overall_status": "pass", "run_manifest_path": "m", "validation_report_path": "v"},
            ), mock.patch(
                "pipeline.cementitious.resource_calibration.write_resource_usage_summary",
                return_value={},
            ), mock.patch(
                "pipeline.cementitious.resource_calibration.build_full_run_recommendations",
                return_value={},
            ):
                export_final(output_dir=out)
            self.assertTrue((out / "checkpoints" / "export.complete").is_file())

    def test_failed_export_does_not_create_export_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "7-30 results"
            out.mkdir()
            with mock.patch(
                "pipeline.cementitious.stages.export_taxonomy_partitions",
                return_value={"exported_record_count": 0},
            ), mock.patch(
                "pipeline.cementitious.final_metadata.write_final_metadata",
                return_value={
                    "overall_status": "fail",
                    "validation_report_path": str(out / "metadata" / "validation_report.json"),
                },
            ):
                with self.assertRaises(FinalMetadataError):
                    export_final(output_dir=out)
            self.assertFalse((out / "checkpoints" / "export.complete").is_file())

    def test_existing_completed_export_blocks_overwrite_unless_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=False, env=env)
            marker = Path(cfg.output_dir) / "checkpoints" / "export.complete"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("done\n", encoding="utf-8")
            blocked = validate_launch_config(cfg, environ=env)
            self.assertTrue(any("export.complete" in e and "FORCE=1" in e for e in blocked))
            env_force = dict(env)
            env_force["FORCE"] = "1"
            with mock.patch.dict(os.environ, env_force, clear=False):
                forced = build_launch_config("pilot", dry_run=False, env=env_force)
            self.assertTrue(forced.force)
            errors = validate_launch_config(forced, environ=env_force)
            self.assertFalse(any("export.complete" in e for e in errors))


class ResumeBehaviorTests(unittest.TestCase):
    def test_marker_alone_is_not_sufficient_for_known_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "checkpoints").mkdir(parents=True)
            write_marker(out / "checkpoints" / "screen.complete")
            self.assertFalse(stage_is_complete(out, "screen", resume=True))
            (out / "metadata").mkdir()
            (out / "metadata" / "screening_results.jsonl").write_text(
                json.dumps({"paper_id": "p1", "is_relevant": True}) + "\n",
                encoding="utf-8",
            )
            self.assertTrue(stage_is_complete(out, "screen", resume=True))
            self.assertFalse(stage_is_complete(out, "screen", resume=True, force=True))
            self.assertFalse(stage_is_complete(out, "screen", resume=False))

    def test_corpus_shard_resume_does_not_duplicate_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "out"
            write_pickle(pkl, [paper_record(i) for i in range(7)])
            first = materialize_corpus_shards(input_path=pkl, output_dir=out, shard_size=3)
            second = materialize_corpus_shards(input_path=pkl, output_dir=out, shard_size=3)
            self.assertEqual(first["record_count"], 7)
            self.assertEqual(second["record_count"], 7)
            ids: list[str] = []
            for shard in first["shards"]:
                for row in iter_jsonl(Path(shard["record_shard_path"])):
                    ids.append(str(row.get("corpus_index")))
            self.assertEqual(len(ids), 7)
            self.assertEqual(len(set(ids)), 7)


if __name__ == "__main__":
    unittest.main()
