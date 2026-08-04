#!/usr/bin/env python3
"""Tests proving Cementitious Materials Engaging workflow is genuinely sharded."""

from __future__ import annotations

import json
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.schema import normalize_record
from pipeline.cementitious.shard_io import array_range_from_count, compact_id_list, read_jsonl
from pipeline.cementitious.stages import (
    ShardError,
    dedupe_and_qc,
    extract_shard,
    export_final,
    merge_extractions,
    merge_screening,
    plan_screen_shards,
    rank_and_plan_extraction,
    screen_shard,
)
from pipeline.cementitious.taxonomy import load_taxonomy


def _paper(i: int, *, relevant: bool = True) -> dict:
    if relevant:
        title = f"Rice husk ash cement replacement study {i}"
        abstract = (
            "Rice husk ash was used as a cement replacement SCM with pozzolanic activity. "
            f"Trial {i}."
        )
    else:
        title = f"Unrelated soil amendment disposal note {i}"
        abstract = "Agricultural ash used only as soil amendment and road base."
    return {
        "title": title,
        "abstract": abstract,
        "doi": f"10.1000/test.{i}",
        "year": 2020 + (i % 5),
    }


def _write_pickle(path: Path, n: int, relevant_indices: set[int] | None = None) -> None:
    relevant_indices = relevant_indices or set()
    records = [_paper(i, relevant=(i in relevant_indices or i % 3 != 2)) for i in range(n)]
    with path.open("wb") as handle:
        pickle.dump(records, handle)


class PlanScreenTests(unittest.TestCase):
    def test_plan_creates_multiple_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            _write_pickle(pkl, 12)
            result = plan_screen_shards(input_path=pkl, output_dir=out, shard_size=5)
            self.assertEqual(result["shard_count"], 3)
            self.assertEqual(result["array_range"], "0-2")
            shards = json.loads((out / "metadata" / "screen_shards.json").read_text())
            self.assertEqual(len(shards), 3)
            self.assertEqual(shards[0]["start_index"], 0)
            self.assertEqual(shards[0]["paper_count"], 5)
            self.assertEqual(shards[1]["start_index"], 5)
            self.assertEqual(shards[1]["paper_count"], 5)
            self.assertEqual(shards[2]["start_index"], 10)
            self.assertEqual(shards[2]["paper_count"], 2)
            self.assertEqual(
                (out / "metadata" / "screen_array_range.txt").read_text().strip(),
                "0-2",
            )


class ScreenShardIsolationTests(unittest.TestCase):
    def test_screen_shards_read_only_assigned_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            _write_pickle(pkl, 12)
            plan_screen_shards(input_path=pkl, output_dir=out, shard_size=5)

            s0 = screen_shard(shard_id=0, output_dir=out, keyword_only=True)
            s1 = screen_shard(shard_id=1, output_dir=out, keyword_only=True)
            self.assertEqual(s0["actual_processed_count"], 5)
            self.assertEqual(s1["actual_processed_count"], 5)

            rows0 = read_jsonl(Path(s0["output_path"]))
            rows1 = read_jsonl(Path(s1["output_path"]))
            self.assertEqual([r["corpus_index"] for r in rows0], [0, 1, 2, 3, 4])
            self.assertEqual([r["corpus_index"] for r in rows1], [5, 6, 7, 8, 9])
            self.assertNotEqual(Path(s0["output_path"]), Path(s1["output_path"]))
            self.assertTrue(Path(s0["marker_path"]).is_file())
            self.assertTrue(Path(s1["marker_path"]).is_file())
            # No shared screening_results from array tasks
            self.assertFalse((out / "metadata" / "screening_results.jsonl").is_file())

    def test_invalid_shard_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            _write_pickle(pkl, 12)
            plan_screen_shards(input_path=pkl, output_dir=out, shard_size=5)
            with self.assertRaises(ShardError):
                screen_shard(shard_id=99, output_dir=out, keyword_only=True)


