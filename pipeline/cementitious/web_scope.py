"""Canonical Concrete Decarbonization web-search scope and retrieval coverage.

Organizational parents (Level 0–2, and Level 3 nodes that have Level-4 children)
do not independently trigger Tavily queries. Searchable technology nodes are:

- every Level-4 leaf
- every Level-3 node that has no children

Records roll upward through the hierarchical export. Runtime 9×58 selection
(``SELECTED_SUBCATEGORIES`` / ``SELECTED_SUB_SUBCATEGORIES``) remains an explicit
restriction (pilot smoke) and uses the legacy query planner.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from pipeline.cementitious.decarbonization_taxonomy import (
    TAXONOMY_NA,
    DecarbNode,
    DecarbonizationTaxonomy,
    get_decarbonization_taxonomy,
)
from pipeline.cementitious.paths import is_taxonomy_na
from pipeline.cementitious.shard_io import atomic_write_json
from pipeline.cementitious.taxonomy import Taxonomy, get_taxonomy
from pipeline.cementitious.taxonomy_migration import runtime_assignment_for_decarb_node

WEB_SEARCH_SCOPE_CANONICAL = "canonical"
WEB_SEARCH_SCOPE_RUNTIME = "runtime"
WEB_SEARCH_SCOPE_AUTO = "auto"

ORGANIZATIONAL_LEVELS = frozenset({0, 1, 2})

TAXONOMY_PROPAGATION_KEYS: tuple[str, ...] = (
    "taxonomy_level_0",
    "taxonomy_level_0_slug",
    "taxonomy_level_1",
    "taxonomy_level_1_slug",
    "taxonomy_level_2",
    "taxonomy_level_2_slug",
    "taxonomy_level_3",
    "taxonomy_level_3_slug",
    "taxonomy_level_4",
    "taxonomy_level_4_slug",
    "taxonomy_path",
    "taxonomy_search_level",
    "web_search_node_slug",
    "web_search_node_role",
    "category",
    "subcategory",
    "subcategory_slug",
    "sub_subcategory",
    "sub_subcategory_slug",
)


def resolve_web_search_scope(
    *,
    selected_subcategories: list[str] | None = None,
    selected_sub_subcategories: list[str] | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    """Return ``canonical`` or ``runtime``.

    ``auto`` (default): explicit runtime selection → runtime planner; otherwise
    the full canonical searchable-node set.
    """
    env = dict(os.environ if environ is None else environ)
    raw = (env.get("WEB_SEARCH_SCOPE") or WEB_SEARCH_SCOPE_AUTO).strip().lower()
    if raw in {"runtime", "legacy", "cementitious"}:
        return WEB_SEARCH_SCOPE_RUNTIME
    if raw in {"canonical", "decarbonization", "full"}:
        return WEB_SEARCH_SCOPE_CANONICAL
    if selected_subcategories or selected_sub_subcategories:
        return WEB_SEARCH_SCOPE_RUNTIME
    return WEB_SEARCH_SCOPE_CANONICAL


def node_search_role(node: DecarbNode) -> str:
    """``organizational_parent`` vs ``searchable_technology``."""
    if node.level in ORGANIZATIONAL_LEVELS:
        return "organizational_parent"
    if node.level == 3 and node.children_slugs:
        return "organizational_parent"
    if node.level in {3, 4}:
        return "searchable_technology"
    return "organizational_parent"


def searchable_web_nodes(
    taxonomy: DecarbonizationTaxonomy | None = None,
    *,
    include_parent_l3: bool = False,
    levels: Iterable[int] | None = None,
) -> list[DecarbNode]:
    """Technology nodes that independently trigger web searches.

    Default: all Level-4 leaves plus childless Level-3 nodes. Level 0–2 never
    search independently. Level-3 parents of Level-4 children are organizational
    unless ``include_parent_l3`` is true.
    """
    tax = taxonomy or get_decarbonization_taxonomy()
    wanted = set(int(x) for x in (levels or (3, 4)))
    include = include_parent_l3 or _env_truthy("WEB_SEARCH_INCLUDE_PARENT_L3")
    nodes: list[DecarbNode] = []
    for node in tax.ordered_nodes():
        if node.level not in wanted:
            continue
        if node.level == 4:
            nodes.append(node)
        elif node.level == 3:
            if include or not node.children_slugs:
                nodes.append(node)
    return nodes


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_web_search_levels(environ: dict[str, str] | None = None) -> tuple[int, ...]:
    env = dict(os.environ if environ is None else environ)
    raw = (env.get("WEB_SEARCH_LEVELS") or "3,4").strip()
    levels: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value not in {3, 4}:
            raise ValueError(f"WEB_SEARCH_LEVELS entries must be 3 or 4, got {value}")
        if value not in levels:
            levels.append(value)
    if not levels:
        return (3, 4)
    return tuple(levels)


def decarb_fields(node: DecarbNode, *, runtime: Taxonomy | None = None) -> dict[str, Any]:
    """Canonical taxonomy columns plus optional 9×58 runtime assignment."""
    labels = list(node.path_labels)
    slugs = list(node.path_slugs)
    while len(labels) < 5:
        labels.append(TAXONOMY_NA)
        slugs.append(TAXONOMY_NA)
    fields: dict[str, Any] = {
        "taxonomy_level_0": labels[0],
        "taxonomy_level_0_slug": slugs[0],
        "taxonomy_level_1": labels[1],
        "taxonomy_level_1_slug": slugs[1],
        "taxonomy_level_2": labels[2],
        "taxonomy_level_2_slug": slugs[2],
        "taxonomy_level_3": labels[3],
        "taxonomy_level_3_slug": slugs[3],
        "taxonomy_level_4": labels[4],
        "taxonomy_level_4_slug": slugs[4],
        "taxonomy_path": node.path,
        "taxonomy_search_level": node.level,
        "web_search_node_slug": node.slug,
        "web_search_node_role": node_search_role(node),
        "category": labels[1] if not is_taxonomy_na(labels[1]) else "",
    }
    assignment = runtime_assignment_for_decarb_node(node, runtime=runtime)
    if assignment:
        fields.update(assignment)
    else:
        fields.setdefault("subcategory", "")
        fields.setdefault("subcategory_slug", "")
        fields.setdefault("sub_subcategory", "")
        fields.setdefault("sub_subcategory_slug", "")
    return fields


def copy_taxonomy_fields(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for key in TAXONOMY_PROPAGATION_KEYS:
        if key in src and src[key] not in {None, ""}:
            dst[key] = src[key]
    return dst


def stamp_search_intent_taxonomy(record: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Overwrite taxonomy columns from the web-search node (search intent wins)."""
    copy_taxonomy_fields(record, src)
    return record


