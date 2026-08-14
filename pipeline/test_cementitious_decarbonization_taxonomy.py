#!/usr/bin/env python3
"""Tests for the five-level Concrete Decarbonization taxonomy and hierarchical export."""

from __future__ import annotations

import csv
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

from pipeline.cementitious.decarbonization_taxonomy import (
    get_decarbonization_taxonomy,
    load_decarbonization_taxonomy,
    validate_decarbonization_payload,
)
from pipeline.cementitious.export_partitions import export_taxonomy_partitions
from pipeline.cementitious.hierarchical_export import (
    HierarchicalExportError,
    render_hierarchical_tree,
    write_hierarchical_export,
)
from pipeline.cementitious.paths import taxonomy_slugify
from pipeline.cementitious.schema import RECORD_FIELDS, normalize_record
from pipeline.cementitious.stages import export_final
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.cementitious.taxonomy_migration import coverage_report
from pipeline.test_cementitious_final_metadata import _seed_pilot_style_output
from pipeline.cementitious.paths import ensure_730_layout


def _full_record(**levels) -> dict:
    rec = {k: "" for k in RECORD_FIELDS}
    rec.update(
        {
            "record_id": levels.get("record_id", "r"),
            "taxonomy_level_0": "Concrete Decarbonization",
            "taxonomy_level_1": levels["l1"],
            "taxonomy_level_2": levels["l2"],
            "taxonomy_level_3": levels["l3"],
            "taxonomy_level_4": levels.get("l4", "N.A."),
            "source_id": "test:1",
            "citation": "doi:test",
            "evidence_text": "synthetic evidence for taxonomy export tests.",
            "extraction_confidence": "High",
            "taxonomy_confidence": "High",
            "classification_basis": "Explicit",
        }
    )
    rec["record_id"] = levels["record_id"]
    return rec


SYNTHETIC = [
    _full_record(
        record_id="A",
        l1="Cementitious Materials",
        l2="Conventional and Blended Cements",
        l3="Ordinary Portland Cement",
        l4="OPC",
    ),
    _full_record(
        record_id="B",
        l1="Cementitious Materials",
        l2="Cement-Plant Carbon Capture",
        l3="Chemical Absorption",
        l4="Amine Absorption",
    ),
    _full_record(
        record_id="C",
        l1="Aggregate Procurement",
        l2="Recycled Concrete Aggregates",
        l3="Treated RCA",
        l4="Carbonated RCA",
    ),
    _full_record(
        record_id="D",
        l1="Concrete Design",
        l2="Design for Durability",
        l3="Self-Healing Concrete",
        l4="Bacterial Self-Healing Concrete",
    ),
    _full_record(
        record_id="E",
        l1="Policy",
        l2="Green Public Procurement",
        l3="Embodied-Carbon Procurement Limits",
        l4="Buy Clean Programs",
    ),
]


class TaxonomyStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tax = get_decarbonization_taxonomy()

    def test_five_levels_and_counts(self) -> None:
        self.assertEqual(self.tax.count(0), 1)
        self.assertEqual(self.tax.count(1), 7)
        self.assertEqual(self.tax.count(2), 35)
        self.assertEqual(self.tax.count(3), 91)
        self.assertEqual(self.tax.count(4), 299)
        self.assertEqual(self.tax.count(), 433)
        self.assertEqual(self.tax.root().label, "Concrete Decarbonization")
        self.assertEqual(self.tax.root().level, 0)

    def test_cementitious_is_single_level_1(self) -> None:
        l1 = {n.label for n in self.tax.nodes_at(1)}
        self.assertIn("Cementitious Materials", l1)
        self.assertNotIn("Supplementary Cementitious Materials", l1)
        self.assertNotIn("Alternative Cementitious Materials", l1)
        self.assertNotIn("Alternative Supplementary Cementitious Materials", l1)
        self.assertNotIn("Inert Fillers", l1)
        cem = [n for n in self.tax.nodes_at(1) if n.slug == "cementitious_materials"][0]
        l2 = {c.label for c in self.tax.children(cem.path)}
        self.assertIn("Conventional Supplementary Cementitious Materials", l2)
        self.assertIn("Emerging Supplementary Cementitious Materials", l2)
        self.assertIn("Alternative Cement Chemistries", l2)
        self.assertIn("Inert and Low-Reactivity Fillers", l2)

    def test_parent_child_and_slug_uniqueness(self) -> None:
        payload = json.loads(Path(self.tax.source_path).read_text(encoding="utf-8"))
        errors = validate_decarbonization_payload(payload)
        self.assertEqual(errors, [])
        for node in self.tax.ordered_nodes():
            if node.level == 4:
                self.assertEqual(node.child_count, 0)
            if node.level > 0:
                parent = self.tax.nodes_by_path[node.parent_path]
                self.assertEqual(parent.level, node.level - 1)
            taxonomy_slugify(node.label)

    def test_cross_branch_ccs_not_collapsed(self) -> None:
        amine = self.tax.resolve_path_labels(
            [
                "Concrete Decarbonization",
                "Cementitious Materials",
                "Cement-Plant Carbon Capture",
                "Chemical Absorption",
                "Amine Absorption",
            ]
        )
        injection = self.tax.resolve_path_labels(
            [
                "Concrete Decarbonization",
                "Operation",
                "Carbon Capture and Utilization of Fresh Concrete",
                "Direct CO2 Injection",
                "Ready-Mix CO2 Injection",
            ]
        )
        self.assertNotEqual(amine.path, injection.path)
        self.assertEqual(amine.path_slugs[1], "cementitious_materials")
        self.assertEqual(injection.path_slugs[1], "operation")


