#!/usr/bin/env python3
"""Literature corpus loading, caps, sampling, and screening (no live OpenAI)."""

from __future__ import annotations

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

from pipeline.cementitious.extraction import keyword_screen, screen_records
from pipeline.cementitious.runner import RunConfig, _sample_records, build_plan
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.cementitious.workflow_launch import PILOT_MAX_RECORDS, build_launch_config
from pipeline.corpus_loader import PaperDatabaseLoadError, load_paper_records
from pipeline.decarb_testlib import launch_env, paper_record, write_pickle
from pipeline.record_utils import record_dedupe_key


class CorpusLoadingTests(unittest.TestCase):
    def tearDown(self) -> None:
        import pipeline.corpus_loader as cl

        cl._cached_records = None
        cl._cached_path = None

    def test_load_pickle_and_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.pkl"
            write_pickle(path, [paper_record(i) for i in range(4)])
            import pipeline.corpus_loader as cl

            cl._cached_records = None
            cl._cached_path = None
            rows = load_paper_records(path)
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["doi"], "10.1000/test.0")
            with self.assertRaises(PaperDatabaseLoadError):
                cl._cached_records = None
                cl._cached_path = None
                load_paper_records(Path(tmp) / "missing.pkl")

    def test_malformed_pickle_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.pkl"
            path.write_text("not a pickle", encoding="utf-8")
            import pipeline.corpus_loader as cl

            cl._cached_records = None
            cl._cached_path = None
            with self.assertRaises(PaperDatabaseLoadError):
                load_paper_records(path)


class SamplingAndCapTests(unittest.TestCase):
    def test_deterministic_sampling_with_seed(self) -> None:
        records = [paper_record(i) for i in range(20)]
        a = _sample_records(records, 5, seed=7)
        b = _sample_records(records, 5, seed=7)
        c = _sample_records(records, 5, seed=8)
        self.assertEqual([r["doi"] for r in a], [r["doi"] for r in b])
        self.assertNotEqual([r["doi"] for r in a], [r["doi"] for r in c])
        self.assertEqual(len(a), 5)

    def test_sample_size_larger_than_corpus_returns_all(self) -> None:
        records = [paper_record(i) for i in range(3)]
        out = _sample_records(records, 50, seed=1)
        self.assertEqual(len(out), 3)

    def test_pilot_record_cap_is_fifty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = launch_env(Path(tmp), extra={"CEMENTITIOUS_MAX_RECORDS": "50"})
            with mock.patch.dict(os.environ, env, clear=False):
                cfg = build_launch_config("pilot", dry_run=True, env=env)
            self.assertEqual(cfg.max_records, PILOT_MAX_RECORDS)
            self.assertTrue(cfg.literature_enabled)


class ScreeningAndFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tax = get_taxonomy()

    def test_screening_and_candidate_counts(self) -> None:
        papers = [paper_record(i) for i in range(5)]
        papers.append(
            paper_record(
                99,
                title="Unrelated soil science",
                abstract="Agricultural soil amendment only, road base aggregate.",
            )
        )
        rows = screen_records(papers, taxonomy=self.tax, keyword_only=True)
        self.assertEqual(len(rows), 6)
        relevant = [r for r in rows if r["is_relevant"]]
        self.assertGreaterEqual(len(relevant), 1)
        self.assertLessEqual(len(relevant), 6)

    def test_missing_abstract_and_malformed_record(self) -> None:
        row = keyword_screen({"title": "Cement SCM", "abstract": ""}, 0, taxonomy=self.tax)
        self.assertIn("is_relevant", row)
        row2 = keyword_screen({}, 1, taxonomy=self.tax)
        self.assertFalse(row2["is_relevant"] and not (row2.get("title") or row2.get("abstract")))

    def test_duplicate_paper_keys_match(self) -> None:
        a = paper_record(1)
        b = dict(a)
        self.assertEqual(record_dedupe_key(a), record_dedupe_key(b))
        c = paper_record(2)
        self.assertNotEqual(record_dedupe_key(a), record_dedupe_key(c))

    def test_empty_candidate_set(self) -> None:
        self.assertEqual(screen_records([], taxonomy=self.tax, keyword_only=True), [])

    def test_literature_only_and_combined_plans(self) -> None:
        tax = get_taxonomy()
        lit = build_plan(RunConfig(mode="literature-only", planning=True), tax)
        self.assertEqual(lit["mode"], "literature-only")
        combined = build_plan(RunConfig(mode="literature-and-web", planning=True), tax)
        self.assertEqual(combined["mode"], "literature-and-web")

    def test_keyword_only_never_calls_openai(self) -> None:
        papers = [paper_record(0)]
        with mock.patch("pipeline.cementitious.extraction.call_json_llm") as llm:
            rows = screen_records(papers, taxonomy=self.tax, keyword_only=True)
        llm.assert_not_called()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["screening_mode"], "keyword")

    def test_llm_screening_uses_mocked_openai_payload(self) -> None:
        papers = [paper_record(0)]
        with mock.patch(
            "pipeline.cementitious.extraction.call_json_llm",
            return_value={
                "relevant": True,
                "relevance_confidence": "High",
                "reason": "mocked",
                "negative_match": "",
            },
        ) as llm:
            rows = screen_records(papers, taxonomy=self.tax, keyword_only=False, concurrency=1)
        llm.assert_called()
        self.assertTrue(rows[0]["is_relevant"])
        self.assertEqual(rows[0]["screening_mode"], "llm")


if __name__ == "__main__":
    unittest.main()
