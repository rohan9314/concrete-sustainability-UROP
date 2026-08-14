"""Canonical user-facing Cementitious Materials CSV export.

Taxonomy mapping (internal → user-facing)
----------------------------------------
The taxonomy has three levels:

1. category              — umbrella, always "Cementitious Materials"
2. subcategory           — 9 nodes (e.g. cement_plant_carbon_capture)
3. sub_subcategory/leaf  — 58 nodes (e.g. chemical_absorption)

The user-facing export is TWO levels beneath the master dataset:

  MASTER
    → CATEGORY CSV     = internal **subcategory**      (``subcategory_slug``)
    → SUBCATEGORY CSV  = internal **sub_subcategory**  (``sub_subcategory_slug``)
                         nested under the parent subcategory folder

This is *not* a dump of the 58 taxonomy leaves into a flat subcategory folder.

Empty-partition policy
----------------------
User-facing category/subcategory CSVs are written **only when at least one
canonical row** belongs to that partition. Empty header-only files are not
created here. (Internal ``subcategories/`` and ``sub_subcategories/`` still
materialize all 9+58 files, including empty ones, for workflow compatibility.)

Missing taxonomy policy
-----------------------
``validate_records`` already sends missing/invalid taxonomy rows to
``rejected_records/``; they are not part of the canonical dataframe.

If a row nevertheless reaches this exporter with a blank category
(internal subcategory) or subcategory (internal leaf) slug, it is:

- kept in the master CSV (not silently dropped)
- written to ``unassigned_taxonomy.csv``
- omitted from the matching category/subcategory CSVs
- treated as an export-contract failure (``export.complete`` must not be written)

All user-facing CSVs are filtered views of the same canonical row list.
No extra normalization or deduplication is applied here.
"""

from __future__ import annotations

import csv
import logging
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from pipeline.cementitious.paths import (
    USER_FACING_CATEGORY_DIRNAME,
    USER_FACING_EXPORT_DIRNAME,
    USER_FACING_MASTER_FILENAME,
    USER_FACING_SUBCATEGORY_DIRNAME,
    USER_FACING_UNASSIGNED_FILENAME,
    safe_partition_filename,
    sanitize_slug,
)
from pipeline.cementitious.schema import RECORD_FIELDS, sort_records

logger = logging.getLogger(__name__)

TAXONOMY_LEVEL_MAPPING = {
    "user_facing_master": "all accepted/cleaned/deduplicated records",
    "user_facing_category": "internal subcategory (subcategory_slug; 9 nodes)",
    "user_facing_subcategory": (
        "internal sub_subcategory / taxonomy leaf (sub_subcategory_slug; 58 nodes), "
        "nested under the parent internal subcategory"
    ),
    "internal_category": "umbrella Cementitious Materials (not a user-facing CSV split)",
}

EMPTY_PARTITION_POLICY = (
    "omit: do not create empty user-facing category or subcategory CSVs. "
    "Internal subcategories/ and sub_subcategories/ still write empty header-only "
    "files for all configured taxonomy nodes."
)

MISSING_TAXONOMY_POLICY = (
    "Records that fail validate_records (missing or invalid taxonomy) are written "
    "to rejected_records/ and are not in the canonical master. Rows that reach "
    "export with blank subcategory_slug or sub_subcategory_slug are kept in the "
    "master CSV, copied to unassigned_taxonomy.csv, excluded from category/"
    "subcategory CSVs, and fail export validation so export.complete is not written."
)


class CanonicalExportError(RuntimeError):
    """Raised when the user-facing export cannot satisfy layout invariants."""


def user_facing_export_root(output_dir: str | Path) -> Path:
    return Path(output_dir) / USER_FACING_EXPORT_DIRNAME


def user_facing_master_path(output_dir: str | Path) -> Path:
    return user_facing_export_root(output_dir) / USER_FACING_MASTER_FILENAME