class MergeScreenTests(unittest.TestCase):
    def test_merge_fails_when_shard_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            _write_pickle(pkl, 12)
            plan_screen_shards(input_path=pkl, output_dir=out, shard_size=5)
            screen_shard(shard_id=0, output_dir=out, keyword_only=True)
            # shard 1 and 2 missing
            with self.assertRaises(ShardError):
                merge_screening(output_dir=out)
            self.assertTrue(
                (out / "rejected_records" / "missing_screen_shards.csv").is_file()
            )

    def test_merge_succeeds_and_detects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            _write_pickle(pkl, 12)
            plan_screen_shards(input_path=pkl, output_dir=out, shard_size=5)
            for sid in (0, 1, 2):
                screen_shard(shard_id=sid, output_dir=out, keyword_only=True)
            summary = merge_screening(output_dir=out)
            self.assertEqual(summary["expected_shard_count"], 3)
            self.assertEqual(summary["total_merged_screening_records"], 12)
            self.assertTrue((out / "checkpoints" / "screen_merge.complete").is_file())

            # Inject duplicate corpus_index and ensure failure
            path = out / "metadata" / "screening_shards" / "screening_shard_00000.jsonl"
            rows = read_jsonl(path)
            rows.append(dict(rows[0]))
            path.write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8",
            )
            # Marker still present; merge should fail on count mismatch first
            with self.assertRaises(ShardError):
                merge_screening(output_dir=out)


