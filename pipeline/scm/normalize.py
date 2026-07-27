"""Material-name normalization with manual alias overrides."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pipeline.scm.config import alias_overrides_path
from pipeline.scm.schema import NA, normalize_confidence

logger = logging.getLogger(__name__)


def load_alias_overrides(path: Path | None = None) -> dict[str, str]:
    file_path = path or alias_overrides_path()
    if not file_path.is_file():
        logger.info("No SCM alias overrides at %s", file_path)
        return {}
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Alias overrides must be a JSON object: {file_path}")
    return {str(k).strip(): str(v).strip() for k, v in data.items() if str(k).strip()}


def _lookup_override(raw: str, overrides: dict[str, str]) -> str | None:
    if raw in overrides:
        return overrides[raw]
    lowered = {k.lower(): v for k, v in overrides.items()}
    return lowered.get(raw.lower())


def _lightweight_canonicalize(raw: str) -> str:
    """Normalize obvious spelling/abbreviation variants without merging distinct feedstocks."""
    text = re.sub(r"\s+", " ", raw.strip())
    # Title-case multi-word names unless already an acronym
    if text.isupper() and len(text) <= 6:
        return text
    return text[:1].upper() + text[1:] if text else NA


def normalize_material_name(
    raw_material_name: str,
    *,
    proposed_canonical_name: str = NA,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Preserve every raw material name. Apply manual overrides first, then light
    canonicalization. Never merge materially distinct feedstocks solely on similarity.
    """
    overrides = overrides if overrides is not None else load_alias_overrides()
    raw = (raw_material_name or "").strip() or NA
    proposed = (proposed_canonical_name or "").strip() or NA

    override = None if raw == NA else _lookup_override(raw, overrides)
    if override:
        return {
            "raw_material_name": raw,
            "proposed_canonical_name": proposed if proposed != NA else override,
            "final_canonical_name": override,
            "normalization_method": "manual_override",
            "normalization_confidence": "High",
            "manual_override_applied": "true",
        }

    if proposed != NA:
        final = proposed
        method = "proposed_canonical"
        confidence = "Medium"
    elif raw != NA:
        final = _lightweight_canonicalize(raw)
        method = "lightweight_canonicalize"
        confidence = "Low"
    else:
        final = NA
        method = "missing"
        confidence = NA

    return {
        "raw_material_name": raw,
        "proposed_canonical_name": proposed,
        "final_canonical_name": final,
        "normalization_method": method,
        "normalization_confidence": normalize_confidence(confidence),
        "manual_override_applied": "false",
    }


def normalize_discovery_records(
    records: list[dict[str, Any]],
    *,
    overrides: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    overrides = overrides if overrides is not None else load_alias_overrides()
    results: list[dict[str, str]] = []
    for record in records:
        raw = str(record.get("raw_material_name") or NA)
        proposed = str(
            record.get("proposed_canonical_name")
            or record.get("canonical_material_name")
            or NA,
        )
        results.append(
            normalize_material_name(
                raw,
                proposed_canonical_name=proposed,
                overrides=overrides,
            ),
        )
    return results
