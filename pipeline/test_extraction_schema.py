#!/usr/bin/env python3
"""Canonical extraction schema, normalization, and provenance field tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.schema import (
    RECORD_FIELDS,
    normalize_confidence,
    normalize_missing,
    normalize_record,
    validate_records,
)
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.decarb_testlib import canonical_record


REQUIRED_TAXONOMY = (
    "taxonomy_level_0",
    "taxonomy_level_1",
    "taxonomy_level_2",
    "taxonomy_level_3",
    "taxonomy_level_4",
)

PROJECT_FIELDS = (
    "company_or_organization",
    "project_name",
    "location",
    "project_year",
    "deployment_stage",
)
SOURCE_FIELDS = (
    "evidence_origin",
    "source_type",
    "source_title",
    "source_id",
    "source_url",
    "retrieval_timestamp",
    "organization_or_publisher",
)
PERFORMANCE_FIELDS = (
    "compressive_strength_value",
    "cement_replacement_percentage",
    "co2_reduction_value",
    "energy_penalty_value",
    "cost_value",
    "carbon_capture_rate",
)


class ExtractionSchemaTests(unittest.TestCase):
    def test_canonical_schema_includes_taxonomy_and_project_fields(self) -> None:
        for col in REQUIRED_TAXONOMY + PROJECT_FIELDS + SOURCE_FIELDS + PERFORMANCE_FIELDS:
            self.assertIn(col, RECORD_FIELDS)
        rec = normalize_record(canonical_record(record_id="schema-1"))
        for col in REQUIRED_TAXONOMY:
            self.assertTrue(rec[col])
        for col in RECORD_FIELDS:
            self.assertIn(col, rec)
        self.assertEqual(
            [k for k in RECORD_FIELDS if k.startswith("taxonomy_level_") and not k.endswith("_slug")],
            list(REQUIRED_TAXONOMY),
        )

    def test_missing_values_and_confidence_normalization(self) -> None:
        self.assertEqual(normalize_missing(None), "")
        self.assertEqual(normalize_missing("n/a"), "")
        self.assertEqual(normalize_missing(" unknown "), "")
        self.assertEqual(normalize_confidence("high"), "High")
        self.assertEqual(normalize_confidence("MEDIUM"), "Medium")
        self.assertEqual(normalize_confidence("nope"), "")
        rec = normalize_record(
            canonical_record(
                record_id="miss-1",
                compressive_strength_value="n/a",
                taxonomy_confidence="high",
            )
        )
        self.assertEqual(rec["compressive_strength_value"], "")
        self.assertEqual(rec["taxonomy_confidence"], "High")

    def test_numeric_fields_remain_strings_and_are_stripped(self) -> None:
        rec = normalize_record(
            canonical_record(
                record_id="num-1",
                co2_reduction_value=" 40 ",
                cost_value="1.5",
                energy_penalty_value="12",
            )
        )
        self.assertEqual(rec["co2_reduction_value"], "40")
        self.assertEqual(rec["cost_value"], "1.5")
        self.assertIsInstance(rec["co2_reduction_value"], str)

    def test_source_fields_not_lost_and_taxonomy_not_overwritten_when_present(self) -> None:
        rec = normalize_record(
            {
                "record_id": "prov-1",
                "evidence_origin": "Web",
                "source_type": "Government Website",
                "source_title": "DOE report",
                "source_url": "https://energy.gov/ccs",
                "organization_or_publisher": "DOE",
                "retrieval_timestamp": "2026-08-13T00:00:00+00:00",
                "taxonomy_level_0": "Concrete Decarbonization",
                "taxonomy_level_1": "Policy",
                "taxonomy_level_2": "Green Public Procurement",
                "taxonomy_level_3": "Embodied-Carbon Procurement Limits",
                "taxonomy_level_4": "Buy Clean Programs",
                "evidence_text": "Buy Clean procurement limit evidence.",
                "source_id": "web:1",
                "citation": "https://energy.gov/ccs",
            }
        )
        self.assertEqual(rec["source_title"], "DOE report")
        self.assertEqual(rec["source_url"], "https://energy.gov/ccs")
        self.assertEqual(rec["taxonomy_level_1"], "Policy")
        self.assertEqual(rec["taxonomy_level_4"], "Buy Clean Programs")
        self.assertNotEqual(rec["taxonomy_level_1"], "Cementitious Materials")

    def test_project_level_rows_remain_distinct(self) -> None:
        a = normalize_record(
            canonical_record(record_id="p1", project_name="Plant A", location="NO")
        )
        b = normalize_record(
            canonical_record(record_id="p2", project_name="Plant B", location="US")
        )
        self.assertNotEqual(a["record_id"], b["record_id"])
        self.assertNotEqual(a["project_name"], b["project_name"])
        result = validate_records([a, b], taxonomy=get_taxonomy())
        self.assertGreaterEqual(len(result.accepted), 2)


if __name__ == "__main__":
    unittest.main()
