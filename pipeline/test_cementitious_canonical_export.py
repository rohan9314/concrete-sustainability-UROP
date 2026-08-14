#!/usr/bin/env python3
"""Tests for the canonical user-facing Cementitious Materials export layout."""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.canonical_user_export import (
    CanonicalExportError,
    render_user_facing_tree,
    user_facing_master_path,
    validate_canonical_user_export_tree,
    write_canonical_user_export,
)
from pipeline.cementitious.export_partitions import export_taxonomy_partitions
from pipeline.cementitious.paths import ensure_730_layout, sanitize_slug
from pipeline.cementitious.schema import RECORD_FIELDS, normalize_record
from pipeline.cementitious.stages import export_final
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.test_cementitious_final_metadata import _seed_pilot_style_output


FIELDS = ("record_id", "subcategory_slug", "sub_subcategory_slug", "value")


def _row(rid: str, cat: str, sub: str, value: str = "x") -> dict[str, str]:
    return {
        "record_id": rid,
        "subcategory_slug": cat,
        "sub_subcategory_slug": sub,
        "value": value,
    }


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class CanonicalUserExportTests(unittest.TestCase):
    def test_master_and_nested_category_subcategory_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            rows = [
                _row("r1", "category_a", "subcategory_a1", "1"),
                _row("r2", "category_a", "subcategory_a2", "2"),
                _row("r3", "category_b", "subcategory_b1", "3"),
            ]
            result = write_canonical_user_export(root, rows, fieldnames=FIELDS)
            self.assertTrue(result["ok"])
            export_root = root / "cementitious_materials_results"
            master = _read(export_root / "cementitious_materials_all_records.csv")
            self.assertEqual(len(master), 3)
            self.assertEqual(list(master[0].keys()), list(FIELDS))

            cat_a = _read(export_root / "category_csvs" / "category_a.csv")
            cat_b = _read(export_root / "category_csvs" / "category_b.csv")
            self.assertEqual({r["record_id"] for r in cat_a}, {"r1", "r2"})
            self.assertEqual({r["record_id"] for r in cat_b}, {"r3"})
            self.assertEqual(list(cat_a[0].keys()), list(FIELDS))

            a1 = _read(
                export_root / "subcategory_csvs" / "category_a" / "subcategory_a1.csv"
            )
            a2 = _read(
                export_root / "subcategory_csvs" / "category_a" / "subcategory_a2.csv"
            )
            b1 = _read(
                export_root / "subcategory_csvs" / "category_b" / "subcategory_b1.csv"
            )
            self.assertEqual([r["record_id"] for r in a1], ["r1"])
            self.assertEqual([r["record_id"] for r in a2], ["r2"])
            self.assertEqual([r["record_id"] for r in b1], ["r3"])
            self.assertFalse((export_root / "subcategory_csvs" / "subcategory_a1.csv").exists())

            cat_rows = len(cat_a) + len(cat_b)
            self.assertEqual(cat_rows, len(master))
            self.assertEqual({r["record_id"] for r in a1 + a2}, {r["record_id"] for r in cat_a})
            self.assertEqual({r["record_id"] for r in b1}, {r["record_id"] for r in cat_b})
            self.assertEqual(validate_canonical_user_export_tree(root, fieldnames=list(FIELDS)), [])

            tree = render_user_facing_tree(root)
            self.assertIn("cementitious_materials_all_records.csv", tree)
            self.assertIn("category_a.csv", tree)
            self.assertIn("subcategory_a1.csv", tree)

    def test_identical_schemas_and_no_export_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                _row("r1", "category_a", "subcategory_a1"),
                _row("r2", "category_b", "subcategory_b1"),
            ]
            write_canonical_user_export(root, rows, fieldnames=FIELDS)
            export_root = root / "cementitious_materials_results"
            paths = [export_root / "cementitious_materials_all_records.csv"]
            paths.extend(sorted((export_root / "category_csvs").glob("*.csv")))
            paths.extend(sorted((export_root / "subcategory_csvs").glob("*/*.csv")))
            headers = []
            all_ids = []
            for path in paths:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    headers.append(list(reader.fieldnames or []))
                    all_ids.extend(r["record_id"] for r in reader if path.parent.name == "category_csvs")
            self.assertTrue(all(h == list(FIELDS) for h in headers))
            self.assertEqual(sorted(all_ids), ["r1", "r2"])
            self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_zero_record_omits_empty_category_and_subcategory_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_canonical_user_export(root, [], fieldnames=FIELDS)
            export_root = root / "cementitious_materials_results"
            master = _read(export_root / "cementitious_materials_all_records.csv")
            self.assertEqual(master, [])
            self.assertEqual(list((export_root / "category_csvs").glob("*.csv")), [])
            nested = list((export_root / "subcategory_csvs").glob("*/*.csv")) if (
                export_root / "subcategory_csvs"
            ).exists() else []
            self.assertEqual(nested, [])
            self.assertEqual(validate_canonical_user_export_tree(root, fieldnames=list(FIELDS)), [])

    def test_missing_category_kept_in_master_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                _row("r1", "category_a", "subcategory_a1"),
                _row("r2", "", "subcategory_a1"),
            ]
            with self.assertRaises(CanonicalExportError) as ctx:
                write_canonical_user_export(root, rows, fieldnames=FIELDS)
            self.assertIn("missing user-facing category", str(ctx.exception))
            export_root = root / "cementitious_materials_results"
            master = _read(export_root / "cementitious_materials_all_records.csv")
            self.assertEqual({r["record_id"] for r in master}, {"r1", "r2"})
            unassigned = _read(export_root / "unassigned_taxonomy.csv")
            self.assertEqual([r["record_id"] for r in unassigned], ["r2"])
            cat_a = _read(export_root / "category_csvs" / "category_a.csv")
            self.assertEqual([r["record_id"] for r in cat_a], ["r1"])
            self.assertFalse((export_root / "category_csvs" / ".csv").exists())

    def test_missing_subcategory_kept_in_category_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [_row("r1", "category_a", "")]
            with self.assertRaises(CanonicalExportError):
                write_canonical_user_export(root, rows, fieldnames=FIELDS)
            export_root = root / "cementitious_materials_results"
            cat_a = _read(export_root / "category_csvs" / "category_a.csv")
            self.assertEqual([r["record_id"] for r in cat_a], ["r1"])
            nested = list((export_root / "subcategory_csvs").glob("*/*.csv")) if (
                export_root / "subcategory_csvs"
            ).exists() else []
            self.assertEqual(nested, [])
            unassigned = _read(export_root / "unassigned_taxonomy.csv")
            self.assertEqual([r["record_id"] for r in unassigned], ["r1"])

    def test_filesystem_safe_slugs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [_row("r1", "Category A", "Sub Category 1")]
            write_canonical_user_export(root, rows, fieldnames=FIELDS)
            export_root = root / "cementitious_materials_results"
            self.assertEqual(sanitize_slug("Category A"), "category_a")
            self.assertTrue((export_root / "category_csvs" / "category_a.csv").is_file())
            self.assertTrue(
                (
                    export_root
                    / "subcategory_csvs"
                    / "category_a"
                    / "sub_category_1.csv"
                ).is_file()
            )
            for path in export_root.rglob("*.csv"):
                self.assertNotIn("..", path.name)
                self.assertNotIn("/", path.name)

    def test_unsafe_slug_does_not_escape_export_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [_row("r1", "../evil", "ok")]
            with self.assertRaises(CanonicalExportError):
                write_canonical_user_export(root, rows, fieldnames=FIELDS)
            self.assertFalse((root / "evil.csv").exists())
            self.assertFalse((root.parent / "evil.csv").exists())

    def test_overwrite_replaces_stale_category_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_canonical_user_export(
                root,
                [
                    _row("r1", "category_a", "subcategory_a1"),
                    _row("r2", "category_b", "subcategory_b1"),
                ],
                fieldnames=FIELDS,
            )
            write_canonical_user_export(
                root,
                [_row("r9", "category_a", "subcategory_a1", "new")],
                fieldnames=FIELDS,
                force=True,
            )
            export_root = root / "cementitious_materials_results"
            self.assertFalse((export_root / "category_csvs" / "category_b.csv").exists())
            self.assertFalse(
                (export_root / "subcategory_csvs" / "category_b" / "subcategory_b1.csv").exists()
            )
            master = _read(export_root / "cementitious_materials_all_records.csv")
            self.assertEqual([r["record_id"] for r in master], ["r9"])
            self.assertEqual(master[0]["value"], "new")

    def test_export_does_not_dedupe_or_transform_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [_row("r1", "category_a", "subcategory_a1", "  keep  ")]
            write_canonical_user_export(root, rows, fieldnames=FIELDS)
            master = _read(root / "cementitious_materials_results" / "cementitious_materials_all_records.csv")
            self.assertEqual(master[0]["value"], "  keep  ")