class MigrationCoverageTests(unittest.TestCase):
    def test_every_old_leaf_is_mapped(self) -> None:
        report = coverage_report()
        self.assertTrue(report["complete"], report)
        self.assertEqual(report["old_leaf_count"], 58)
        self.assertEqual(report["unmapped_old_leaves"], [])
        self.assertEqual(report["invalid_new_paths"], [])

    def test_old_chemical_absorption_becomes_level_3(self) -> None:
        rec = normalize_record(
            {
                "record_id": "ccs1",
                "subcategory_slug": "cement_plant_carbon_capture",
                "sub_subcategory_slug": "chemical_absorption",
                "source_id": "x",
                "citation": "y",
                "evidence_text": "amine capture at a cement plant.",
            }
        )
        self.assertEqual(rec["taxonomy_level_1"], "Cementitious Materials")
        self.assertEqual(rec["taxonomy_level_2"], "Cement-Plant Carbon Capture")
        self.assertEqual(rec["taxonomy_level_3"], "Chemical Absorption")
        self.assertEqual(rec["taxonomy_level_4"], "N.A.")


class HierarchicalExportTests(unittest.TestCase):
    def test_synthetic_tree_and_conservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            result = write_hierarchical_export(root, SYNTHETIC, fieldnames=RECORD_FIELDS)
            self.assertTrue(result["ok"])
            export = root / "concrete_decarbonization_results"
            master_path = export / "concrete_decarbonization.csv"
            self.assertTrue(master_path.is_file())
            with master_path.open(newline="") as handle:
                master = list(csv.DictReader(handle))
            self.assertEqual({r["record_id"] for r in master}, {"A", "B", "C", "D", "E"})
            self.assertEqual(list(master[0].keys()), list(RECORD_FIELDS))

            cem = export / "cementitious_materials" / "cementitious_materials.csv"
            with cem.open(newline="") as handle:
                cem_rows = list(csv.DictReader(handle))
            self.assertEqual({r["record_id"] for r in cem_rows}, {"A", "B"})
            self.assertEqual(list(cem_rows[0].keys()), list(RECORD_FIELDS))

            opc = (
                export
                / "cementitious_materials"
                / "conventional_and_blended_cements"
                / "ordinary_portland_cement"
                / "opc.csv"
            )
            self.assertTrue(opc.is_file())
            with opc.open(newline="") as handle:
                opc_rows = list(csv.DictReader(handle))
            self.assertEqual([r["record_id"] for r in opc_rows], ["A"])

            na_parent = (
                export
                / "cementitious_materials"
                / "conventional_and_blended_cements"
                / "ordinary_portland_cement"
                / "ordinary_portland_cement.csv"
            )
            with na_parent.open(newline="") as handle:
                l3 = list(csv.DictReader(handle))
            self.assertEqual([r["record_id"] for r in l3], ["A"])

            # Record with N.A. L4 belongs in L3 but not L4.
            na_rec = dict(SYNTHETIC[1])
            na_rec["record_id"] = "B2"
            na_rec["taxonomy_level_4"] = "N.A."
            write_hierarchical_export(root, SYNTHETIC + [na_rec], fieldnames=RECORD_FIELDS)
            amine = (
                export
                / "cementitious_materials"
                / "cement_plant_carbon_capture"
                / "chemical_absorption"
                / "amine_absorption.csv"
            )
            chem = (
                export
                / "cementitious_materials"
                / "cement_plant_carbon_capture"
                / "chemical_absorption"
                / "chemical_absorption.csv"
            )
            with amine.open(newline="") as handle:
                amine_ids = {r["record_id"] for r in csv.DictReader(handle)}
            with chem.open(newline="") as handle:
                chem_ids = {r["record_id"] for r in csv.DictReader(handle)}
            self.assertIn("B", amine_ids)
            self.assertNotIn("B2", amine_ids)
            self.assertEqual(chem_ids, {"B", "B2"})

            # Empty L4 still emitted as header-only CSV.
            empty_l4 = (
                export
                / "end_of_life"
                / "end_of_life_carbonation"
                / "enhanced_concrete_carbonation"
                / "demolition_concrete_carbonation.csv"
            )
            self.assertTrue(empty_l4.is_file())
            self.assertTrue((export / "end_of_life" / "end_of_life.csv").is_file())

            manifest = json.loads(
                (root / "metadata" / "taxonomy_export_manifest.json").read_text()
            )
            self.assertEqual(manifest["total_canonical_records"], 6)
            self.assertEqual(manifest["level_4_nodes"], 299)
            self.assertTrue(any(n["zero_records"] and n["level"] == 4 for n in manifest["nodes"]))

            # Identical schemas
            sample = [
                master_path,
                cem,
                opc,
                export / "policy" / "policy.csv",
            ]
            headers = []
            for path in sample:
                with path.open(newline="") as handle:
                    headers.append(next(csv.reader(handle)))
            self.assertTrue(all(h == list(RECORD_FIELDS) for h in headers))

            tree = render_hierarchical_tree(root)
            self.assertIn("concrete_decarbonization.csv", tree)
            self.assertIn("ordinary_portland_cement/", tree)
            self.assertIn("opc.csv", tree)
            self.assertIn("buy_clean_programs.csv", tree)

    def test_no_export_duplicates_and_values_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_hierarchical_export(root, SYNTHETIC, fieldnames=RECORD_FIELDS)
            export = root / "concrete_decarbonization_results"
            with (export / "concrete_decarbonization.csv").open(newline="") as handle:
                master = {r["record_id"]: r for r in csv.DictReader(handle)}
            leaf = (
                export
                / "aggregate_procurement"
                / "recycled_concrete_aggregates"
                / "treated_rca"
                / "carbonated_rca.csv"
            )
            with leaf.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["record_id"], "C")
            for key in RECORD_FIELDS:
                self.assertEqual(rows[0][key], master["C"][key])

    def test_runtime_export_writes_hierarchical_and_compat(self) -> None:
        tax = get_taxonomy()
        rec = normalize_record(
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
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "merged.csv"
            with inp.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_FIELDS), extrasaction="ignore")
                writer.writeheader()
                writer.writerow(rec)
            out = Path(tmp) / "7-30 results"
            export_taxonomy_partitions(input_path=inp, output_dir=out)
            self.assertTrue((out / "all_records" / "cementitious_materials_all_records.csv").is_file())
            self.assertTrue(
                (out / "cementitious_materials_results" / "cementitious_materials_all_records.csv").is_file()
            )
            self.assertTrue(
                (out / "concrete_decarbonization_results" / "concrete_decarbonization.csv").is_file()
            )
            self.assertTrue((out / "metadata" / "taxonomy_export_manifest.json").is_file())
            self.assertTrue(
                (out / "metadata" / "cementitious_runtime_taxonomy_migration.json").is_file()
            )
            mig = json.loads(
                (out / "metadata" / "cementitious_runtime_taxonomy_migration.json").read_text()
            )
            self.assertTrue(mig["complete"])

    def test_export_complete_requires_hierarchical_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            records = _seed_pilot_style_output(root, n=1)
            layout = ensure_730_layout(root)
            with (layout["metadata"] / "merged_records.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
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
            self.assertTrue((root / "checkpoints" / "export.complete").is_file())
            self.assertTrue(
                (root / "concrete_decarbonization_results" / "concrete_decarbonization.csv").is_file()
            )
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch(
                    "pipeline.cementitious.export_partitions.write_hierarchical_export",
                    side_effect=HierarchicalExportError("boom"),
                ):
                    (root / "checkpoints" / "export.complete").unlink(missing_ok=True)
                    with self.assertRaises(HierarchicalExportError):
                        export_final(output_dir=root, force=True)
            self.assertFalse((root / "checkpoints" / "export.complete").is_file())


if __name__ == "__main__":
    unittest.main()
