#!/usr/bin/env python3
"""Tests for one-line Cementitious Engaging pilot/full workflow launch."""

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

from pipeline.cementitious.workflow_launch import (
    PILOT_MAX_RECORDS,
    PILOT_RESULTS_SUFFIX,
    PILOT_TAXONOMY_SCOPE_ALL,
    PILOT_TAXONOMY_SCOPE_SMOKE,
    PILOT_WEB_LEAF,
    PILOT_WEB_PARENT,
    build_launch_config,
    build_workflow_dry_run,
    export_paths_for_leaves,
    redact_secrets,
    required_stage_names,
    taxonomy_summary,
    validate_launch_config,
    web_leaf_slugs,
)


def _env(tmp: Path, *, mode_bits: dict | None = None) -> dict[str, str]:
    pkl = tmp / "corpus.pkl"
    with pkl.open("wb") as handle:
        pickle.dump([{"title": "t", "abstract": "a", "doi": "10.1/x"}], handle)
    base = {
        "OPENAI_API_KEY": "sk-test-not-real",
        "TAVILY_API_KEY": "tvly-test-not-real",
        "PICKLE_PATH": str(pkl),
        "RESULTS_ROOT": str(tmp / "results"),
    }
    if mode_bits:
        base.update(mode_bits)
    return base


class PilotFullConfigTests(unittest.TestCase):
    def test_pilot_enables_lit_and_web_and_caps_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=True)
            self.assertTrue(cfg.literature_enabled)
            self.assertTrue(cfg.web_enabled)
            self.assertEqual(cfg.run_mode, "literature-and-web")
            self.assertEqual(cfg.max_records, PILOT_MAX_RECORDS)
            self.assertLessEqual(cfg.max_records, 50)
            self.assertEqual(cfg.workers, 1)
            self.assertEqual(cfg.array_max_concurrency, 1)
            self.assertIn(PILOT_RESULTS_SUFFIX, Path(cfg.results_root).parts)
            self.assertIn(PILOT_WEB_LEAF, cfg.selected_sub_subcategories)
            self.assertEqual(cfg.pilot_taxonomy_scope, PILOT_TAXONOMY_SCOPE_SMOKE)
            self.assertTrue(cfg.pilot_corpus_sampling)
            self.assertEqual(cfg.selected_subcategories, [PILOT_WEB_PARENT])
            behavior = cfg.as_public_dict()["pilot_behavior"]
            self.assertTrue(behavior["corpus_sampling"]["enabled"])
            self.assertTrue(behavior["taxonomy_restriction"]["enabled"])
            errors = validate_launch_config(cfg, environ=env)
            self.assertEqual(errors, [])

    def test_pilot_taxonomy_scope_all_keeps_record_cap_without_restricting_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp), mode_bits={"CEMENTITIOUS_PILOT_TAXONOMY_SCOPE": "all"})
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=True)
            self.assertEqual(cfg.max_records, PILOT_MAX_RECORDS)
            self.assertTrue(cfg.pilot_corpus_sampling)
            self.assertEqual(cfg.pilot_taxonomy_scope, PILOT_TAXONOMY_SCOPE_ALL)
            self.assertEqual(cfg.selected_subcategories, [])
            self.assertEqual(cfg.selected_sub_subcategories, [])
            self.assertGreaterEqual(len(web_leaf_slugs(cfg)), 50)

    def test_full_enables_lit_and_web_no_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True)
            self.assertIsNone(cfg.max_records)
            self.assertTrue(cfg.web_enabled)
            leaves = web_leaf_slugs(cfg)
            self.assertGreaterEqual(len(leaves), 50)
            errors = validate_launch_config(cfg, environ=env)
            self.assertEqual(errors, [])

    def test_full_rejects_record_cap_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp), mode_bits={"CEMENTITIOUS_MAX_RECORDS": "50"})
            with mock.patch.dict(os.environ, env, clear=False):
                with self.assertRaises(ValueError):
                    build_launch_config("full")

    def test_tavily_required_for_combined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            del env["TAVILY_API_KEY"]
            with mock.patch.dict(os.environ, env, clear=False):
                # Clear inherited TAVILY if any
                os.environ.pop("TAVILY_API_KEY", None)
                cfg = build_launch_config("pilot", dry_run=True)
            errors = validate_launch_config(cfg, environ={**env})
            self.assertTrue(any("TAVILY_API_KEY" in e for e in errors))

    def test_openai_required_unless_keyword_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            del env["OPENAI_API_KEY"]
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("OPENAI_API_KEY", None)
                cfg = build_launch_config("pilot", dry_run=True)
            errors = validate_launch_config(cfg, environ=env)
            self.assertTrue(any("OPENAI_API_KEY" in e for e in errors))
            env2 = {**env, "KEYWORD_ONLY": "1"}
            cfg.keyword_only = True
            errors2 = validate_launch_config(cfg, environ=env2)
            self.assertFalse(any("OPENAI_API_KEY" in e for e in errors2))


