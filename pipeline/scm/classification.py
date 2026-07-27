"""Corpus-level LLM category clustering for SCM discovery."""

from __future__ import annotations

import logging
from typing import Any

from pipeline.llm_utils import DEFAULT_MODEL, InvalidJSONError, _parse_json_response
from pipeline.openai_client import call_openai
from pipeline.scm.prompts import DISCOVERY_SYSTEM_PROMPT, build_clustering_prompt

logger = logging.getLogger(__name__)


def cluster_categories_with_llm(
    aggregated_candidates_json: str,
    *,
    model: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    """
    Ask the LLM to group aggregated candidates.

    Does not overwrite source-level records — returns derived groupings only.
    """
    prompt = build_clustering_prompt(aggregated_candidates_json=aggregated_candidates_json)
    try:
        raw = call_openai(
            model=model,
            messages=[
                {"role": "system", "content": DISCOVERY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        payload = _parse_json_response(raw)
    except (InvalidJSONError, Exception) as exc:
        logger.warning("SCM corpus clustering LLM call failed: %s", exc)
        return []

    groupings = payload.get("groupings") if isinstance(payload, dict) else None
    if not isinstance(groupings, list):
        return []
    return [item for item in groupings if isinstance(item, dict)]


def heuristic_groupings(aggregated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic fallback used in tests / offline mode."""
    groupings: list[dict[str, Any]] = []
    for item in aggregated:
        overlap = item.get("seed_category_overlap") or []
        if isinstance(overlap, str):
            overlap = [overlap]
        overlap_clean = [x for x in overlap if x and x != "NA"]
        if overlap_clean:
            action = "MERGE_WITH_SEED_CATEGORY"
            reason = f"Overlaps seed category {overlap_clean[0]}"
            coherence = "High"
        elif int(item.get("total_record_count") or 0) >= 20:
            action = "CREATE_DEDICATED_PIPELINE"
            reason = "High record count heuristic"
            coherence = "Medium"
        else:
            action = "RETAIN_AS_BROAD_DISCOVERY_CATEGORY"
            reason = "Default retention"
            coherence = "Medium"
        groupings.append(
            {
                "proposed_category": item.get("proposed_category"),
                "canonical_material_names": item.get("canonical_material_names"),
                "common_aliases": item.get("common_aliases"),
                "seed_category_overlap": overlap_clean[0] if overlap_clean else "NA",
                "classification_coherence": coherence,
                "recommended_action": action,
                "recommendation_reason": reason,
            },
        )
    return groupings
