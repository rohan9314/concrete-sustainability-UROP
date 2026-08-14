#!/usr/bin/env python3
"""Hierarchical five-level CSV export tests (synthetic dataframe, no network)."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy
from pipeline.cementitious.hierarchical_export import write_hierarchical_export
from pipeline.cementitious.paths import (
    DECARBONIZATION_EXPORT_DIRNAME,
    DECARBONIZATION_MASTER_FILENAME,
    TAXONOMY_EXPORT_MANIFEST_REL,
)
from pipeline.cementitious.schema import RECORD_FIELDS
from pipeline.decarb_testlib import REPRESENTATIVE_PATHS, canonical_record, record_for_path


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _ids(rows: list[dict[str, str]]) -> set[str]:
    return {r["record_id"] for r in rows}


class HierarchicalExportSuiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tax = get_decarbonization_taxonomy()
        self.rows = [
            record_for_path(REPRESENTATIVE_PATHS[0], record_id="opc"),
            record_for_path(REPRESENTATIVE_PATHS[1], record_id="amine"),
            record_for_path(
                REPRESENTATIVE_PATHS[1][:4],
                record_id="chem-na",
                taxonomy_level_4="N.A.",
            ),
            record_for_path(REPRESENTATIVE_PATHS[2], record_id="rca"),
            record_for_path(REPRESENTATIVE_PATHS[3], record_id="heal"),
            record_for_path(REPRESENTATIVE_PATHS[4], record_id="buyclean"),
        ]

    def test_expected_node_csv_paths_and_slug_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "7-30 results"
            write_hierarchical_export(root, self.rows, fieldnames=RECORD_FIELDS)
            export = root / DECARBONIZATION_EXPORT_DIRNAME
            l0 = export / DECARBONIZATION_MASTER_FILENAME
            l1 = export / "cementitious_materials" / "cementitious_materials.csv"
            l2 = (
                export
                / "cementitious_materials"
                / "cement_plant_carbon_capture"
                / "cement_plant_carbon_capture.csv"
            )
            l3 = (
                export
                / "cementitious_materials"
                / "cement_plant_carbon_capture"
                / "chemical_absorption"
                / "chemical_absorption.csv"
            )
            l4 = (
                export
                / "cementitious_materials"
                / "cement_plant_carbon_capture"
                / "chemical_absorption"
                / "amine_absorption.csv"
            )
            for path in (l0, l1, l2, l3, l4):
                self.assertTrue(path.is_file(), path)
            self.assertTrue(
                (
                    export
                    / "policy"
                    / "green_public_procurement"
                    / "embodied_carbon_procurement_limits"
                    / "buy_clean_programs.csv"
                ).is_file()
            )

    def test_level_subsets_identical_schema_and_no_value_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_hierarchical_export(root, self.rows, fieldnames=RECORD_FIELDS)
            export = root / DECARBONIZATION_EXPORT_DIRNAME
            l0 = _read(export / DECARBONIZATION_MASTER_FILENAME)
            l1 = _read(export / "cementitious_materials" / "cementitious_materials.csv")
            l2 = _read(
                export
                / "cementitious_materials"
                / "cement_plant_carbon_capture"
                / "cement_plant_carbon_capture.csv"
            )
            l3 = _read(
                export
                / "cementitious_materials"
                / "cement_plant_carbon_capture"
                / "chemical_absorption"
                / "chemical_absorption.csv"
            )
            l4 = _read(
                export
                / "cementitious_materials"
                / "cement_plant_carbon_capture"
                / "chemical_absorption"
                / "amine_absorption.csv"
            )
            self.assertEqual(_ids(l0), {"opc", "amine", "chem-na", "rca", "heal", "buyclean"})
            self.assertTrue(_ids(l1) < _ids(l0))
            self.assertTrue(_ids(l2) <= _ids(l1))
            self.assertTrue(_ids(l3) <= _ids(l2))
            self.assertTrue(_ids(l4) <= _ids(l3))
            self.assertEqual(_ids(l1), {"opc", "amine", "chem-na"})
            self.assertEqual(_ids(l3), {"amine", "chem-na"})
            self.assertEqual(_ids(l4), {"amine"})
            self.assertEqual(list(l0[0].keys()), list(RECORD_FIELDS))
            self.assertEqual(list(l4[0].keys()), list(RECORD_FIELDS))
            master_by_id = {r["record_id"]: r for r in l0}
            for row in l1 + l2 + l3 + l4:
                self.assertEqual(row, master_by_id[row["record_id"]])

    def test_na_level_4_stays_in_level_3_not_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_hierarchical_export(root, self.rows, fieldnames=RECORD_FIELDS)
            export = root / DECARBONIZATION_EXPORT_DIRNAME
            l3 = _ids(
                _read(
                    export
                    / "cementitious_materials"
                    / "cement_plant_carbon_capture"
                    / "chemical_absorption"
                    / "chemical_absorption.csv"
                )
            )
            l4 = _ids(
                _read(
                    export
                    / "cementitious_materials"
                    / "cement_plant_carbon_capture"
                    / "chemical_absorption"
                    / "amine_absorption.csv"
                )
            )
            self.assertIn("chem-na", l3)
            self.assertNotIn("chem-na", l4)

    def test_zero_record_policy_and_manifest_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_hierarchical_export(root, self.rows, fieldnames=RECORD_FIELDS)
            export = root / DECARBONIZATION_EXPORT_DIRNAME
            eol = export / "end_of_life" / "end_of_life.csv"
            self.assertTrue(eol.is_file())
            self.assertEqual(_read(eol), [])
            empty_l4 = (
                export
                / "end_of_life"
                / "end_of_life_carbonation"
                / "enhanced_concrete_carbonation"
                / "demolition_concrete_carbonation.csv"
            )
            self.assertTrue(empty_l4.is_file())
            self.assertEqual(_read(empty_l4), [])
            with empty_l4.open(newline="") as handle:
                import csv as _csv

                header = next(_csv.reader(handle))
            self.assertEqual(header, list(RECORD_FIELDS))
            manifest = json.loads((root / TAXONOMY_EXPORT_MANIFEST_REL).read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_canonical_records"], len(self.rows))
            by_path = {n["path"]: n for n in manifest["nodes"]}
            for node in manifest["nodes"]:
                self.assertTrue(node["csv_emitted"], node["path"])
                csv_path = export / Path(node["csv_path"])
                self.assertTrue(csv_path.is_file(), csv_path)
                self.assertEqual(len(_read(csv_path)), node["row_count"], node["path"])
                if node["level"] == 4 and node["zero_records"]:
                    self.assertEqual(node["row_count"], 0)
                    self.assertTrue(node["csv_emitted"])
            l0_node = self.tax.root()
            self.assertEqual(by_path[l0_node.path]["row_count"], len(self.rows))

    def test_no_duplicate_rows_introduced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_hierarchical_export(root, self.rows, fieldnames=RECORD_FIELDS)
            export = root / DECARBONIZATION_EXPORT_DIRNAME
            master = _read(export / DECARBONIZATION_MASTER_FILENAME)
            ids = [r["record_id"] for r in master]
            self.assertEqual(len(ids), len(set(ids)))
            extra = canonical_record(record_id="opc-dup", taxonomy_level_4="OPC")
            extra["taxonomy_level_1"] = "Cementitious Materials"
            extra["taxonomy_level_2"] = "Conventional and Blended Cements"
            extra["taxonomy_level_3"] = "Ordinary Portland Cement"
            write_hierarchical_export(root, self.rows + [extra], fieldnames=RECORD_FIELDS)
            master2 = _read(export / DECARBONIZATION_MASTER_FILENAME)
            self.assertEqual(len(master2), len(self.rows) + 1)


if __name__ == "__main__":
    unittest.main()
