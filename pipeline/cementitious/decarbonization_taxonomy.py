"""Five-level Concrete Decarbonization taxonomy loader and validator."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from pipeline.config import REPO_ROOT
from pipeline.cementitious.paths import is_taxonomy_na, sanitize_slug, taxonomy_slugify

DEFAULT_DECARBONIZATION_TAXONOMY_PATH = (
    REPO_ROOT / "config" / "concrete_decarbonization_taxonomy.json"
)
TAXONOMY_NA = "N.A."


@dataclass(frozen=True)
class DecarbNode:
    label: str
    slug: str
    level: int
    parent_slug: str
    parent_path: str
    path: str
    path_slugs: tuple[str, ...]
    path_labels: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    children_slugs: tuple[str, ...] = ()

    @property
    def child_count(self) -> int:
        return len(self.children_slugs)

    def csv_filename(self, *, parent_slug: str | None = None) -> str:
        """Level-4 CSVs that share the parent folder name get a ``_leaf`` suffix."""
        if self.level == 4 and parent_slug and self.slug == parent_slug:
            return f"{self.slug}_leaf.csv"
        return f"{self.slug}.csv"


@dataclass
class DecarbonizationTaxonomy:
    taxonomy_version: str
    schema_version: str
    source_path: str
    nodes_by_path: dict[str, DecarbNode] = field(default_factory=dict)
    children_of: dict[str, list[str]] = field(default_factory=dict)
    label_index: dict[tuple[int, str], str] = field(default_factory=dict)

    def root(self) -> DecarbNode:
        for node in self.nodes_by_path.values():
            if node.level == 0:
                return node
        raise ValueError("Taxonomy is missing a Level-0 root")

    def nodes_at(self, level: int) -> list[DecarbNode]:
        return [n for n in self.ordered_nodes() if n.level == level]

    def ordered_nodes(self) -> list[DecarbNode]:
        return sorted(self.nodes_by_path.values(), key=lambda n: (n.level, n.path))

    def children(self, path: str) -> list[DecarbNode]:
        return [self.nodes_by_path[p] for p in self.children_of.get(path, [])]

    def count(self, level: int | None = None) -> int:
        if level is None:
            return len(self.nodes_by_path)
        return sum(1 for n in self.nodes_by_path.values() if n.level == level)

    def resolve_path_labels(self, labels: Iterable[str]) -> DecarbNode:
        labels = [str(x).strip() for x in labels if str(x).strip() and not is_taxonomy_na(str(x))]
        if not labels:
            raise ValueError("Empty taxonomy path")
        slugs = [taxonomy_slugify(x) for x in labels]
        path = "/".join(slugs)
        node = self.nodes_by_path.get(path)
        if node is None:
            raise ValueError(f"Unknown taxonomy path: {labels}")
        return node

    def searchable_web_nodes(
        self,
        *,
        include_parent_l3: bool = False,
        levels: Iterable[int] | None = None,
    ) -> list[DecarbNode]:
        from pipeline.cementitious.web_scope import searchable_web_nodes as _searchable

        return _searchable(self, include_parent_l3=include_parent_l3, levels=levels)

    def find_child(self, parent_path: str, label_or_slug: str) -> DecarbNode | None:
        if is_taxonomy_na(label_or_slug):
            return None
        want = label_or_slug.strip().casefold()
        want_slug = None
        try:
            want_slug = taxonomy_slugify(label_or_slug)
        except ValueError:
            want_slug = None
        for child in self.children(parent_path):
            aliases = {child.label.casefold(), child.slug}
            aliases.update(a.casefold() for a in child.aliases)
            if want in aliases or (want_slug and child.slug == want_slug):
                return child
        return None


def validate_decarbonization_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    nodes = payload.get("nodes") or []
    if not nodes:
        errors.append("taxonomy has no nodes")
        return errors
    roots = [n for n in nodes if int(n.get("level", -1)) == 0]
    if len(roots) != 1:
        errors.append(f"expected exactly one Level-0 root, found {len(roots)}")
    paths: set[str] = set()
    sibling_slugs: dict[str, set[str]] = {}
    for raw in nodes:
        try:
            level = int(raw.get("level"))
        except Exception:
            errors.append(f"invalid level on node {raw.get('label')!r}")
            continue
        if level < 0 or level > 4:
            errors.append(f"level {level} outside 0..4 for {raw.get('label')!r}")
        slug = str(raw.get("slug") or "")
        try:
            sanitize_slug(slug)
        except ValueError as exc:
            errors.append(str(exc))
        path = str(raw.get("path") or "")
        if not path:
            errors.append(f"missing path for {raw.get('label')!r}")
            continue
        if path in paths:
            errors.append(f"duplicate canonical path: {path}")
        paths.add(path)
        parent_path = str(raw.get("parent_path") or "")
        if level == 0:
            if parent_path or raw.get("parent_slug"):
                errors.append("root must not have a parent")
        else:
            if not parent_path:
                errors.append(f"non-root {path} missing parent")
            expected_parent_level = level - 1
            parent = next((n for n in nodes if n.get("path") == parent_path), None)
            if parent is None:
                errors.append(f"{path} parent {parent_path} not found")
            elif int(parent.get("level", -1)) != expected_parent_level:
                errors.append(
                    f"{path} parent is level {parent.get('level')}, expected {expected_parent_level}"
                )
        bucket = sibling_slugs.setdefault(parent_path, set())
        if slug in bucket:
            errors.append(f"duplicate sibling slug {slug!r} under {parent_path or '<root>'}")
        bucket.add(slug)
        children = list(raw.get("children_slugs") or [])
        if level == 4 and children:
            errors.append(f"Level-4 node must not have children: {path}")
    return errors


def load_decarbonization_taxonomy(path: str | Path | None = None) -> DecarbonizationTaxonomy:
    taxonomy_path = Path(path) if path else DEFAULT_DECARBONIZATION_TAXONOMY_PATH
    if not taxonomy_path.is_file():
        from pipeline.cementitious._build_decarbonization_taxonomy import write_json

        write_json(taxonomy_path)
    payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    errors = validate_decarbonization_payload(payload)
    if errors:
        raise ValueError("Invalid decarbonization taxonomy:\n- " + "\n- ".join(errors))
    tax = DecarbonizationTaxonomy(
        taxonomy_version=str(payload.get("taxonomy_version") or ""),
        schema_version=str(payload.get("schema_version") or ""),
        source_path=str(taxonomy_path),
    )
    for raw in payload["nodes"]:
        node = DecarbNode(
            label=str(raw["label"]),
            slug=str(raw["slug"]),
            level=int(raw["level"]),
            parent_slug=str(raw.get("parent_slug") or ""),
            parent_path=str(raw.get("parent_path") or ""),
            path=str(raw["path"]),
            path_slugs=tuple(raw.get("path_slugs") or []),
            path_labels=tuple(raw.get("path_labels") or []),
            aliases=tuple(raw.get("aliases") or []),
            children_slugs=tuple(raw.get("children_slugs") or []),
        )
        tax.nodes_by_path[node.path] = node
        tax.children_of.setdefault(node.parent_path, [])
        if node.level > 0:
            tax.children_of.setdefault(node.parent_path, [])
            if node.path not in tax.children_of[node.parent_path]:
                tax.children_of[node.parent_path].append(node.path)
        tax.label_index[(node.level, node.label.casefold())] = node.path
        tax.label_index[(node.level, node.slug)] = node.path
    for parent in tax.children_of:
        tax.children_of[parent].sort()
    return tax


@lru_cache(maxsize=4)
def get_decarbonization_taxonomy(path: str | None = None) -> DecarbonizationTaxonomy:
    return load_decarbonization_taxonomy(path)