def project_canonical_rows(
    rows: Iterable[dict[str, Any]],
    *,
    fieldnames: tuple[str, ...] | list[str] | None = None,
) -> list[dict[str, str]]:
    """Return sorted rows projected onto a single unified schema (blanks preserved)."""
    fields = list(fieldnames or RECORD_FIELDS)
    projected: list[dict[str, str]] = []
    for row in rows:
        projected.append({key: _cell(row.get(key)) for key in fields})
    return sort_records(projected) if set(fields) >= {"record_id"} else projected


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_slug(value: Any) -> str:
    text = _cell(value).strip()
    if not text:
        return ""
    try:
        return sanitize_slug(text)
    except ValueError:
        return ""


def _row_key(row: dict[str, str], fieldnames: list[str]) -> tuple[str, ...]:
    return tuple(row.get(k, "") for k in fieldnames)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{k: (v if v is not None else "") for k, v in row.items()} for row in reader]
    return fields, rows


def write_canonical_user_export(
    output_dir: str | Path,
    rows: Iterable[dict[str, Any]],
    *,
    fieldnames: tuple[str, ...] | list[str] | None = None,
    force: bool = True,
) -> dict[str, Any]:
    """
    Write ``cementitious_materials_results/`` from one canonical row list.

    ``force`` is accepted for API symmetry with the rest of the export stage.
    When this function runs it always rewrites the user-facing tree (atomic
    replace). Checkpoint-level FORCE/resume is handled by the export stage.
    """
    del force  # overwrite is always a full tree replace when invoked
    from pipeline.cementitious.shard_io import atomic_write_csv

    root = Path(output_dir)
    fields = list(fieldnames or RECORD_FIELDS)
    canonical = project_canonical_rows(rows, fieldnames=fields)
    export_root = user_facing_export_root(root)
    export_root.mkdir(parents=True, exist_ok=True)

    by_category: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_subcategory: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    unassigned: list[dict[str, str]] = []
    issues: list[str] = []

    seen_ids: list[str] = []
    category_files: list[str] = []
    subcategory_files: list[str] = []
    for row in canonical:
        rid = row.get("record_id") or ""
        if rid:
            seen_ids.append(rid)
        cat = _safe_slug(row.get("subcategory_slug") or row.get("subcategory"))
        sub = _safe_slug(row.get("sub_subcategory_slug") or row.get("sub_subcategory"))
        l1 = (row.get("taxonomy_level_1") or "").strip()
        non_cementitious = l1 not in {"", "N.A.", "Cementitious Materials"}
        if not cat:
            if non_cementitious:
                continue
            unassigned.append(row)
            issues.append(
                f"record_id {rid!r} missing user-facing category "
                "(internal subcategory_slug); kept in master + unassigned_taxonomy.csv"
            )
            continue
        by_category[cat].append(row)
        if not sub:
            if non_cementitious:
                continue
            unassigned.append(row)
            issues.append(
                f"record_id {rid!r} missing user-facing subcategory "
                "(internal sub_subcategory_slug); kept in master + category CSV + "
                "unassigned_taxonomy.csv"
            )
            continue
        by_subcategory[(cat, sub)].append(row)

    dup_ids = sorted({rid for rid in seen_ids if seen_ids.count(rid) > 1})
    if dup_ids:
        issues.append(f"canonical dataframe contains duplicate record_id values: {dup_ids[:10]}")

    staging = export_root / ".staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_csv(staging / USER_FACING_MASTER_FILENAME, fields, canonical)

        cat_dir = staging / USER_FACING_CATEGORY_DIRNAME
        sub_dir = staging / USER_FACING_SUBCATEGORY_DIRNAME

        for cat_slug in sorted(by_category):
            cat_rows = by_category[cat_slug]
            if not cat_rows:
                continue
            filename = safe_partition_filename(cat_slug)
            atomic_write_csv(cat_dir / filename, fields, cat_rows)
            category_files.append(f"{USER_FACING_CATEGORY_DIRNAME}/{filename}")

        for cat_slug, sub_slug in sorted(by_subcategory):
            sub_rows = by_subcategory[(cat_slug, sub_slug)]
            if not sub_rows:
                continue
            filename = safe_partition_filename(sub_slug)
            dest = sub_dir / sanitize_slug(cat_slug) / filename
            atomic_write_csv(dest, fields, sub_rows)
            subcategory_files.append(
                f"{USER_FACING_SUBCATEGORY_DIRNAME}/{sanitize_slug(cat_slug)}/{filename}"
            )

        if unassigned:
            atomic_write_csv(staging / USER_FACING_UNASSIGNED_FILENAME, fields, unassigned)

        # Swap staged tree into place so a crash cannot leave mixed old+new CSVs.
        atomic_write_csv(export_root / USER_FACING_MASTER_FILENAME, fields, canonical)
        _replace_dir(cat_dir, export_root / USER_FACING_CATEGORY_DIRNAME)
        _replace_dir(sub_dir, export_root / USER_FACING_SUBCATEGORY_DIRNAME)

        unassigned_path = export_root / USER_FACING_UNASSIGNED_FILENAME
        if unassigned:
            atomic_write_csv(unassigned_path, fields, unassigned)
        elif unassigned_path.is_file():
            unassigned_path.unlink()
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    invariant_issues = validate_canonical_user_export_tree(
        root, canonical_rows=canonical, fieldnames=fields
    )
    issues.extend(invariant_issues)

    result = {
        "export_root": str(export_root),
        "master_csv": str(user_facing_master_path(root)),
        "master_record_count": len(canonical),
        "category_csv_count": len(category_files),
        "subcategory_csv_count": len(subcategory_files),
        "category_files": category_files,
        "subcategory_files": subcategory_files,
        "unassigned_count": len(unassigned),
        "empty_partition_policy": EMPTY_PARTITION_POLICY,
        "missing_taxonomy_policy": MISSING_TAXONOMY_POLICY,
        "taxonomy_level_mapping": dict(TAXONOMY_LEVEL_MAPPING),
        "issues": issues,
        "ok": not issues,
    }
    if issues:
        raise CanonicalExportError(
            "Canonical user-facing export failed invariants: " + "; ".join(issues[:8])
        )
    return result


