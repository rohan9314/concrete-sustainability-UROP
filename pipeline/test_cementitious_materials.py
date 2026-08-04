#!/usr/bin/env python3
"""Unit and integration tests for the Cementitious Materials pipeline."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.dedupe import deduplicate_records
from pipeline.cementitious.export_partitions import export_taxonomy_partitions
from pipeline.cementitious.migrate_carbon_capture import (
    map_sub_subcategory,
    migrate_carbon_capture,
    migrate_carbon_capture_record,
    migrate_carbon_capture_record_detailed,
    mineralization_is_scm_compatible,
)
from pipeline.cementitious.paths import (
    get_730_results_dir,
    get_results_root,
    safe_partition_filename,
    sanitize_slug,
)
from pipeline.cementitious.schema import (
    RECORD_FIELDS,
    normalize_record,
    sort_records,
    validate_records,
)
from pipeline.cementitious.taxonomy import get_taxonomy, load_taxonomy, validate_taxonomy_payload


class TaxonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        get_taxonomy.cache_clear()
        self.tax = load_taxonomy()

    def test_taxonomy_loads(self) -> None:
        self.assertEqual(
            self.tax.taxonomy_version,
            "cementitious-materials-v1-2026-07-30",
        )
        self.assertEqual(len(self.tax.subcategories), 9)
        self.assertEqual(len(self.tax.sub_subcategories), 58)

    def test_slug_uniqueness(self) -> None:
        slugs = list(self.tax.subcategories) + list(self.tax.sub_subcategories)
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_parent_child_consistency(self) -> None:
        for slug, parent in self.tax.parent_of_sub_sub.items():
            self.assertIn(parent, self.tax.subcategories)
            self.assertEqual(self.tax.sub_subcategories[slug].parent, parent)

    def test_display_name_to_slug(self) -> None:
        self.assertEqual(
            self.tax.resolve_slug("Cement-Plant Carbon Capture", level="subcategory"),
            "cement_plant_carbon_capture",
        )
        self.assertEqual(
            self.tax.resolve_slug("chemical_absorption", level="sub_subcategory"),
            "chemical_absorption",
        )
        self.assertEqual(
            self.tax.resolve_slug("Chemical Absorption", level="sub_subcategory"),
            "chemical_absorption",
        )

    def test_validate_payload_rejects_duplicates(self) -> None:
        payload = {
            "taxonomy_version": "x",
            "category": {"display_name": "Cementitious Materials", "slug": "cementitious_materials"},
            "subcategories": [
                {
                    "slug": "a",
                    "display_name": "A",
                    "children": [
                        {"slug": "a", "display_name": "dup", "parent": "a"},
                    ],
                }
            ],
        }
        errors = validate_taxonomy_payload(payload)
        self.assertTrue(any("duplicate" in e for e in errors))


class PathTests(unittest.TestCase):
    def test_results_root_default(self) -> None:
        os.environ.pop("RESULTS_ROOT", None)
        root = get_results_root()
        self.assertTrue(str(root).endswith("results") or root.name == "results")
        out = get_730_results_dir(root)
        self.assertEqual(out.name, "7-30 results")

    def test_sanitize_slug_rejects_traversal(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_slug("../etc/passwd")
        with self.assertRaises(ValueError):
            sanitize_slug("foo/bar")

    def test_safe_partition_filename(self) -> None:
        self.assertEqual(safe_partition_filename("chemical_absorption"), "chemical_absorption.csv")
        with self.assertRaises(ValueError):
            safe_partition_filename("..")


class MigrationTests(unittest.TestCase):
    def test_deterministic_mappings(self) -> None:
        cases = [
            ("amine_absorption", "chemical_absorption"),
            ("solvent-based capture", "chemical_absorption"),
            ("cryogenic carbon capture", "cryogenic_carbon_capture"),
            ("oxyfuel", "oxy_fuel_combustion"),
            ("oxygen-enriched combustion", "oxy_fuel_combustion"),
            ("membrane separation", "membrane_separation"),
            ("Ca-looping", "calcium_looping"),
            ("LEILAC", "direct_separation"),
        ]
        for text, expected in cases:
            got = map_sub_subcategory(subcategory=text, technology_type=text)
            self.assertEqual(got, expected, msg=text)

    def test_migrate_record(self) -> None:
        raw = {
            "subcategory": "Solvent-based / amine absorption",
            "technology_type": "Aqueous Amine Solvent",
            "company_or_organization": "DemoCo",
            "project_name": "Demo Project",
            "source_title": "Demo Paper",
            "source_url_or_citation": "doi:10.1000/demo",
            "confidence": "High",
            "notes": "pilot amine capture at cement plant",
        }
        record, unmapped = migrate_carbon_capture_record(
            raw, methodology_slug="amine_absorption"
        )
        self.assertIsNone(unmapped)
        assert record is not None
        self.assertEqual(record["category"], "Cementitious Materials")
        self.assertEqual(record["subcategory_slug"], "cement_plant_carbon_capture")
        self.assertEqual(record["sub_subcategory_slug"], "chemical_absorption")

    def test_migrate_directory_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ccs.csv"
            with src.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "subcategory",
                        "technology_type",
                        "source_title",
                        "source_url_or_citation",
                        "confidence",
                        "notes",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "subcategory": "Membrane separation",
                        "technology_type": "Polymeric Membrane",
                        "source_title": "Mem Paper",
                        "source_url_or_citation": "doi:1",
                        "confidence": "Medium",
                        "notes": "",
                    }
                )
                writer.writerow(
                    {
                        "subcategory": "mineralization",
                        "technology_type": "Mineralization",
                        "source_title": "Min Paper",
                        "source_url_or_citation": "doi:2",
                        "confidence": "Low",
                        "notes": "CO2 curing of concrete specimens",
                    }
                )
            out = Path(tmp) / "7-30 results"
            report = migrate_carbon_capture(input_path=src, output_dir=out)
            self.assertEqual(report["migrated"], 1)
            self.assertEqual(report["pending_review"], 1)
            self.assertEqual(report["invalid"], 0)
            self.assertEqual(report["legacy_mineralization"], 1)
            self.assertTrue(
                (out / "metadata" / "legacy_mineralization_records.csv").is_file()
            )
            rejected = (
                out / "rejected_records" / "unmapped_carbon_capture_records.csv"
            ).read_text(encoding="utf-8")
            self.assertNotIn("doi:2", rejected)
            self.assertNotIn("Min Paper", rejected)


class MineralizationMigrationTests(unittest.TestCase):
    def test_scm_compatible_mineralization_maps_to_carbonated_waste_scm(self) -> None:
        raw = {
            "record_id": "min-scm-1",
            "subcategory": "mineralization",
            "methodology_slug": "mineralization",
            "technology_type": "Carbonated Steel Slag",
            "functional_role": "Cement Replacement",
            "notes": "Carbonated slag used as SCM cement replacement in concrete",
            "source_title": "Carbonated slag SCM study",
            "source_url_or_citation": "doi:10.1000/scm-min",
            "source_id": "src-scm-1",
            "confidence": "High",
        }
        self.assertTrue(mineralization_is_scm_compatible(raw))
        result = migrate_carbon_capture_record_detailed(raw)
        self.assertEqual(result.status, "migrated")
        assert result.record is not None
        self.assertEqual(
            result.record["subcategory_slug"],
            "emerging_supplementary_cementitious_materials",
        )
        self.assertEqual(
            result.record["sub_subcategory_slug"],
            "carbonated_waste_derived_scms",
        )
        self.assertNotEqual(
            result.record["subcategory_slug"],
            "cement_plant_carbon_capture",
        )
        self.assertEqual(result.record["record_id"], "min-scm-1")
        self.assertEqual(result.record["citation"], "doi:10.1000/scm-min")
        self.assertEqual(result.record["source_id"], "src-scm-1")
        assert result.legacy_mineralization is not None
        self.assertEqual(result.legacy_mineralization["migration_status"], "migrated_scm")

    def test_non_scm_mineralization_pending_review_not_rejected(self) -> None:
        raw = {
            "record_id": "min-cure-1",
            "subcategory": "mineralization",
            "technology_type": "CO2 curing",
            "functional_role": "Carbonation curing",
            "notes": "CO2 curing only of precast elements; sequestration only",
            "source_title": "Curing paper",
            "source_url_or_citation": "doi:10.1000/cure",
            "source_id": "src-cure",
        }
        self.assertFalse(mineralization_is_scm_compatible(raw))
        result = migrate_carbon_capture_record_detailed(raw)
        self.assertEqual(result.status, "pending_review")
        assert result.record is not None
        self.assertEqual(result.record["subcategory"], "Pending Taxonomy Review")
        self.assertNotIn(
            result.record["sub_subcategory_slug"],
            {
                "chemical_absorption",
                "cryogenic_carbon_capture",
                "oxy_fuel_combustion",
                "membrane_separation",
                "calcium_looping",
                "direct_separation",
            },
        )
        assert result.proposal is not None
        self.assertEqual(result.proposal["review_status"], "Pending Review")
        self.assertEqual(
            result.proposal["proposed_parent"],
            "Emerging Supplementary Cementitious Materials",
        )
        self.assertEqual(result.proposal["functional_role"], "Carbonation curing")
        self.assertEqual(result.record["citation"], "doi:10.1000/cure")

    def test_missing_functional_role_defaults_to_pending(self) -> None:
        raw = {
            "record_id": "min-norole",
            "subcategory": "mineralization",
            "technology_type": "Mineral carbonation",
            "notes": "CO2 mineralization of industrial residues",
            "source_title": "No role paper",
            "citation": "doi:10.1000/norole",
        }
        self.assertFalse(mineralization_is_scm_compatible(raw))
        result = migrate_carbon_capture_record_detailed(raw)
        self.assertEqual(result.status, "pending_review")
        assert result.proposal is not None
        self.assertIn(
            "lacks sufficient SCM",
            result.proposal["reason_existing_taxonomy_is_insufficient"],
        )

    def test_citation_and_identifiers_preserved_in_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "min.csv"
            with src.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "record_id",
                        "source_id",
                        "subcategory",
                        "technology_type",
                        "functional_role",
                        "notes",
                        "source_title",
                        "source_url_or_citation",
                        "source_url",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "record_id": "keep-id-1",
                        "source_id": "keep-src-1",
                        "subcategory": "mineralization",
                        "technology_type": "Carbonated fly ash",
                        "functional_role": "Pozzolanic SCM",
                        "notes": "carbonated fly ash cement replacement SCM",
                        "source_title": "FA paper",
                        "source_url_or_citation": "doi:10.1000/keep",
                        "source_url": "https://example.com/keep",
                    }
                )
                writer.writerow(
                    {
                        "record_id": "keep-id-2",
                        "source_id": "keep-src-2",
                        "subcategory": "mineralization",
                        "technology_type": "Mineralization",
                        "functional_role": "",
                        "notes": "aggregate only road base product",
                        "source_title": "Agg paper",
                        "source_url_or_citation": "doi:10.1000/agg",
                        "source_url": "https://example.com/agg",
                    }
                )
            out = Path(tmp) / "7-30 results"
            report = migrate_carbon_capture(input_path=src, output_dir=out)
            self.assertEqual(report["migrated"], 1)
            self.assertEqual(report["pending_review"], 1)
            self.assertEqual(report["invalid"], 0)
            self.assertEqual(report["legacy_mineralization"], 2)

            with (out / "metadata" / "legacy_mineralization_records.csv").open(
                encoding="utf-8"
            ) as handle:
                legacy = list(csv.DictReader(handle))
            self.assertEqual(len(legacy), 2)
            by_id = {r["preserved_record_id"]: r for r in legacy}
            self.assertEqual(by_id["keep-id-1"]["preserved_citation"], "doi:10.1000/keep")
            self.assertEqual(by_id["keep-id-2"]["preserved_source_id"], "keep-src-2")

            with (out / "metadata" / "migrated_carbon_capture_records.csv").open(
                encoding="utf-8"
            ) as handle:
                migrated = list(csv.DictReader(handle))
            self.assertEqual(migrated[0]["record_id"], "keep-id-1")
            self.assertEqual(migrated[0]["citation"], "doi:10.1000/keep")
            self.assertEqual(
                migrated[0]["sub_subcategory_slug"],
                "carbonated_waste_derived_scms",
            )

            with (out / "metadata" / "taxonomy_proposals.csv").open(
                encoding="utf-8"
            ) as handle:
                proposals = list(csv.DictReader(handle))
            self.assertEqual(len(proposals), 1)
            self.assertEqual(proposals[0]["source_record_id"], "keep-id-2")
            self.assertEqual(proposals[0]["review_status"], "Pending Review")

            rejected = (
                out / "rejected_records" / "unmapped_carbon_capture_records.csv"
            ).read_text(encoding="utf-8")
            self.assertNotIn("keep-id-1", rejected)
            self.assertNotIn("keep-id-2", rejected)
            self.assertNotIn("doi:10.1000/keep", rejected)


def _sample_records() -> list[dict]:
    tax = load_taxonomy()
    rows = []
    # Chemical absorption
    rows.append(
        {
            "record_id": "r1",
            "category": "Cementitious Materials",
            "subcategory": "Cement-Plant Carbon Capture",
            "subcategory_slug": "cement_plant_carbon_capture",
            "sub_subcategory": "Chemical Absorption",
            "sub_subcategory_slug": "chemical_absorption",
            "technology_variant": "Aqueous Amine Solvent",
            "canonical_technology_name": "Aqueous Amine Solvent",
            "taxonomy_version": tax.taxonomy_version,
            "taxonomy_confidence": "High",
            "classification_basis": "Explicit",
            "classification_reasoning": "Paper studies amine absorption at a cement plant.",
            "technology_domain": "Carbon Capture Process",
            "functional_role": "Carbon Capture System",
            "source_id": "paper:1",
            "source_title": "Amine CCS at Cement Plant",
            "publication_year": "2020",
            "citation": "doi:10.1000/amine",
            "evidence_text": "Amine solvent capture was applied to cement kiln flue gas.",
            "extraction_confidence": "High",
        }
    )
    # Biomass ash SCM
    rows.append(
        {
            "record_id": "r2",
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
            "classification_reasoning": "RHA evaluated as 20% cement replacement.",
            "technology_domain": "Supplementary Cementitious Material",
            "functional_role": "Cement Replacement",
            "source_id": "paper:2",
            "source_title": "Rice Husk Ash as SCM",
            "publication_year": "2019",
            "citation": "doi:10.1000/rha",
            "evidence_text": "Rice husk ash replaced 20% cement and showed pozzolanic activity.",
            "extraction_confidence": "High",
            "cement_replacement_percentage": "20",
        }
    )
    return rows


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        get_taxonomy.cache_clear()

    def test_full_partition_export_and_empty_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "merged.csv"
            with inp.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                for row in _sample_records():
                    writer.writerow(normalize_record(row))
            out = Path(tmp) / "7-30 results"
            summary = export_taxonomy_partitions(input_path=inp, output_dir=out)
            self.assertEqual(summary["accepted"], 2)
            # Required directories
            self.assertTrue((out / "all_records" / "cementitious_materials_all_records.csv").is_file())
            self.assertTrue((out / "all_records" / "citations_all.csv").is_file())
            self.assertTrue((out / "all_records" / "partition_summary.csv").is_file())
            self.assertTrue((out / "all_records" / "validation_report.json").is_file())
            self.assertTrue((out / "all_records" / "taxonomy_manifest.json").is_file())
            # Subcategory broader + sub-subcategory specific
            self.assertTrue(
                (out / "subcategories" / "cement_plant_carbon_capture.csv").is_file()
            )
            self.assertTrue(
                (out / "sub_subcategories" / "chemical_absorption.csv").is_file()
            )
            # Empty partitions still exist
            self.assertTrue((out / "sub_subcategories" / "biocements.csv").is_file())
            with (out / "sub_subcategories" / "biocements.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows, [])
            # Citation partitions
            self.assertTrue(
                (
                    out
                    / "citations"
                    / "subcategories"
                    / "cement_plant_carbon_capture_citations.csv"
                ).is_file()
            )
            self.assertTrue(
                (
                    out
                    / "citations"
                    / "sub_subcategories"
                    / "chemical_absorption_citations.csv"
                ).is_file()
            )
            # Chemical absorption has exactly one record
            with (out / "sub_subcategories" / "chemical_absorption.csv").open(
                encoding="utf-8"
            ) as handle:
                chem = list(csv.DictReader(handle))
            self.assertEqual(len(chem), 1)
            # Broader CCS subcategory has that record
            with (out / "subcategories" / "cement_plant_carbon_capture.csv").open(
                encoding="utf-8"
            ) as handle:
                ccs = list(csv.DictReader(handle))
            self.assertEqual(len(ccs), 1)
            # All 9 subcategory files
            self.assertEqual(len(list((out / "subcategories").glob("*.csv"))), 9)
            # All 58 sub-subcategory files
            self.assertEqual(len(list((out / "sub_subcategories").glob("*.csv"))), 58)

    def test_selective_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "merged.csv"
            with inp.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                for row in _sample_records():
                    writer.writerow(normalize_record(row))
            out = Path(tmp) / "7-30 results"
            export_taxonomy_partitions(
                input_path=inp,
                output_dir=out,
                subcategory="cement_plant_carbon_capture",
            )
            with (out / "subcategories" / "cement_plant_carbon_capture.csv").open(
                encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            export_taxonomy_partitions(
                input_path=inp,
                output_dir=out,
                sub_subcategory="Chemical Absorption",
            )
            with (out / "sub_subcategories" / "chemical_absorption.csv").open(
                encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)

    def test_invalid_parent_child_rejected(self) -> None:
        bad = normalize_record(
            {
                "record_id": "bad1",
                "category": "Cementitious Materials",
                "subcategory": "Cement-Plant Carbon Capture",
                "subcategory_slug": "cement_plant_carbon_capture",
                "sub_subcategory": "Biomass Ashes",
                "sub_subcategory_slug": "biomass_ashes",
                "taxonomy_version": "cementitious-materials-v1-2026-07-30",
                "source_id": "x",
                "citation": "y",
                "evidence_text": "z",
                "taxonomy_confidence": "High",
            }
        )
        result = validate_records([bad])
        self.assertEqual(len(result.accepted), 0)
        self.assertEqual(len(result.invalid_taxonomy), 1)

    def test_deterministic_ordering(self) -> None:
        rows = [normalize_record(r) for r in _sample_records()]
        # Reverse then sort
        ordered = sort_records(list(reversed(rows)))
        self.assertEqual(ordered[0]["subcategory_slug"], "cement_plant_carbon_capture")
        self.assertEqual(ordered[1]["subcategory_slug"], "emerging_supplementary_cementitious_materials")


class DedupeTests(unittest.TestCase):
    def test_exact_duplicate_removed(self) -> None:
        a = normalize_record(_sample_records()[0])
        b = normalize_record(_sample_records()[0])
        b["record_id"] = "r1_dup"
        kept, audit = deduplicate_records([a, b])
        self.assertEqual(len(kept), 1)
        self.assertTrue(any(r["duplicate_status"] == "Exact Duplicate Removed" for r in audit))


class SmokeLayoutTests(unittest.TestCase):
    def test_smoke_export_layout(self) -> None:
        """Smoke-style check without requiring corpus pickle or LLM."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["RESULTS_ROOT"] = tmp
            get_taxonomy.cache_clear()
            inp = Path(tmp) / "merged.csv"
            with inp.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                for row in _sample_records():
                    writer.writerow(normalize_record(row))
            out = get_730_results_dir()
            summary = export_taxonomy_partitions(input_path=inp, output_dir=out)
            report = json.loads(
                (out / "all_records" / "validation_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["total_accepted"], 2)
            self.assertGreaterEqual(summary["partition_file_count"], 9 + 58)
            # No unsafe path characters in filenames
            for path in out.rglob("*.csv"):
                self.assertNotIn("..", path.name)
                self.assertNotIn("/", path.name)


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
