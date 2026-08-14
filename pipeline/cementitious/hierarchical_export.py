"""Hierarchical Concrete Decarbonization export (taxonomy-tree views of one master)."""

from __future__ import annotations

import csv
import logging
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from pipeline.cementitious.decarbonization_taxonomy import (
    TAXONOMY_NA,
    DecarbNode,
    DecarbonizationTaxonomy,
    get_decarbonization_taxonomy,
)
from pipeline.cementitious.paths import (
    DECARBONIZATION_EXPORT_DIRNAME,
    DECARBONIZATION_MASTER_FILENAME,
    TAXONOMY_EXPORT_MANIFEST_REL,
    is_taxonomy_na,
    taxonomy_slugify,
)
from pipeline.cementitious.schema import RECORD_FIELDS, sort_records
from pipeline.cementitious.shard_io import atomic_write_csv, atomic_write_json
from pipeline.cementitious.taxonomy_migration import apply_decarbonization_path

logger = logging.getLogger(__name__)

EMPTY_L4_POLICY = (
    "emit_every_node: every taxonomy node (Level 0–4) receives a CSV with the "
    "canonical header. Zero-record nodes are header-only files with csv_emitted=true "
    "and row_count=0. Level-4 CSVs live in the parent Level-3 folder."
)


class HierarchicalExportError(RuntimeError):
    """Raised when the hierarchical export fails row-conservation invariants."""


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _project(rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> list[dict[str, str]]:
    projected = []
    for row in rows:
        annotated = apply_decarbonization_path(row)
        projected.append({k: _cell(annotated.get(k)) for k in fieldnames})
    return sort_records(projected)


def _level_value(row: dict[str, str], level: int) -> str:
    return _cell(row.get(f"taxonomy_level_{level}"))


def _ancestor_nodes(row: dict[str, str], tax: DecarbonizationTaxonomy) -> list[DecarbNode]:
    """Resolve ancestor nodes for a projected row without copying the row."""
    prefixes: list[str] = []
    found: list[DecarbNode] = []
    for i in range(5):
        value = _level_value(row, i)
        if is_taxonomy_na(value):
            break
        prefixes.append(value)
        try:
            found.append(tax.resolve_path_labels(prefixes))
        except ValueError:
            break
    return found


def _bucket_rows_by_node(
    canonical: list[dict[str, str]],
    tax: DecarbonizationTaxonomy,
) -> dict[str, list[dict[str, str]]]:
    """Group row *references* by taxonomy path (no per-node dataframe copies)."""
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in canonical:
        for node in _ancestor_nodes(row, tax):
            buckets[node.path].append(row)
    return buckets


def _matches_node(row: dict[str, str], node: DecarbNode) -> bool:
    for i, label in enumerate(node.path_labels):
        value = _level_value(row, i)
        if is_taxonomy_na(value):
            return False
        try:
            if taxonomy_slugify(value) != node.path_slugs[i] and value != label:
                return False
        except ValueError:
            return False
    return True


def _folder_for_node(export_root: Path, node: DecarbNode) -> Path:
    """Directory that contains this node's CSV.

    Level 0 CSV lives in the export root. Level 1–3 CSVs live in a folder named
    for the node. Level 4 CSVs live in the Level-3 parent folder.
    """
    slugs = list(node.path_slugs)
    if node.level == 0:
        return export_root
    if node.level == 4:
        return export_root.joinpath(*slugs[1:-1])
    return export_root.joinpath(*slugs[1:])


def _csv_path(export_root: Path, node: DecarbNode) -> Path:
    folder = _folder_for_node(export_root, node)
    parent_slug = node.parent_slug if node.level == 4 else None
    return folder / node.csv_filename(parent_slug=parent_slug)


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def write_hierarchical_export(
    output_dir: str | Path,
    rows: Iterable[dict[str, Any]],
    *,
    fieldnames: tuple[str, ...] | list[str] | None = None,
    taxonomy: DecarbonizationTaxonomy | None = None,
    force: bool = True,
) -> dict[str, Any]:
    """Write concrete_decarbonization_results/ as filtered views of ``rows``."""
    del force
    root = Path(output_dir)
    tax = taxonomy or get_decarbonization_taxonomy()
    fields = list(fieldnames or RECORD_FIELDS)
    canonical = _project(rows, fields)
    export_root = root / DECARBONIZATION_EXPORT_DIRNAME
    staging = export_root / ".staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    buckets = _bucket_rows_by_node(canonical, tax)

    emitted: list[dict[str, Any]] = []
    folders = 0
    csv_count = 0
    try:
        for node in tax.ordered_nodes():
            dest_folder = _folder_for_node(staging, node)
            dest_folder.mkdir(parents=True, exist_ok=True)
            folders += 1
            matched = buckets.pop(node.path, [])
            emit = True
            dest = _csv_path(staging, node)
            atomic_write_csv(dest, fields, matched)
            csv_count += 1
            csv_rel = _rel(dest, staging)
            next_level = node.level + 1
            unclassified = 0
            if node.level < 4:
                unclassified = sum(
                    1
                    for row in matched
                    if is_taxonomy_na(_level_value(row, next_level))
                )
            zero_reason = "no_qualifying_evidence" if not matched else ""
            emitted.append(
                {
                    "canonical_label": node.label,
                    "slug": node.slug,
                    "level": node.level,
                    "parent_path": node.parent_path,
                    "full_taxonomy_path": " → ".join(node.path_labels),
                    "path": node.path,
                    "csv_path": csv_rel,
                    "row_count": len(matched),
                    "child_count": node.child_count,
                    "csv_emitted": emit,
                    "zero_records": len(matched) == 0,
                    "zero_reason": zero_reason,
                    "unclassified_to_deeper_level_count": unclassified,
                    "literature_candidates": None,
                    "literature_extracted": None,
                    "web_queries": None,
                    "web_results": None,
                    "web_extracted": None,
                }
            )
        if export_root.exists():
            # Keep the directory but replace contents atomically via staging swap
            # of the tree except metadata living outside this folder.
            for child in list(export_root.iterdir()):
                if child.name == ".staging":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        export_root.mkdir(parents=True, exist_ok=True)
        for child in staging.iterdir():
            target = export_root / child.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(child), str(target))
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    issues = validate_hierarchical_export(
        root, canonical_rows=canonical, fieldnames=fields, taxonomy=tax
    )
    manifest = {
        "taxonomy_version": tax.taxonomy_version,
        "schema_version": tax.schema_version,
        "empty_l4_policy": EMPTY_L4_POLICY,
        "single_path_per_record": True,
        "total_canonical_records": len(canonical),
        "level_0_nodes": tax.count(0),
        "level_1_nodes": tax.count(1),
        "level_2_nodes": tax.count(2),
        "level_3_nodes": tax.count(3),
        "level_4_nodes": tax.count(4),
        "total_taxonomy_nodes": tax.count(),
        "total_csvs_generated": csv_count,
        "total_folders_generated": folders,
        "invariant_issues": issues,
        "nodes": emitted,
    }
    atomic_write_json(root / TAXONOMY_EXPORT_MANIFEST_REL, manifest)
    if issues:
        raise HierarchicalExportError(
            "Hierarchical export failed invariants: " + "; ".join(issues[:8])
        )
    return {
        "export_root": str(export_root),
        "master_csv": str(export_root / DECARBONIZATION_MASTER_FILENAME),
        "manifest_path": str(root / TAXONOMY_EXPORT_MANIFEST_REL),
        "ok": True,
        **{k: manifest[k] for k in (
            "total_canonical_records",
            "total_csvs_generated",
            "total_folders_generated",
            "level_1_nodes",
            "level_2_nodes",
            "level_3_nodes",
            "level_4_nodes",
        )},
    }