class TaxonomyExportParityTests(unittest.TestCase):
    def test_every_web_leaf_has_export_paths_and_exists_in_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True)
            summary = taxonomy_summary(cfg.taxonomy_path)
            tax_slugs = {child["slug"] for branch in summary["tree"] for child in branch["children"]}
            for slug in web_leaf_slugs(cfg):
                self.assertIn(slug, tax_slugs)
            paths = export_paths_for_leaves(cfg)
            self.assertEqual(set(paths), set(web_leaf_slugs(cfg)))
            for slug, p in paths.items():
                self.assertTrue(p["records_csv"].endswith(f"{slug}.csv"))
                self.assertTrue(p["citations_csv"].endswith(f"{slug}_citations.csv"))

    def test_full_processes_every_configured_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("full", dry_run=True)
            summary = taxonomy_summary(cfg.taxonomy_path)
            self.assertEqual(len(web_leaf_slugs(cfg)), summary["leaf_count"])


class OrchestrationGraphTests(unittest.TestCase):
    def test_required_stages_and_acyclic_export_depends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(Path(tmp))
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=True)
            dry = build_workflow_dry_run(cfg)
            for stage in required_stage_names():
                if stage == "plan_web_queries":
                    continue
                self.assertIn(stage, dry["stage_order"])
            self.assertTrue(dry["dependency_graph"]["acyclic"])
            self.assertTrue(dry["web_search_enabled"])
            self.assertTrue(dry["literature_enabled"])
            self.assertTrue(dry["export_job_depends_on_lit_and_web"])
            stages = {j["stage"] for j in dry["dependency_graph"]["jobs"]}
            self.assertIn("preprocess_plan", stages)
            self.assertIn("export", stages)
            export = next(j for j in dry["dependency_graph"]["jobs"] if j["stage"] == "export")
            # Export parents should eventually include lit+web merge path
            self.assertTrue(export["parent_job_ids"])

    def test_one_line_scripts_exist(self) -> None:
        root = REPO_ROOT / "scripts" / "engaging"
        canonical = root / "run_concrete_decarbonization_full_workflow.sh"
        alias = root / "run_cementitious_full_workflow.sh"
        self.assertTrue(canonical.is_file())
        self.assertTrue(alias.is_file())
        self.assertTrue((root / "run_cementitious_pilot.sh").is_file())
        text = canonical.read_text(encoding="utf-8")
        self.assertIn("--pilot", text)
        self.assertIn("--smoke", text)
        self.assertIn("--pilot-50", text)
        self.assertIn("--pilot-1000", text)
        self.assertIn("--full", text)
        self.assertIn("--dry-run", text)
        self.assertIn("730_cementitious_preprocess_plan.sh", text)
        self.assertIn("SKIP_LIT_PLAN=1", text)
        self.assertIn("run_730_results.sh", text)
        self.assertIn("render_preflight_summary", text)
        self.assertIn("Concrete Decarbonization", text)
        self.assertNotIn("OPENAI_API_KEY=", text.split("echo")[0])
        alias_text = alias.read_text(encoding="utf-8")
        self.assertIn("run_concrete_decarbonization_full_workflow.sh", alias_text)

    def test_secrets_redacted_from_manifest_payload(self) -> None:
        payload = redact_secrets(
            {"OPENAI_API_KEY": "sk-secret", "jobs": [{"cmd": "ok"}], "note": "sk-abcdefghijklmnopqrstuvwxyz"}
        )
        self.assertEqual(payload["OPENAI_API_KEY"], "<redacted>")
        self.assertEqual(payload["note"], "<redacted>")


class NoFullPickleInArrayScriptTests(unittest.TestCase):
    def test_screen_array_does_not_reference_pickle_load(self) -> None:
        text = (REPO_ROOT / "scripts" / "engaging" / "730_cementitious_screen_array.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("pickle.load", text)
        self.assertIn("record_shard", text.lower() + text)


if __name__ == "__main__":
    unittest.main()
