#!/usr/bin/env python3
"""Canonical five-level Concrete Decarbonization taxonomy structure tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.decarbonization_taxonomy import (
    get_decarbonization_taxonomy,
    validate_decarbonization_payload,
)
from pipeline.cementitious.paths import sanitize_slug, taxonomy_slugify
from pipeline.decarb_testlib import REPRESENTATIVE_PATHS


FORBIDDEN_L1 = (
    "Alternative Cementitious Materials",
    "Supplementary Cementitious Materials",
    "Alternative Supplementary Cementitious Materials",
    "Inert Fillers",
    "Inert and Low-Reactivity Fillers",
)


class CanonicalTaxonomyStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tax = get_decarbonization_taxonomy()

    def test_exactly_one_level_0_root_named_concrete_decarbonization(self) -> None:
        roots = self.tax.nodes_at(0)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].label, "Concrete Decarbonization")
        self.assertEqual(roots[0].level, 0)
        self.assertEqual(self.tax.root().path, roots[0].path)

    def test_levels_are_zero_through_four(self) -> None:
        levels = {n.level for n in self.tax.ordered_nodes()}
        self.assertEqual(levels, {0, 1, 2, 3, 4})
        self.assertEqual(self.tax.count(0), 1)
        self.assertEqual(self.tax.count(1), 7)
        self.assertEqual(self.tax.count(2), 35)
        self.assertEqual(self.tax.count(3), 91)
        self.assertEqual(self.tax.count(4), 299)

    def test_cementitious_materials_is_the_only_cementitious_level_1(self) -> None:
        l1 = {n.label for n in self.tax.nodes_at(1)}
        self.assertIn("Cementitious Materials", l1)
        for forbidden in FORBIDDEN_L1:
            self.assertNotIn(forbidden, l1)
        cem = next(n for n in self.tax.nodes_at(1) if n.slug == "cementitious_materials")
        l2 = {c.label for c in self.tax.children(cem.path)}
        self.assertIn("Conventional Supplementary Cementitious Materials", l2)
        self.assertIn("Emerging Supplementary Cementitious Materials", l2)
        self.assertIn("Alternative Cement Chemistries", l2)
        self.assertIn("Inert and Low-Reactivity Fillers", l2)
        self.assertIn("Cement-Plant Carbon Capture", l2)

    def test_every_non_root_has_valid_parent_and_l4_has_no_children(self) -> None:
        for node in self.tax.ordered_nodes():
            if node.level == 0:
                self.assertFalse(node.parent_path)
                continue
            self.assertIn(node.parent_path, self.tax.nodes_by_path)
            parent = self.tax.nodes_by_path[node.parent_path]
            self.assertEqual(parent.level, node.level - 1)
            self.assertIn(node.path, self.tax.children_of[node.parent_path])
            if node.level == 4:
                self.assertEqual(node.child_count, 0)
                self.assertEqual(node.children_slugs, ())

    def test_sibling_slugs_and_full_paths_are_unique(self) -> None:
        paths = [n.path for n in self.tax.ordered_nodes()]
        self.assertEqual(len(paths), len(set(paths)))
        siblings: dict[str, list[str]] = {}
        for node in self.tax.ordered_nodes():
            siblings.setdefault(node.parent_path, []).append(node.slug)
        for parent, slugs in siblings.items():
            self.assertEqual(len(slugs), len(set(slugs)), msg=parent)

    def test_no_filesystem_invalid_slugs(self) -> None:
        for node in self.tax.ordered_nodes():
            sanitize_slug(node.slug)
            self.assertNotIn("..", node.slug)
            self.assertNotIn("/", node.slug)
            self.assertNotIn("\\", node.slug)
            if node.level > 0:
                taxonomy_slugify(node.label)

    def test_traversal_is_deterministic(self) -> None:
        first = [n.path for n in self.tax.ordered_nodes()]
        second = [n.path for n in get_decarbonization_taxonomy().ordered_nodes()]
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first, key=lambda p: (p.count("/"), p)))

    def test_representative_paths_resolve(self) -> None:
        for labels in REPRESENTATIVE_PATHS:
            node = self.tax.resolve_path_labels(labels)
            self.assertEqual(node.level, 4)
            self.assertEqual(tuple(node.path_labels), labels)

    def test_payload_validator_accepts_canonical_file(self) -> None:
        payload = json.loads(Path(self.tax.source_path).read_text(encoding="utf-8"))
        self.assertEqual(validate_decarbonization_payload(payload), [])


if __name__ == "__main__":
    unittest.main()
