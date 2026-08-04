"""Load and validate the Cementitious Materials taxonomy configuration."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pipeline.config import REPO_ROOT
from pipeline.cementitious.paths import sanitize_slug

DEFAULT_TAXONOMY_PATH = REPO_ROOT / "config" / "cementitious_materials_taxonomy.json"


@dataclass(frozen=True)
class TaxonomyNode:
    slug: str
    display_name: str
    parent: str
    level: str
    definition: str
    inclusion_criteria: tuple[str, ...] = ()
    exclusion_criteria: tuple[str, ...] = ()
    representative_synonyms: tuple[str, ...] = ()
    representative_technology_variants: tuple[str, ...] = ()
    expected_technology_domain: str = ""
    allowed_functional_roles: tuple[str, ...] = ()
    positive_screening_cues: tuple[str, ...] = ()
    negative_screening_cues: tuple[str, ...] = ()
    retrieval_query_terms: tuple[str, ...] = ()

    @property
    def csv_filename(self) -> str:
        return f"{self.slug}.csv"

    @property
    def citations_filename(self) -> str:
        return f"{self.slug}_citations.csv"


@dataclass
class Taxonomy:
    taxonomy_version: str
    schema_version: str
    category_display: str
    category_slug: str
    category_definition: str
    controlled_vocabularies: dict[str, list[str]]
    subcategories: dict[str, TaxonomyNode] = field(default_factory=dict)
    sub_subcategories: dict[str, TaxonomyNode] = field(default_factory=dict)
    display_to_slug: dict[str, str] = field(default_factory=dict)
    parent_of_sub_sub: dict[str, str] = field(default_factory=dict)
    source_path: str = ""

    def all_nodes(self) -> list[TaxonomyNode]:
        return list(self.subcategories.values()) + list(self.sub_subcategories.values())

    def resolve_slug(self, value: str, *, level: str | None = None) -> str:
        raw = (value or "").strip()
        if not raw:
            raise ValueError("Empty taxonomy reference")
        # Prefer exact slug match
        key = raw.lower().replace(" ", "_").replace("-", "_")
        key = re.sub(r"_+", "_", key)
        if level in (None, "subcategory") and key in self.subcategories:
            return key
        if level in (None, "sub_subcategory") and key in self.sub_subcategories:
            return key
        # Display-name match (case-insensitive)
        display_key = raw.casefold()
        if display_key in self.display_to_slug:
            slug = self.display_to_slug[display_key]
            if level == "subcategory" and slug not in self.subcategories:
                raise ValueError(f"{value!r} is not a subcategory")
            if level == "sub_subcategory" and slug not in self.sub_subcategories:
                raise ValueError(f"{value!r} is not a sub-subcategory")
            return slug
        raise ValueError(f"Unknown taxonomy node: {value!r}")

    def children_of(self, subcategory_slug: str) -> list[TaxonomyNode]:
        parent = sanitize_slug(subcategory_slug) if subcategory_slug else ""
        return [
            node
            for slug, node in self.sub_subcategories.items()
            if self.parent_of_sub_sub.get(slug) == parent
        ]

    def validate_assignment(
        self,
        *,
        category: str,
        subcategory: str,
        subcategory_slug: str,
        sub_subcategory: str,
        sub_subcategory_slug: str,
    ) -> list[str]:
        errors: list[str] = []
        if category != self.category_display:
            errors.append(f"invalid category: {category!r}")
        try:
            sub_slug = self.resolve_slug(subcategory_slug or subcategory, level="subcategory")
        except ValueError as exc:
            errors.append(str(exc))
            return errors
        try:
            ss_slug = self.resolve_slug(
                sub_subcategory_slug or sub_subcategory,
                level="sub_subcategory",
            )
        except ValueError as exc:
            errors.append(str(exc))
            return errors
        expected_parent = self.parent_of_sub_sub.get(ss_slug)
        if expected_parent != sub_slug:
            errors.append(
                f"inconsistent parent-child: {ss_slug} belongs under "
                f"{expected_parent}, not {sub_slug}"
            )
        sub_node = self.subcategories[sub_slug]
        ss_node = self.sub_subcategories[ss_slug]
        if subcategory and subcategory != sub_node.display_name:
            errors.append(
                f"subcategory display mismatch: {subcategory!r} vs {sub_node.display_name!r}"
            )
        if sub_subcategory and sub_subcategory != ss_node.display_name:
            errors.append(
                f"sub_subcategory display mismatch: {sub_subcategory!r} vs {ss_node.display_name!r}"
            )
        if subcategory_slug and subcategory_slug != sub_slug:
            errors.append(f"subcategory_slug mismatch: {subcategory_slug!r} vs {sub_slug!r}")
        if sub_subcategory_slug and sub_subcategory_slug != ss_slug:
            errors.append(
                f"sub_subcategory_slug mismatch: {sub_subcategory_slug!r} vs {ss_slug!r}"
            )
        return errors

    def list_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = [
            {
                "display_name": self.category_display,
                "slug": self.category_slug,
                "level": "category",
                "parent": "",
                "expected_output_filename": "cementitious_materials_all_records.csv",
            }
        ]
        for slug, node in self.subcategories.items():
            rows.append(
                {
                    "display_name": node.display_name,
                    "slug": slug,
                    "level": "subcategory",
                    "parent": self.category_slug,
                    "expected_output_filename": f"subcategories/{node.csv_filename}",
                }
            )
        for slug, node in self.sub_subcategories.items():
            rows.append(
                {
                    "display_name": node.display_name,
                    "slug": slug,
                    "level": "sub_subcategory",
                    "parent": node.parent,
                    "expected_output_filename": f"sub_subcategories/{node.csv_filename}",
                }
            )
        return rows


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _node_from_dict(payload: dict[str, Any]) -> TaxonomyNode:
    slug = sanitize_slug(str(payload["slug"]))
    return TaxonomyNode(
        slug=slug,
        display_name=str(payload["display_name"]),
        parent=str(payload.get("parent") or ""),
        level=str(payload.get("level") or ""),
        definition=str(payload.get("definition") or ""),
        inclusion_criteria=_as_tuple(payload.get("inclusion_criteria")),
        exclusion_criteria=_as_tuple(payload.get("exclusion_criteria")),
        representative_synonyms=_as_tuple(payload.get("representative_synonyms")),
        representative_technology_variants=_as_tuple(
            payload.get("representative_technology_variants")
        ),
        expected_technology_domain=str(payload.get("expected_technology_domain") or ""),
        allowed_functional_roles=_as_tuple(payload.get("allowed_functional_roles")),
        positive_screening_cues=_as_tuple(payload.get("positive_screening_cues")),
        negative_screening_cues=_as_tuple(payload.get("negative_screening_cues")),
        retrieval_query_terms=_as_tuple(payload.get("retrieval_query_terms")),
    )


def resolve_taxonomy_path(explicit: str | Path | None = None) -> Path:
    raw = (
        str(explicit).strip()
        if explicit
        else os.getenv("TAXONOMY_PATH", "").strip()
    )
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
    else:
        # Prefer JSON when PyYAML is unavailable so Engaging/local runs stay portable.
        yaml_path = DEFAULT_TAXONOMY_PATH.with_suffix(".yaml")
        json_path = DEFAULT_TAXONOMY_PATH.with_suffix(".json")
        if json_path.is_file():
            try:
                import yaml  # noqa: F401

                path = yaml_path if yaml_path.is_file() else json_path
            except ImportError:
                path = json_path
        else:
            path = yaml_path if yaml_path.is_file() else DEFAULT_TAXONOMY_PATH
    if not path.is_file():
        # Fall back to JSON sibling
        json_fallback = path.with_suffix(".json")
        if json_fallback.is_file():
            return json_fallback
        raise FileNotFoundError(f"Taxonomy config not found: {path}")
    return path


def _load_raw(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "PyYAML is required to load taxonomy YAML. "
                "Install pyyaml or use the JSON taxonomy file."
            ) from exc
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"Taxonomy root must be an object: {path}")
    return payload


def validate_taxonomy_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not payload.get("taxonomy_version"):
        errors.append("missing taxonomy_version")
    category = payload.get("category") or {}
    if not category.get("display_name") or not category.get("slug"):
        errors.append("category must include display_name and slug")
    subcats = payload.get("subcategories") or []
    seen_slugs: set[str] = set()
    for sub in subcats:
        slug = str(sub.get("slug") or "")
        try:
            slug = sanitize_slug(slug)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if slug in seen_slugs:
            errors.append(f"duplicate slug: {slug}")
        seen_slugs.add(slug)
        for child in sub.get("children") or []:
            child_slug = str(child.get("slug") or "")
            try:
                child_slug = sanitize_slug(child_slug)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if child_slug in seen_slugs:
                errors.append(f"duplicate slug: {child_slug}")
            seen_slugs.add(child_slug)
            parent = str(child.get("parent") or "")
            if parent and parent != slug:
                errors.append(
                    f"child {child_slug} parent {parent!r} does not match subcategory {slug}"
                )
    return errors


def load_taxonomy(path: str | Path | None = None) -> Taxonomy:
    taxonomy_path = resolve_taxonomy_path(path)
    payload = _load_raw(taxonomy_path)
    errors = validate_taxonomy_payload(payload)
    if errors:
        raise ValueError("Invalid taxonomy:\n- " + "\n- ".join(errors))

    category = payload["category"]
    tax = Taxonomy(
        taxonomy_version=str(payload["taxonomy_version"]),
        schema_version=str(payload.get("schema_version") or ""),
        category_display=str(category["display_name"]),
        category_slug=sanitize_slug(str(category["slug"])),
        category_definition=str(category.get("definition") or ""),
        controlled_vocabularies={
            str(k): [str(x) for x in (v or [])]
            for k, v in (payload.get("controlled_vocabularies") or {}).items()
        },
        source_path=str(taxonomy_path),
    )
    display_map: dict[str, str] = {
        tax.category_display.casefold(): tax.category_slug,
    }
    for sub_payload in payload.get("subcategories") or []:
        sub_node = _node_from_dict(sub_payload)
        tax.subcategories[sub_node.slug] = sub_node
        display_map[sub_node.display_name.casefold()] = sub_node.slug
        for child_payload in sub_payload.get("children") or []:
            child = _node_from_dict(child_payload)
            tax.sub_subcategories[child.slug] = child
            tax.parent_of_sub_sub[child.slug] = sub_node.slug
            display_map[child.display_name.casefold()] = child.slug
    tax.display_to_slug = display_map
    return tax


@lru_cache(maxsize=4)
def get_taxonomy(path: str | None = None) -> Taxonomy:
    return load_taxonomy(path)