def ensure_hierarchical_export_from_master(output_dir: str | Path) -> dict[str, Any]:
    """Rebuild the five-level tree from ``all_records/`` master CSV."""
    import csv

    root = Path(output_dir)
    master = root / "all_records" / "cementitious_materials_all_records.csv"
    if not master.is_file():
        raise FileNotFoundError(f"Master records CSV missing: {master}")
    with master.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return write_hierarchical_export(root, rows, fieldnames=RECORD_FIELDS)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    import csv

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{k: (v if v is not None else "") for k, v in row.items()} for row in reader]
    return fields, rows


def validate_hierarchical_export(
    output_dir: str | Path,
    *,
    canonical_rows: list[dict[str, str]] | None = None,
    fieldnames: list[str] | None = None,
    taxonomy: DecarbonizationTaxonomy | None = None,
) -> list[str]:
    root = Path(output_dir)
    tax = taxonomy or get_decarbonization_taxonomy()
    fields = list(fieldnames or RECORD_FIELDS)
    export_root = root / DECARBONIZATION_EXPORT_DIRNAME
    master_path = export_root / DECARBONIZATION_MASTER_FILENAME
    issues: list[str] = []
    if not master_path.is_file():
        return [f"missing master CSV: {master_path}"]
    master_fields, master_rows = _read_csv(master_path)
    if list(master_fields) != fields:
        issues.append("master CSV schema mismatch")
    if canonical_rows is not None and len(canonical_rows) != len(master_rows):
        issues.append(
            f"master row count {len(master_rows)} != canonical {len(canonical_rows)}"
        )

    def row_id(row: dict[str, str]) -> str:
        return row.get("record_id") or ""

    def row_key(row: dict[str, str]) -> tuple[str, ...]:
        return tuple(row.get(k, "") for k in fields)

    master_by_id = {row_id(r): r for r in master_rows if row_id(r)}
    if len(master_by_id) != len([r for r in master_rows if row_id(r)]):
        issues.append("duplicate record_id in hierarchical master")

    # IDs only after streaming each partition CSV — do not retain per-node dataframes.
    tables_ids: dict[str, list[str]] = {
        tax.root().path: [row_id(r) for r in master_rows if row_id(r)]
    }
    for node in tax.ordered_nodes():
        if node.level == 0:
            continue
        path = _csv_path(export_root, node)
        if node.level < 4:
            if not path.is_file():
                issues.append(f"missing Level-{node.level} CSV: {path}")
                tables_ids[node.path] = []
                continue
        elif not path.is_file():
            issues.append(f"missing Level-{node.level} CSV: {path}")
            tables_ids[node.path] = []
            continue
        ids: list[str] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if list(reader.fieldnames or []) != fields:
                issues.append(f"schema mismatch in {_rel(path, root)}")
            for raw in reader:
                row = {k: (v if v is not None else "") for k, v in raw.items()}
                rid = row_id(row)
                ids.append(rid)
                if rid not in master_by_id:
                    issues.append(f"{path.name} has {rid!r} not in master")
                    continue
                if row_key({k: row.get(k, "") for k in fields}) != row_key(master_by_id[rid]):
                    issues.append(f"values changed vs master for {rid} in {path.name}")
                if not _matches_node(row, node):
                    issues.append(f"{rid} in {path.name} does not match taxonomy path {node.path}")
        tables_ids[node.path] = ids

    for node in tax.ordered_nodes():
        parent_ids = tables_ids.get(node.path, [])
        children = tax.children(node.path)
        if not children:
            continue
        child_ids: list[str] = []
        for child in children:
            child_ids.extend(tables_ids.get(child.path, []))
        next_level = node.level + 1
        classified = [
            rid
            for rid in parent_ids
            if rid
            and rid in master_by_id
            and not is_taxonomy_na(_level_value(master_by_id[rid], next_level))
        ]
        if sorted(x for x in child_ids if x) != sorted(classified):
            issues.append(
                f"child union != classified parent rows at {node.path} "
                f"(children={len(child_ids)} classified={len(classified)})"
            )
        if len(child_ids) != len(set(child_ids)):
            issues.append(f"duplicate rows across children of {node.path}")

    l1_ids: list[str] = []
    for node in tax.nodes_at(1):
        l1_ids.extend(tables_ids.get(node.path, []))
    master_ids = [row_id(r) for r in master_rows if row_id(r)]
    assigned_master = [
        rid for rid in master_ids if not is_taxonomy_na(_level_value(master_by_id[rid], 1))
    ]
    if sorted(x for x in l1_ids if x) != sorted(assigned_master):
        issues.append("union of Level-1 CSVs does not match assigned master rows")

    return issues


