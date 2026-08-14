#!/usr/bin/env python3
"""Old 9×58 cementitious runtime → five-level canonical migration tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy
from pipeline.cementitious.schema import normalize_record
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.cementitious.taxonomy_migration import (
    LEAF_MIGRATIONS,
    MIGRATIONS_BY_LEAF,
    apply_decarbonization_path,
    coverage_report,
)
from pipeline.decarb_testlib import OLD_LEAF_EXAMPLES


class MigrationCoverageTests(unittest.TestCase):
    def test_no_known_old_leaf_is_silently_lost(self) -> None:
        report = coverage_report()
        self.assertTrue(report["complete"], report)
        self.assertEqual(report["old_leaf_count"], 58)
        self.assertEqual(len(LEAF_MIGRATIONS), 58)
        self.assertEqual(report["unmapped_old_leaves"], [])
        self.assertEqual(report["unknown_mapped_slugs"], [])
        self.assertEqual(report["invalid_new_paths"], [])
        runtime = get_taxonomy()
        for slug in runtime.sub_subcategories:
            self.assertIn(slug, MIGRATIONS_BY_LEAF)

    def test_representative_old_classifications_receive_valid_new_paths(self) -> None:
        decarb = get_decarbonization_taxonomy()
        runtime = get_taxonomy()
        for slug in OLD_LEAF_EXAMPLES:
            self.assertIn(slug, MIGRATIONS_BY_LEAF, slug)
            mapping = MIGRATIONS_BY_LEAF[slug]
            rec = normalize_record(
                {
                    "record_id": f"old-{slug}",
                    "subcategory_slug": mapping.old_subcategory_slug,
                    "sub_subcategory_slug": slug,
                    "source_id": f"doi:{slug}",
                    "citation": f"doi:{slug}",
                    "evidence_text": f"legacy evidence for {mapping.old_leaf_label}.",
                },
                taxonomy=runtime,
            )
            self.assertEqual(rec["taxonomy_level_0"], "Concrete Decarbonization")
            self.assertEqual(rec["taxonomy_level_1"], "Cementitious Materials")
            self.assertEqual(rec["taxonomy_level_2"], mapping.level_2)
            self.assertEqual(rec["taxonomy_level_3"], mapping.level_3)
            labels = [
                rec["taxonomy_level_0"],
                rec["taxonomy_level_1"],
                rec["taxonomy_level_2"],
                rec["taxonomy_level_3"],
            ]
            if mapping.level_4:
                labels.append(mapping.level_4)
                self.assertEqual(rec["taxonomy_level_4"], mapping.level_4)
            else:
                self.assertEqual(rec["taxonomy_level_4"], "N.A.")
            decarb.resolve_path_labels(labels)

    def test_ccs_family_promoted_to_level_3_without_fabricating_l4(self) -> None:
        for slug, l3 in (
            ("chemical_absorption", "Chemical Absorption"),
            ("cryogenic_carbon_capture", "Cryogenic Carbon Capture"),
            ("oxy_fuel_combustion", "Oxy-Fuel Combustion"),
            ("membrane_separation", "Membrane Separation"),
            ("calcium_looping", "Calcium Looping"),
            ("direct_separation", "Direct Separation"),
        ):
            rec = apply_decarbonization_path(
                {
                    "subcategory_slug": "cement_plant_carbon_capture",
                    "sub_subcategory_slug": slug,
                }
            )
            self.assertEqual(rec["taxonomy_level_3"], l3)
            self.assertEqual(rec["taxonomy_level_4"], "N.A.")

    def test_conventional_and_emerging_scm_and_fillers_and_alt_cements(self) -> None:
        cases = {
            "slag_cement": "Slag Cement",
            "coal_ash": "Coal Ash",
            "biomass_ashes": "Biomass Ashes",
            "alkali_activated_cements": "Alkali-Activated Cements",
            "engineered_ultrafine_fillers": "Engineered Ultrafine Fillers",
        }
        for slug, l3 in cases.items():
            rec = apply_decarbonization_path({"sub_subcategory_slug": slug})
            self.assertEqual(rec["taxonomy_level_3"], l3, slug)
            mapping = MIGRATIONS_BY_LEAF[slug]
            if mapping.level_4:
                self.assertEqual(rec["taxonomy_level_4"], mapping.level_4)
            else:
                self.assertEqual(rec["taxonomy_level_4"], "N.A.")

    def test_technology_variant_can_fill_l4_but_blank_variant_stays_na(self) -> None:
        blank = apply_decarbonization_path({"sub_subcategory_slug": "chemical_absorption"})
        self.assertEqual(blank["taxonomy_level_4"], "N.A.")
        matched = apply_decarbonization_path(
            {
                "sub_subcategory_slug": "chemical_absorption",
                "technology_variant": "Amine Absorption",
            }
        )
        self.assertEqual(matched["taxonomy_level_3"], "Chemical Absorption")
        self.assertEqual(matched["taxonomy_level_4"], "Amine Absorption")


if __name__ == "__main__":
    unittest.main()
