"""Generate reviewable draft configs for recommended SCM categories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.scm.schema import NA


def build_category_config_payload(
    *,
    category: str,
    aggregated: dict[str, Any] | None = None,
    discovered_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aggregated = aggregated or {}
    discovered_row = discovered_row or {}
    display = category.strip()
    category_id = (
        display.lower()
        .replace("/", " ")
        .replace("-", " ")
        .replace("  ", " ")
        .strip()
        .replace(" ", "_")
    )
    aliases = discovered_row.get("common_aliases") or aggregated.get("common_aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases] if aliases != NA else []
    materials = (
        discovered_row.get("canonical_material_names")
        or aggregated.get("canonical_material_names")
        or [display]
    )
    if isinstance(materials, str):
        materials = [materials]

    search_terms = list(
        dict.fromkeys(
            [display, *[str(a) for a in aliases[:8]], *[str(m) for m in materials[:5]]],
        ),
    )
    return {
        "category_id": category_id,
        "display_name": display,
        "representative_material_names": materials,
        "aliases": aliases,
        "suggested_search_terms": search_terms,
        "suggested_negative_terms": [],
        "source_counts": {
            "total_record_count": aggregated.get("total_record_count")
            or discovered_row.get("total_record_count")
            or 0,
            "unique_source_count": aggregated.get("unique_source_count")
            or discovered_row.get("unique_source_count")
            or 0,
            "literature_source_count": aggregated.get("literature_source_count")
            or discovered_row.get("literature_source_count")
            or 0,
            "web_source_count": aggregated.get("web_source_count")
            or discovered_row.get("web_source_count")
            or 0,
        },
        "example_sources": aggregated.get("example_source_ids")
        or discovered_row.get("example_source_ids")
        or [],
        "relationship_to_seed_categories": aggregated.get("seed_category_overlap")
        or discovered_row.get("seed_category_overlap")
        or NA,
        "status": "proposed",
    }


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#{}[]&*!|>'\"%@`"):
        return json.dumps(text, ensure_ascii=False)
    return text


def _to_simple_yaml(data: Any, indent: int = 0) -> list[str]:
    spaces = "  " * indent
    lines: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{spaces}{key}:")
                lines.extend(_to_simple_yaml(value, indent + 1))
            else:
                lines.append(f"{spaces}{key}: {_yaml_scalar(value)}")
    elif isinstance(data, list):
        if not data:
            lines.append(f"{spaces}[]")
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{spaces}-")
                lines.extend(_to_simple_yaml(item, indent + 1))
            else:
                lines.append(f"{spaces}- {_yaml_scalar(item)}")
    else:
        lines.append(f"{spaces}{_yaml_scalar(data)}")
    return lines


def write_category_config(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(_to_simple_yaml(payload)) + "\n"
    output_path.write_text(text, encoding="utf-8")
    return output_path