class ExportPartitionsUserFacingTests(unittest.TestCase):
    def test_taxonomy_export_writes_user_facing_from_same_master(self) -> None:
        tax = get_taxonomy()
        recs = []
        recs.append(
            normalize_record(
                {
                    "record_id": "r1",
                    "category": "Cementitious Materials",
                    "subcategory": tax.subcategories["cement_plant_carbon_capture"].display_name,
                    "subcategory_slug": "cement_plant_carbon_capture",
                    "sub_subcategory": tax.sub_subcategories["chemical_absorption"].display_name,
                    "sub_subcategory_slug": "chemical_absorption",
                    "canonical_technology_name": "Amine",
                    "taxonomy_version": tax.taxonomy_version,
                    "taxonomy_confidence": "High",
                    "classification_basis": "Explicit",
                    "classification_reasoning": "explicit",
                    "technology_domain": "Carbon Capture Process",
                    "functional_role": "Carbon Capture System",
                    "source_id": "paper:1",
                    "source_title": "t",
                    "citation": "doi:1",
                    "evidence_text": "Amine solvent capture was applied to cement kiln flue gas.",
                    "extraction_confidence": "High",
                }
            )
        )
        recs.append(
            normalize_record(
                {
                    "record_id": "r2",
                    "category": "Cementitious Materials",
                    "subcategory": tax.subcategories[
                        "emerging_supplementary_cementitious_materials"
                    ].display_name,
                    "subcategory_slug": "emerging_supplementary_cementitious_materials",
                    "sub_subcategory": tax.sub_subcategories["biomass_ashes"].display_name,
                    "sub_subcategory_slug": "biomass_ashes",
                    "canonical_technology_name": "RHA",
                    "taxonomy_version": tax.taxonomy_version,
                    "taxonomy_confidence": "High",
                    "classification_basis": "Explicit",
                    "classification_reasoning": "rha",
                    "technology_domain": "Supplementary Cementitious Material",
                    "functional_role": "Cement Replacement",
                    "source_id": "paper:2",
                    "source_title": "t2",
                    "citation": "doi:2",
                    "evidence_text": "Rice husk ash replaced 20% cement and showed pozzolanic activity.",
                    "extraction_confidence": "High",
                }
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "merged.csv"
            with inp.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                for row in recs:
                    writer.writerow(row)
            out = Path(tmp) / "7-30 results"
            summary = export_taxonomy_partitions(input_path=inp, output_dir=out)
            self.assertEqual(summary["accepted"], 2)
            user_master = _read(user_facing_master_path(out))
            internal_master = _read(
                out / "all_records" / "cementitious_materials_all_records.csv"
            )
            self.assertEqual(
                [r["record_id"] for r in user_master],
                [r["record_id"] for r in internal_master],
            )
            self.assertEqual(list(user_master[0].keys()), list(RECORD_FIELDS))
            self.assertTrue(
                (
                    out
                    / "cementitious_materials_results"
                    / "category_csvs"
                    / "cement_plant_carbon_capture.csv"
                ).is_file()
            )
            self.assertTrue(
                (
                    out
                    / "cementitious_materials_results"
                    / "subcategory_csvs"
                    / "cement_plant_carbon_capture"
                    / "chemical_absorption.csv"
                ).is_file()
            )
            # Internal empty leaf still exists; user-facing omits it.
            self.assertTrue((out / "sub_subcategories" / "biocements.csv").is_file())
            self.assertFalse(
                (
                    out
                    / "cementitious_materials_results"
                    / "subcategory_csvs"
                    / "alternative_cement_chemistries"
                    / "biocements.csv"
                ).exists()
            )
            self.assertEqual(len(list((out / "subcategories").glob("*.csv"))), 9)
            self.assertEqual(
                len(list((out / "cementitious_materials_results" / "category_csvs").glob("*.csv"))),
                2,
            )


class ExportCompleteGateTests(unittest.TestCase):
    def test_export_final_writes_user_facing_before_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            records = _seed_pilot_style_output(root, n=2)
            layout = ensure_730_layout(root)
            with (layout["metadata"] / "merged_records.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                for row in records:
                    writer.writerow(row)
            env = {"RUN_MODE": "literature-only", "WORKFLOW_MODE": "full"}
            for name in (
                "plan_web_queries.complete",
                "web_search_merge.complete",
                "web_extract_merge.complete",
                "merge_literature_web.complete",
            ):
                (layout["checkpoints"] / name).unlink(missing_ok=True)
            with mock.patch.dict(os.environ, env, clear=False):
                summary = export_final(output_dir=root, force=True)
            self.assertEqual(summary.get("final_validation_status"), "pass")
            self.assertTrue(user_facing_master_path(root).is_file())
            self.assertTrue((root / "checkpoints" / "export.complete").is_file())
            cat = _read(
                root
                / "cementitious_materials_results"
                / "category_csvs"
                / "cement_plant_carbon_capture.csv"
            )
            self.assertEqual(len(cat), 2)

    def test_failed_user_export_does_not_write_export_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            records = _seed_pilot_style_output(root, n=1)
            layout = ensure_730_layout(root)
            with (layout["metadata"] / "merged_records.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                for row in records:
                    writer.writerow(row)
            env = {"RUN_MODE": "literature-only", "WORKFLOW_MODE": "full"}
            for name in (
                "plan_web_queries.complete",
                "web_search_merge.complete",
                "web_extract_merge.complete",
                "merge_literature_web.complete",
            ):
                (layout["checkpoints"] / name).unlink(missing_ok=True)
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch(
                    "pipeline.cementitious.export_partitions.write_canonical_user_export",
                    side_effect=CanonicalExportError("boom"),
                ):
                    with self.assertRaises(CanonicalExportError):
                        export_final(output_dir=root, force=True)
            self.assertFalse((root / "checkpoints" / "export.complete").is_file())


if __name__ == "__main__":
    unittest.main()