def ensure_canonical_user_export_from_master(output_dir: str | Path) -> dict[str, Any]:
    """Rebuild the user-facing tree from ``all_records/`` master CSV (repair path)."""
    root = Path(output_dir)
    master = root / "all_records" / "cementitious_materials_all_records.csv"
    if not master.is_file():
        raise FileNotFoundError(f"Master records CSV missing: {master}")
    _fields, rows = _read_csv(master)
    return write_canonical_user_export(root, rows, fieldnames=RECORD_FIELDS)


def _replace_dir(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    if src.exists():
        src.rename(dest)


def validate_canonical_user_export_tree(
    output_dir: str | Path,
    *,
    canonical_rows: list[dict[str, str]] | None = None,
    fieldnames: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Return human-readable invariant failures (empty list = pass)."""
    root = Path(output_dir)
    fields = list(fieldnames or RECORD_FIELDS)
    export_root = user_facing_export_root(root)
    master_path = user_facing_master_path(root)
    issues: list[str] = []

    if not master_path.is_file():
        return [f"user-facing master CSV missing: {master_path}"]

    master_fields, master_rows = _read_csv(master_path)
    if canonical_rows is not None:
        if len(canonical_rows) != len(master_rows):
            issues.append(
                f"user-facing master row count {len(master_rows)} != canonical {len(canonical_rows)}"
            )
        if [_row_key(r, fields) for r in canonical_rows] != [
            _row_key({k: r.get(k, "") for k in fields}, fields) for r in master_rows
        ]:
            issues.append("user-facing master CSV does not match the canonical dataframe")

    if list(master_fields) != fields:
        issues.append("user-facing master CSV header does not match the unified schema")

    master_by_id: dict[str, dict[str, str]] = {}
    blank_ids = 0
    for row in master_rows:
        rid = row.get("record_id") or ""
        if not rid:
            blank_ids += 1
            continue
        if rid in master_by_id:
            issues.append(f"duplicate record_id in user-facing master: {rid}")
        master_by_id[rid] = {k: row.get(k, "") for k in fields}

    if blank_ids:
        issues.append(f"{blank_ids} user-facing master row(s) have blank record_id")

    cat_dir = export_root / USER_FACING_CATEGORY_DIRNAME
    sub_root = export_root / USER_FACING_SUBCATEGORY_DIRNAME
    category_tables: dict[str, list[dict[str, str]]] = {}
    if cat_dir.is_dir():
        for path in sorted(cat_dir.glob("*.csv")):
            slug = path.stem
            cat_fields, cat_rows = _read_csv(path)
            if list(cat_fields) != fields:
                issues.append(f"schema mismatch in {path.relative_to(root)}")
            category_tables[slug] = cat_rows
            if not cat_rows:
                issues.append(f"empty user-facing category CSV should not exist: {path.name}")

    # No CSVs directly under subcategory_csvs/ (must be nested).
    if sub_root.is_dir():
        for stray in sorted(sub_root.glob("*.csv")):
            issues.append(f"subcategory CSV is not nested under a category folder: {stray.name}")

    subcategory_tables: dict[tuple[str, str], list[dict[str, str]]] = {}
    if sub_root.is_dir():
        for cat_folder in sorted(p for p in sub_root.iterdir() if p.is_dir()):
            cat_slug = cat_folder.name
            for path in sorted(cat_folder.glob("*.csv")):
                sub_slug = path.stem
                sub_fields, sub_rows = _read_csv(path)
                if list(sub_fields) != fields:
                    issues.append(f"schema mismatch in {path.relative_to(root)}")
                if not sub_rows:
                    issues.append(f"empty user-facing subcategory CSV should not exist: {path}")
                subcategory_tables[(cat_slug, sub_slug)] = sub_rows

    # Every category-CSV row exists in master; no extras; exact values.
    seen_in_category: dict[str, str] = {}
    for cat_slug, cat_rows in category_tables.items():
        for row in cat_rows:
            rid = row.get("record_id") or ""
            if not rid or rid not in master_by_id:
                issues.append(f"category CSV {cat_slug}.csv has row {rid!r} not in master")
                continue
            if _row_key({k: row.get(k, "") for k in fields}, fields) != _row_key(
                master_by_id[rid], fields
            ):
                issues.append(f"category CSV {cat_slug}.csv values differ from master for {rid}")
            expected_cat = _safe_slug(
                master_by_id[rid].get("subcategory_slug") or master_by_id[rid].get("subcategory")
            )
            if expected_cat != cat_slug:
                issues.append(
                    f"row {rid} from category {expected_cat} leaked into {cat_slug}.csv"
                )
            if rid in seen_in_category:
                issues.append(
                    f"record_id {rid} appears in multiple category CSVs "
                    f"({seen_in_category[rid]} and {cat_slug})"
                )
            seen_in_category[rid] = cat_slug

    assigned_master_ids = {
        rid
        for rid, row in master_by_id.items()
        if _safe_slug(row.get("subcategory_slug") or row.get("subcategory"))
    }
    missing_from_category = sorted(assigned_master_ids - set(seen_in_category))
    if missing_from_category:
        issues.append(
            "master rows missing from the matching category CSV: "
            + ", ".join(missing_from_category[:10])
        )

    concat_ids: list[str] = []
    for cat_slug in sorted(category_tables):
        concat_ids.extend(r.get("record_id") or "" for r in category_tables[cat_slug])
    if sorted(concat_ids) != sorted(assigned_master_ids):
        issues.append(
            "concatenating category CSVs does not reproduce assigned master record_ids"
        )

    # Subcategory CSVs: subset of parent category + master; no cross-category leakage.
    seen_in_sub: dict[str, tuple[str, str]] = {}
    for (cat_slug, sub_slug), sub_rows in subcategory_tables.items():
        parent_ids = {r.get("record_id") or "" for r in category_tables.get(cat_slug, [])}
        parent_ids.discard("")
        for row in sub_rows:
            rid = row.get("record_id") or ""
            if rid not in master_by_id:
                issues.append(
                    f"subcategory CSV {cat_slug}/{sub_slug}.csv has row {rid!r} not in master"
                )
                continue
            if rid not in parent_ids:
                issues.append(
                    f"subcategory CSV {cat_slug}/{sub_slug}.csv has row {rid!r} "
                    "not in the parent category CSV"
                )
            expected_cat = _safe_slug(
                master_by_id[rid].get("subcategory_slug") or master_by_id[rid].get("subcategory")
            )
            expected_sub = _safe_slug(
                master_by_id[rid].get("sub_subcategory_slug")
                or master_by_id[rid].get("sub_subcategory")
            )
            if expected_cat != cat_slug:
                issues.append(
                    f"row {rid} from category {expected_cat} leaked into "
                    f"{cat_slug}/{sub_slug}.csv"
                )
            if expected_sub != sub_slug:
                issues.append(
                    f"row {rid} from subcategory {expected_sub} leaked into {sub_slug}.csv"
                )
            if _row_key({k: row.get(k, "") for k in fields}, fields) != _row_key(
                master_by_id[rid], fields
            ):
                issues.append(
                    f"subcategory CSV {cat_slug}/{sub_slug}.csv values differ from master for {rid}"
                )
            if rid in seen_in_sub:
                issues.append(f"record_id {rid} appears in multiple subcategory CSVs")
            seen_in_sub[rid] = (cat_slug, sub_slug)

    assigned_sub_ids = {
        rid
        for rid, row in master_by_id.items()
        if _safe_slug(row.get("subcategory_slug") or row.get("subcategory"))
        and _safe_slug(row.get("sub_subcategory_slug") or row.get("sub_subcategory"))
    }
    missing_from_sub = sorted(assigned_sub_ids - set(seen_in_sub))
    if missing_from_sub:
        issues.append(
            "master rows missing from the matching subcategory CSV: "
            + ", ".join(missing_from_sub[:10])
        )

    if len(concat_ids) != len(set(concat_ids)):
        issues.append("export introduced duplicate rows across category CSVs")

    return issues


def user_facing_validation_checks(
    output_dir: str | Path,
    *,
    internal_master_rows: list[dict[str, str]] | None = None,
    fieldnames: tuple[str, ...] | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Checks in the final_metadata report format."""
    root = Path(output_dir)
    fields = list(fieldnames or RECORD_FIELDS)
    export_root = user_facing_export_root(root)
    master_path = user_facing_master_path(root)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, expected: Any, observed: Any, message: str) -> None:
        checks.append(
            {
                "check_name": name,
                "status": "pass" if ok else "fail",
                "expected": expected,
                "observed": observed,
                "message": message,
            }
        )

    add(
        "user_facing_master_csv_exists",
        master_path.is_file(),
        str(master_path),
        "present" if master_path.is_file() else "missing",
        "User-facing master CSV exists"
        if master_path.is_file()
        else "User-facing master CSV missing",
    )
    if not master_path.is_file():
        return checks

    master_fields, master_rows = _read_csv(master_path)
    add(
        "user_facing_master_schema",
        list(master_fields) == fields,
        fields[:5] + ["..."],
        master_fields[:8],
        "User-facing master uses the unified schema",
    )

    if internal_master_rows is not None:
        internal_ids = [r.get("record_id") or "" for r in internal_master_rows]
        user_ids = [r.get("record_id") or "" for r in master_rows]
        add(
            "user_facing_master_matches_internal_master",
            sorted(internal_ids) == sorted(user_ids) and len(internal_ids) == len(user_ids),
            len(internal_ids),
            len(user_ids),
            "User-facing master is the same canonical dataframe as all_records/",
        )

    issues = validate_canonical_user_export_tree(root, fieldnames=fields)
    add(
        "user_facing_export_invariants",
        not issues,
        "master/category/subcategory row conservation and identical schemas",
        issues[:8],
        "User-facing export invariants hold" if not issues else issues[0],
    )

    cat_dir = export_root / USER_FACING_CATEGORY_DIRNAME
    sub_root = export_root / USER_FACING_SUBCATEGORY_DIRNAME
    cat_files = list(cat_dir.glob("*.csv")) if cat_dir.is_dir() else []
    nested = list(sub_root.glob("*/*.csv")) if sub_root.is_dir() else []
    stray = list(sub_root.glob("*.csv")) if sub_root.is_dir() else []
    add(
        "user_facing_subcategory_csvs_are_nested",
        not stray,
        "subcategory_csvs/<category>/<subcategory>.csv",
        [p.name for p in stray],
        "Subcategory CSVs are nested under category folders",
    )
    add(
        "user_facing_empty_csvs_omitted",
        all(_csv_has_rows(p) for p in cat_files + nested),
        "no empty user-facing CSVs",
        {
            "category_csv_count": len(cat_files),
            "subcategory_csv_count": len(nested),
        },
        "Empty user-facing category/subcategory CSVs are omitted",
    )
    return checks


def _csv_has_rows(path: Path) -> bool:
    _, rows = _read_csv(path)
    return bool(rows)


def render_user_facing_tree(output_dir: str | Path) -> str:
    """Return a text tree of the user-facing export (for tests/docs)."""
    export_root = user_facing_export_root(output_dir)
    if not export_root.exists():
        return "(missing)"
    lines = [f"{USER_FACING_EXPORT_DIRNAME}/"]
    master = export_root / USER_FACING_MASTER_FILENAME
    if master.is_file():
        lines.append(f"├── {USER_FACING_MASTER_FILENAME}")
    unassigned = export_root / USER_FACING_UNASSIGNED_FILENAME
    cat_dir = export_root / USER_FACING_CATEGORY_DIRNAME
    sub_root = export_root / USER_FACING_SUBCATEGORY_DIRNAME
    cat_files = sorted(cat_dir.glob("*.csv")) if cat_dir.is_dir() else []
    cat_folders = sorted(p for p in sub_root.iterdir() if p.is_dir()) if sub_root.is_dir() else []

    lines.append(f"├── {USER_FACING_CATEGORY_DIRNAME}/")
    if not cat_files:
        lines.append("│   └── (none; no populated categories)")
    else:
        for i, path in enumerate(cat_files):
            prefix = "│   └──" if i == len(cat_files) - 1 else "│   ├──"
            lines.append(f"{prefix} {path.name}")

    last_top = not unassigned.is_file()
    lines.append(f"{'└──' if last_top else '├──'} {USER_FACING_SUBCATEGORY_DIRNAME}/")
    if not cat_folders:
        lines.append("    └── (none; no populated subcategories)")
    else:
        for i, folder in enumerate(cat_folders):
            last_folder = i == len(cat_folders) - 1
            folder_prefix = "    └──" if last_folder else "    ├──"
            lines.append(f"{folder_prefix} {folder.name}/")
            files = sorted(folder.glob("*.csv"))
            child_indent = "        " if last_folder else "    │   "
            for j, path in enumerate(files):
                file_prefix = "└──" if j == len(files) - 1 else "├──"
                lines.append(f"{child_indent}{file_prefix} {path.name}")
    if unassigned.is_file():
        lines.append(f"└── {USER_FACING_UNASSIGNED_FILENAME}")
    return "\n".join(lines)