def searchable_node_summaries(
    taxonomy: DecarbonizationTaxonomy | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    tax = taxonomy or get_decarbonization_taxonomy()
    runtime = get_taxonomy()
    out: list[dict[str, Any]] = []
    for node in searchable_web_nodes(tax, **kwargs):
        fields = decarb_fields(node, runtime=runtime)
        out.append(
            {
                "path": node.path,
                "path_labels": list(node.path_labels),
                "slug": node.slug,
                "label": node.label,
                "level": node.level,
                "role": node_search_role(node),
                "aliases": list(node.aliases),
                "level_1": fields["taxonomy_level_1"],
                "level_2": fields["taxonomy_level_2"],
                "level_3": fields["taxonomy_level_3"],
                "level_4": fields["taxonomy_level_4"],
                "runtime_subcategory_slug": fields.get("subcategory_slug") or "",
                "runtime_sub_subcategory_slug": fields.get("sub_subcategory_slug") or "",
            }
        )
    return out


def write_web_search_scope_manifest(
    output_dir: str | Path,
    *,
    queries: list[dict[str, Any]],
    scope: str,
    nodes: list[dict[str, Any]] | None = None,
) -> Path:
    root = Path(output_dir)
    meta = root / "metadata"
    meta.mkdir(parents=True, exist_ok=True)
    by_node: Counter[str] = Counter()
    for q in queries:
        by_node[str(q.get("taxonomy_path") or q.get("sub_subcategory_slug") or "")] += 1
    payload = {
        "web_search_scope": scope,
        "scope_rule": (
            "Search Level-4 technology leaves and childless Level-3 nodes. "
            "Level 0–2 and Level-3 parents of Level-4 children are organizational "
            "and do not independently trigger Tavily queries. Records roll up via "
            "hierarchical export."
        ),
        "searched_node_count": len(nodes or []),
        "query_count": len(queries),
        "queries_by_taxonomy_path": dict(by_node),
        "nodes": nodes or [],
        "level_1_branches_searched": sorted(
            {n.get("level_1") for n in (nodes or []) if n.get("level_1")}
        ),
        "restricted_to_chemical_absorption": (
            len(nodes or []) == 1
            and (nodes or [{}])[0].get("slug") in {"chemical_absorption", "amine_absorption"}
        ),
    }
    path = meta / "web_search_scope.json"
    atomic_write_json(path, payload)
    return path


def build_retrieval_coverage_manifest(output_dir: str | Path) -> dict[str, Any]:
    """Per-searched-node literature vs web counts for the final canonical table."""
    root = Path(output_dir)
    meta = root / "metadata"
    queries = _load_json_list(meta / "web_queries.json")
    search_summary = _load_json(meta / "web_search_merge_summary.json")
    extract_summary = _load_json(meta / "web_extraction_merge_summary.json")
    screening = _load_jsonl(meta / "web_screening_results.jsonl")
    web_raw = _load_jsonl(meta / "web_records_raw.jsonl")
    scope = _load_json(meta / "web_search_scope.json")

    master_rows = _load_master_rows(root)
    lit_final = [r for r in master_rows if _origin(r) == "Literature"]
    web_final = [r for r in master_rows if _origin(r) == "Web"]

    nodes = list(scope.get("nodes") or [])
    if not nodes:
        nodes = _nodes_from_queries(queries)

    tax = get_decarbonization_taxonomy()
    by_path = {str(n.get("path") or ""): n for n in nodes}
    for l4 in tax.nodes_at(4):
        if l4.path not in by_path:
            fields = decarb_fields(l4)
            nodes.append(
                {
                    "path": l4.path,
                    "path_labels": list(l4.path_labels),
                    "slug": l4.slug,
                    "label": l4.label,
                    "level": 4,
                    "level_1": fields.get("taxonomy_level_1") or "",
                    "aliases": list(l4.aliases),
                    "skip_reason": "not_in_query_plan",
                }
            )
            by_path[l4.path] = nodes[-1]

    query_strings: dict[str, list[str]] = {}
    query_counts: Counter[str] = Counter()
    unique_urls: dict[str, set[str]] = {}
    for q in queries:
        key = _node_key(q)
        query_counts[key] += 1
        query_strings.setdefault(key, []).append(str(q.get("query_text") or ""))

    retrieved: Counter[str] = Counter()
    for row in _load_jsonl(meta / "web_search_results_raw.jsonl"):
        if row.get("url"):
            key = _node_key(row)
            retrieved[key] += 1
            unique_urls.setdefault(key, set()).add(str(row.get("url")))

    retained: Counter[str] = Counter()
    for row in screening:
        if str(row.get("relevance_decision") or "").lower() in {"relevant", "uncertain"}:
            retained[_node_key(row)] += 1

    extracted: Counter[str] = Counter()
    for row in web_raw:
        if row.get("extraction_error"):
            continue
        extracted[_node_key(row)] += 1

    lit_by_path: Counter[str] = Counter()
    web_by_path: Counter[str] = Counter()
    for row in lit_final:
        lit_by_path[_record_path_key(row)] += 1
    for row in web_final:
        web_by_path[_record_path_key(row)] += 1

    per_node: list[dict[str, Any]] = []
    zero_web_results: list[str] = []
    for node in nodes:
        path = str(node.get("path") or node.get("taxonomy_path") or "")
        key = path or str(node.get("slug") or "")
        n_retrieved = int(retrieved.get(key, 0) or retrieved.get(str(node.get("slug") or ""), 0))
        n_queries = int(query_counts.get(key, 0) or query_counts.get(str(node.get("slug") or ""), 0))
        rec = {
            "taxonomy_path": path,
            "full_taxonomy_path": " → ".join(node.get("path_labels") or []) or path,
            "path_labels": node.get("path_labels") or [],
            "slug": node.get("slug") or "",
            "label": node.get("label") or "",
            "canonical_label": node.get("label") or "",
            "level": node.get("level"),
            "level_1": node.get("level_1") or "",
            "aliases_used": node.get("aliases") or [],
            "query_strings": query_strings.get(key) or query_strings.get(str(node.get("slug") or ""), []),
            "query_count": n_queries,
            "literature_candidates": int(lit_by_path.get(path, 0)),
            "web_queries": n_queries,
            "raw_result_count": n_retrieved,
            "unique_url_count": len(unique_urls.get(key) or unique_urls.get(str(node.get("slug") or ""), set())),
            "web_results_retrieved": n_retrieved,
            "web_results_retained_after_screening": int(
                retained.get(key, 0) or retained.get(str(node.get("slug") or ""), 0)
            ),
            "screened_result_count": int(
                retained.get(key, 0) or retained.get(str(node.get("slug") or ""), 0)
            ),
            "web_records_extracted": int(
                extracted.get(key, 0) or extracted.get(str(node.get("slug") or ""), 0)
            ),
            "extracted_record_count": int(
                extracted.get(key, 0) or extracted.get(str(node.get("slug") or ""), 0)
            ),
            "merged_final_records": int(lit_by_path.get(path, 0)) + int(web_by_path.get(path, 0)),
            "final_retained_record_count": int(lit_by_path.get(path, 0)) + int(web_by_path.get(path, 0)),
            "merged_final_literature": int(lit_by_path.get(path, 0)),
            "merged_final_web": int(web_by_path.get(path, 0)),
            "zero_result_flag": n_queries > 0 and n_retrieved == 0,
            "skip_reason": node.get("skip_reason") or ("" if n_queries else "no_queries_generated"),
        }
        per_node.append(rec)
        if n_queries > 0 and n_retrieved == 0:
            zero_web_results.append(path or rec["slug"])

    source_types = Counter(str(r.get("source_type") or "") for r in master_rows)
    origins = Counter(_origin(r) for r in master_rows)
    payload = {
        "web_search_scope": scope.get("web_search_scope") or "",
        "searched_node_count": len(nodes),
        "searched_taxonomy_paths": [n.get("path") or n.get("slug") for n in nodes],
        "level_1_branches_searched": scope.get("level_1_branches_searched")
        or sorted({n.get("level_1") for n in nodes if n.get("level_1")}),
        "nodes_with_zero_web_results": zero_web_results,
        "totals": {
            "literature_final_records": len(lit_final),
            "web_final_records": len(web_final),
            "final_records": len(master_rows),
            "web_queries": len(queries),
            "web_results_retrieved": int(search_summary.get("raw_result_count") or 0),
            "web_results_retained_after_screening": int(
                search_summary.get("relevant_url_count") or 0
            ),
            "web_records_extracted": int(extract_summary.get("extracted_record_count") or 0),
        },
        "totals_by_evidence_origin": dict(origins),
        "totals_by_source_type": dict(source_types),
        "per_searched_node": per_node,
    }
    atomic_write_json(meta / "retrieval_coverage_manifest.json", payload)
    return payload


def _node_key(row: dict[str, Any]) -> str:
    return str(
        row.get("taxonomy_path")
        or row.get("web_search_node_slug")
        or row.get("sub_subcategory_slug")
        or ""
    )


def _record_path_key(row: dict[str, Any]) -> str:
    if row.get("taxonomy_path"):
        return str(row["taxonomy_path"])
    labels = [
        str(row.get(f"taxonomy_level_{i}") or "")
        for i in range(5)
        if row.get(f"taxonomy_level_{i}") not in {"", None, TAXONOMY_NA, "N.A."}
    ]
    if labels:
        from pipeline.cementitious.paths import taxonomy_slugify

        try:
            return "/".join(taxonomy_slugify(x) for x in labels)
        except ValueError:
            return "/".join(x for x in labels)
    return str(row.get("sub_subcategory_slug") or "")


def _origin(row: dict[str, Any]) -> str:
    raw = str(row.get("evidence_origin") or "").strip()
    if raw == "Web":
        return "Web"
    return "Literature"


def _nodes_from_queries(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for q in queries:
        key = _node_key(q)
        if not key or key in seen:
            continue
        seen[key] = {
            "path": q.get("taxonomy_path") or "",
            "path_labels": [
                q.get(f"taxonomy_level_{i}")
                for i in range(5)
                if q.get(f"taxonomy_level_{i}") not in {"", None, TAXONOMY_NA}
            ],
            "slug": q.get("web_search_node_slug") or q.get("sub_subcategory_slug") or "",
            "label": q.get("sub_subcategory") or q.get("taxonomy_level_4") or q.get("taxonomy_level_3"),
            "level": q.get("taxonomy_search_level"),
            "level_1": q.get("taxonomy_level_1") or "",
        }
    return list(seen.values())


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _load_master_rows(root: Path) -> list[dict[str, Any]]:
    import csv

    candidates = [
        root / "all_records" / "cementitious_materials_all_records.csv",
        root / "metadata" / "merged_records.csv",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    combined = root / "metadata" / "combined_records_pre_dedupe.jsonl"
    if combined.is_file():
        return _load_jsonl(combined)
    return []