def render_hierarchical_tree(
    output_dir: str | Path,
    *,
    max_depth: int = 8,
    populated_only: bool = False,
) -> str:
    export_root = Path(output_dir) / DECARBONIZATION_EXPORT_DIRNAME
    if not export_root.exists():
        return "(missing)"

    def _csv_has_rows(path: Path) -> bool:
        if not path.is_file():
            return False
        _, rows = _read_csv(path)
        return bool(rows)

    def _dir_has_data(dir_path: Path) -> bool:
        if not populated_only:
            return True
        for csv_path in dir_path.rglob("*.csv"):
            if _csv_has_rows(csv_path):
                return True
        return False

    lines = [f"{DECARBONIZATION_EXPORT_DIRNAME}/"]

    def walk(dir_path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name))
        files = [p for p in entries if p.is_file() and p.suffix == ".csv"]
        dirs = [p for p in entries if p.is_dir() and p.name != ".staging"]
        if populated_only:
            files = [p for p in files if _csv_has_rows(p)]
            dirs = [p for p in dirs if _dir_has_data(p)]
        items = files + dirs
        for i, item in enumerate(items):
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            lines.append(f"{prefix}{branch}{item.name}{'/' if item.is_dir() else ''}")
            if item.is_dir():
                walk(item, prefix + ("    " if last else "│   "), depth + 1)

    walk(export_root, "", 0)
    return "\n".join(lines)
