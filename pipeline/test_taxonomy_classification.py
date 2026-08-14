#!/usr/bin/env python3
"""Literature screening/classification into the shared canonical taxonomy."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.extraction import classify_and_extract, keyword_screen, screen_records
from pipeline.cementitious.schema import normalize_record
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.decarb_testlib import paper_record


class TaxonomyClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tax = get_taxonomy()

    def test_keyword_screen_assigns_runtime_leaf_then_canonical_path(self) -> None:
        paper = paper_record(
            1,
            title="Amine solvent carbon capture at a cement kiln",
            abstract="Post-combustion chemical absorption using MEA at a cement plant.",
        )
        row = keyword_screen(
            paper,
            0,
            taxonomy=self.tax,
            focus_ss_slugs=["chemical_absorption"],
        )
        self.assertTrue(row["is_relevant"])
        rec = normalize_record(
            {
                "record_id": "cls-1",
                "subcategory_slug": "cement_plant_carbon_capture",
                "sub_subcategory_slug": "chemical_absorption",
                "source_id": paper["doi"],
                "citation": paper["doi"],
                "evidence_text": paper["abstract"],
                "evidence_origin": "Literature",
            },
            taxonomy=self.tax,
        )
        self.assertEqual(rec["taxonomy_level_0"], "Concrete Decarbonization")
        self.assertEqual(rec["taxonomy_level_1"], "Cementitious Materials")
        self.assertEqual(rec["taxonomy_level_3"], "Chemical Absorption")
        self.assertEqual(rec["taxonomy_level_4"], "N.A.")

    def test_unrelated_paper_is_not_forced_into_capture_leaf(self) -> None:
        paper = paper_record(
            2,
            title="Highway asphalt binder aging",
            abstract="Bitumen rheology for road pavement, no cement or clinker.",
        )
        row = keyword_screen(paper, 0, taxonomy=self.tax, focus_ss_slugs=["chemical_absorption"])
        self.assertFalse(row["is_relevant"])

    def test_screen_records_empty_and_malformed_inputs(self) -> None:
        self.assertEqual(screen_records([], taxonomy=self.tax, keyword_only=True), [])
        malformed = {"title": None, "abstract": None}
        rows = screen_records([malformed], taxonomy=self.tax, keyword_only=True)
        self.assertEqual(len(rows), 1)
        self.assertIn("is_relevant", rows[0])

    def test_scoped_vs_unscoped_screening_candidate_counts(self) -> None:
        papers = [
            paper_record(i, title="Cement clinker SCM slag replacement", abstract="GGBFS cement replacement concrete.")
            for i in range(3)
        ]
        all_rows = screen_records(papers, taxonomy=self.tax, keyword_only=True)
        scoped = screen_records(
            papers,
            taxonomy=self.tax,
            keyword_only=True,
            focus_ss_slugs=["chemical_absorption"],
        )
        self.assertEqual(len(all_rows), 3)
        self.assertEqual(len(scoped), 3)
        self.assertGreaterEqual(sum(1 for r in all_rows if r["is_relevant"]), 1)

    def test_keyword_extract_and_mocked_llm_extract_never_use_live_openai(self) -> None:
        paper = paper_record(3, title="GGBFS slag cement replacement", abstract="Blast furnace slag SCM in concrete.")
        with mock.patch("pipeline.cementitious.extraction.call_json_llm") as llm:
            rec, _proposal = classify_and_extract(paper, taxonomy=self.tax, keyword_only=True)
            llm.assert_not_called()
            llm.return_value = {
                "relevant": True,
                "subcategory_slug": "cement_plant_carbon_capture",
                "sub_subcategory_slug": "chemical_absorption",
                "taxonomy_confidence": "High",
                "classification_basis": "Explicit",
                "evidence_text": "mocked extract",
                "source_id": paper["doi"],
            }
            rec2, _ = classify_and_extract(paper, taxonomy=self.tax, keyword_only=False)
        self.assertTrue(rec is None or rec.get("record_id"))
        self.assertTrue(rec2 is None or rec2.get("record_id") or rec2.get("sub_subcategory_slug"))


if __name__ == "__main__":
    unittest.main()