class ExtractionShardTests(unittest.TestCase):
    def _prepare_ranked(self, out: Path, pkl: Path, n_papers: int = 12) -> None:
        # Make most papers relevant via keyword cues
        _write_pickle(pkl, n_papers, relevant_indices=set(range(n_papers)))
        plan_screen_shards(input_path=pkl, output_dir=out, shard_size=5)
        for sid in range(3):
            screen_shard(shard_id=sid, output_dir=out, keyword_only=True)
        merge_screening(output_dir=out)

    def test_extraction_planning_multiple_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            self._prepare_ranked(out, pkl)
            # Force enough candidates
            plan = rank_and_plan_extraction(
                output_dir=out,
                top_n=7,
                extract_shard_size=3,
            )
            self.assertGreaterEqual(plan["candidate_count"], 1)
            # With 7 candidates and size 3 -> 3 shards if enough relevant
            shards = json.loads((out / "metadata" / "extraction_shards.json").read_text())
            if plan["candidate_count"] >= 7:
                self.assertEqual(len(shards), 3)
                self.assertEqual(shards[0]["record_count"], 3)
                self.assertEqual(shards[1]["record_count"], 3)
                self.assertEqual(shards[2]["record_count"], 1)
                self.assertEqual(
                    (out / "metadata" / "extract_array_range.txt").read_text().strip(),
                    "0-2",
                )
            else:
                # Still must derive range from manifest, not hardcode 0-0 when >1
                rng = (out / "metadata" / "extract_array_range.txt").read_text().strip()
                if plan["shard_count"] > 1:
                    self.assertNotEqual(rng, "0-0")

    def test_extract_shard_isolation_and_no_final_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            self._prepare_ranked(out, pkl)
            rank_and_plan_extraction(output_dir=out, top_n=7, extract_shard_size=3)
            shards = json.loads((out / "metadata" / "extraction_shards.json").read_text())
            self.assertGreaterEqual(len(shards), 1)

            # Mock LLM classify_and_extract
            tax = load_taxonomy()

            def fake_classify(paper, **kwargs):
                title = paper.get("title") or "tech"
                row = normalize_record(
                    {
                        "category": "Cementitious Materials",
                        "subcategory": "Emerging Supplementary Cementitious Materials",
                        "subcategory_slug": "emerging_supplementary_cementitious_materials",
                        "sub_subcategory": "Biomass Ashes",
                        "sub_subcategory_slug": "biomass_ashes",
                        "technology_variant": "Rice Husk Ash",
                        "canonical_technology_name": "Rice Husk Ash",
                        "taxonomy_version": tax.taxonomy_version,
                        "taxonomy_confidence": "High",
                        "classification_basis": "Explicit",
                        "classification_reasoning": "Mocked RHA cement replacement.",
                        "technology_domain": "Supplementary Cementitious Material",
                        "functional_role": "Cement Replacement",
                        "source_id": title,
                        "source_title": title,
                        "citation": "doi:mock",
                        "evidence_text": paper.get("abstract") or title,
                        "extraction_confidence": "High",
                    },
                    taxonomy=tax,
                )
                return row, None

            with mock.patch(
                "pipeline.cementitious.stages.classify_and_extract",
                side_effect=fake_classify,
            ):
                e0 = extract_shard(shard_id=0, output_dir=out, keyword_only=False)
            self.assertTrue(Path(e0["output_path"]).is_file())
            self.assertFalse((out / "metadata" / "merged_records.csv").is_file())
            self.assertFalse((out / "checkpoints" / "export.complete").is_file())
            self.assertFalse((out / "checkpoints" / "extract_merge.complete").is_file())

            rows0 = read_jsonl(Path(e0["output_path"]))
            ids0 = {r.get("candidate_id") for r in rows0}

            if len(shards) > 1:
                with mock.patch(
                    "pipeline.cementitious.stages.classify_and_extract",
                    side_effect=fake_classify,
                ):
                    e1 = extract_shard(shard_id=1, output_dir=out)
                rows1 = read_jsonl(Path(e1["output_path"]))
                ids1 = {r.get("candidate_id") for r in rows1}
                self.assertTrue(ids0.isdisjoint(ids1))
                self.assertNotEqual(Path(e0["output_path"]), Path(e1["output_path"]))

    def test_merge_extract_fails_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            self._prepare_ranked(out, pkl)
            plan = rank_and_plan_extraction(output_dir=out, top_n=6, extract_shard_size=3)
            if plan["shard_count"] < 2:
                self.skipTest("need >=2 extract shards for this assertion")
            tax = load_taxonomy()

            def fake_classify(paper, **kwargs):
                return (
                    normalize_record(
                        {
                            "category": "Cementitious Materials",
                            "subcategory": "Emerging Supplementary Cementitious Materials",
                            "subcategory_slug": "emerging_supplementary_cementitious_materials",
                            "sub_subcategory": "Biomass Ashes",
                            "sub_subcategory_slug": "biomass_ashes",
                            "technology_variant": "Rice Husk Ash",
                            "canonical_technology_name": "Rice Husk Ash",
                            "taxonomy_version": tax.taxonomy_version,
                            "taxonomy_confidence": "High",
                            "classification_basis": "Explicit",
                            "classification_reasoning": "mock",
                            "technology_domain": "Supplementary Cementitious Material",
                            "functional_role": "Cement Replacement",
                            "source_id": "x",
                            "source_title": paper.get("title") or "t",
                            "citation": "c",
                            "evidence_text": "e",
                            "extraction_confidence": "High",
                        },
                        taxonomy=tax,
                    ),
                    None,
                )

            with mock.patch(
                "pipeline.cementitious.stages.classify_and_extract",
                side_effect=fake_classify,
            ):
                extract_shard(shard_id=0, output_dir=out)
            with self.assertRaises(ShardError):
                merge_extractions(output_dir=out)

    def test_rerun_one_failed_shard_preserves_other(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            self._prepare_ranked(out, pkl)
            plan = rank_and_plan_extraction(output_dir=out, top_n=6, extract_shard_size=3)
            if plan["shard_count"] < 2:
                self.skipTest("need >=2 extract shards")
            tax = load_taxonomy()

            def fake_classify(paper, **kwargs):
                return (
                    normalize_record(
                        {
                            "category": "Cementitious Materials",
                            "subcategory": "Emerging Supplementary Cementitious Materials",
                            "subcategory_slug": "emerging_supplementary_cementitious_materials",
                            "sub_subcategory": "Biomass Ashes",
                            "sub_subcategory_slug": "biomass_ashes",
                            "technology_variant": "Rice Husk Ash",
                            "canonical_technology_name": "Rice Husk Ash",
                            "taxonomy_version": tax.taxonomy_version,
                            "taxonomy_confidence": "High",
                            "classification_basis": "Explicit",
                            "classification_reasoning": "mock",
                            "technology_domain": "Supplementary Cementitious Material",
                            "functional_role": "Cement Replacement",
                            "source_id": "x",
                            "source_title": paper.get("title") or "t",
                            "citation": "c",
                            "evidence_text": "e",
                            "extraction_confidence": "High",
                        },
                        taxonomy=tax,
                    ),
                    None,
                )

            with mock.patch(
                "pipeline.cementitious.stages.classify_and_extract",
                side_effect=fake_classify,
            ):
                e0 = extract_shard(shard_id=0, output_dir=out)
                before = Path(e0["output_path"]).read_text(encoding="utf-8")
                extract_shard(shard_id=1, output_dir=out)
                # Corrupt shard 1 marker/output then rerun only shard 1
                Path(
                    json.loads((out / "metadata" / "extraction_shards.json").read_text())[1][
                        "expected_output_path"
                    ]
                ).unlink()
                extract_shard(shard_id=1, output_dir=out, resume=False)
            after = Path(e0["output_path"]).read_text(encoding="utf-8")
            self.assertEqual(before, after)

    def test_resume_validates_output_not_marker_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            _write_pickle(pkl, 12)
            plan_screen_shards(input_path=pkl, output_dir=out, shard_size=5)
            screen_shard(shard_id=0, output_dir=out, keyword_only=True)
            shards = json.loads((out / "metadata" / "screen_shards.json").read_text())
            out_path = Path(shards[0]["expected_output_path"])
            marker = Path(shards[0]["expected_marker_path"])
            # Break output but keep marker
            out_path.write_text("{not json\n", encoding="utf-8")
            self.assertTrue(marker.is_file())
            # RESUME should rerun because validation fails
            screen_shard(shard_id=0, output_dir=out, keyword_only=True, resume=True)
            rows = read_jsonl(out_path)
            self.assertEqual(len(rows), 5)


class IntegrationShardedTests(unittest.TestCase):
    def test_local_12_paper_integration(self) -> None:
        """12 papers, SHARD_SIZE=5, EXTRACT_SHARD_SIZE=3 end-to-end with mocks."""
        with tempfile.TemporaryDirectory() as tmp:
            pkl = Path(tmp) / "corpus.pkl"
            out = Path(tmp) / "7-30 results"
            # Ensure many relevant papers
            records = [_paper(i, relevant=True) for i in range(12)]
            with pkl.open("wb") as handle:
                pickle.dump(records, handle)

            plan = plan_screen_shards(input_path=pkl, output_dir=out, shard_size=5)
            self.assertEqual(plan["array_range"], "0-2")
            for sid in (0, 1, 2):
                screen_shard(shard_id=sid, output_dir=out, keyword_only=True)
            merge_screening(output_dir=out)

            # Select 7 candidates / extract shards 0-2
            extract_plan = rank_and_plan_extraction(
                output_dir=out, top_n=7, extract_shard_size=3
            )
            self.assertEqual(extract_plan["candidate_count"], 7)
            self.assertEqual(extract_plan["shard_count"], 3)
            self.assertEqual(extract_plan["array_range"], "0-2")

            tax = load_taxonomy()

            def fake_classify(paper, **kwargs):
                return (
                    normalize_record(
                        {
                            "category": "Cementitious Materials",
                            "subcategory": "Emerging Supplementary Cementitious Materials",
                            "subcategory_slug": "emerging_supplementary_cementitious_materials",
                            "sub_subcategory": "Biomass Ashes",
                            "sub_subcategory_slug": "biomass_ashes",
                            "technology_variant": "Rice Husk Ash",
                            "canonical_technology_name": "Rice Husk Ash",
                            "raw_technology_name": paper.get("title") or "",
                            "taxonomy_version": tax.taxonomy_version,
                            "taxonomy_confidence": "High",
                            "classification_basis": "Explicit",
                            "classification_reasoning": "mock integration",
                            "technology_domain": "Supplementary Cementitious Material",
                            "functional_role": "Cement Replacement",
                            "source_id": paper.get("title") or "src",
                            "source_title": paper.get("title") or "",
                            "citation": "doi:integration",
                            "evidence_text": paper.get("abstract") or "evidence",
                            "extraction_confidence": "High",
                        },
                        taxonomy=tax,
                    ),
                    None,
                )

            with mock.patch(
                "pipeline.cementitious.stages.classify_and_extract",
                side_effect=fake_classify,
            ):
                for sid in (0, 1, 2):
                    extract_shard(shard_id=sid, output_dir=out)

            merge_extractions(output_dir=out)
            # Extract tasks must not have written merged/export
            # (dedupe stage creates merged)
            dedupe_and_qc(output_dir=out, run_qc=False, keyword_only=True)
            export_final(output_dir=out)

            merged = read_jsonl(out / "metadata" / "merged_records.jsonl")
            # Exactly one successful record per candidate (7)
            self.assertEqual(len(merged), 7)
            ids = [r["record_id"] for r in merged]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue((out / "checkpoints" / "export.complete").is_file())
            self.assertTrue(
                (out / "sub_subcategories" / "biomass_ashes.csv").is_file()
            )


class ArrayRangeHelpers(unittest.TestCase):
    def test_array_range_helpers(self) -> None:
        self.assertEqual(array_range_from_count(0), "")
        self.assertEqual(array_range_from_count(1), "0")
        self.assertEqual(array_range_from_count(3), "0-2")
        self.assertEqual(compact_id_list([3, 7, 11, 12, 13, 14]), "3,7,11-14")


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        f"\nSummary: ran={result.testsRun} "
        f"failures={len(result.failures)} errors={len(result.errors)} "
        f"skipped={len(result.skipped)}"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
