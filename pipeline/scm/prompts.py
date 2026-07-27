"""Prompt templates for SCM literature, web, discovery, and clustering."""

from __future__ import annotations

import json

from pipeline.scm.schema import (
    DISCOVERY_FIELDS,
    EVIDENCE_FIELDS,
    NA,
    SEED_CATEGORY_IDS,
)
from pipeline.scm.seed_categories import SCM_SEED_CATEGORIES

SYSTEM_PROMPT = """You are a research analyst specializing in supplementary cementitious materials (SCMs)
for cement and concrete decarbonization.

Extract machine-readable structured data from the provided source(s).

STRICT RULES:
1. Return valid JSON only — no markdown, no commentary, no code fences.
2. Use the canonical schema exactly.
3. Use "NA" for every missing, unknown, or unavailable value. Never use empty strings.
4. Do not invent numerical values. If a number is not explicitly stated, use NA.
5. confidence must be exactly one of: High, Medium, Low, NA.
6. deployment_stage must be exactly one of: Laboratory, Pilot, Demonstration, Commercial, NA.
7. deployment_stage must reflect the CURRENT stage only — not future projections.
8. source_type must be exactly one of: Literature, Web, NA.
9. Put explanations only in notes.
10. Do not treat company claims as peer-reviewed measurements; preserve provenance.
11. For list-like fields (alternative_names, constituent_materials), use JSON arrays.
12. Never force an unfamiliar material into a seed category when extracting discovery records.
"""

DISCOVERY_SYSTEM_PROMPT = """You identify supplementary cementitious materials (SCMs) and SCM-like binder
replacements from scientific literature and web sources.

Screen for materials that replace Portland cement, clinker, or cementitious binder and contribute
to concrete or mortar performance through pozzolanic, hydraulic, latent hydraulic, or other
demonstrated chemical reactivity / strength-contributing mechanisms.

EXCLUDE (mark not relevant):
- Aggregate-only applications
- Fiber reinforcement
- Pigments
- Admixtures with no binder-replacement role
- General waste incorporation with no demonstrated strength contribution
- Materials mentioned only as background

Do NOT require numerical carbon reductions for relevance.

Return valid JSON only.
"""


def _evidence_example() -> str:
    example = {
        "records": [
            {
                **{field: NA for field in EVIDENCE_FIELDS},
                "raw_material_name": "GGBFS",
                "canonical_material_name": "Slag Cement",
                "alternative_names": ["GGBS", "ground granulated blast furnace slag"],
                "replacement_percentage": "40",
                "replacement_basis": "cement mass",
                "strength_result": "45 MPa",
                "strength_test_age": "28 days",
                "deployment_stage": "Commercial",
                "confidence": "Medium",
                "source_type": "Literature",
            },
        ],
    }
    return json.dumps(example, indent=2, ensure_ascii=False)


def _ternary_example() -> str:
    example = {
        "records": [
            {
                **{field: NA for field in EVIDENCE_FIELDS},
                "raw_material_name": "ternary OPC-slag-fly ash blend",
                "canonical_material_name": "Ternary Blends",
                "binder_system": "OPC / slag / fly ash",
                "constituent_materials": [
                    {"material_name": "Coal Fly Ash", "fraction_percent": 30},
                    {"material_name": "Slag Cement", "fraction_percent": 40},
                ],
                "replacement_percentage": "70",
                "replacement_basis": "cement mass",
                "seed_category": "ternary_blends",
                "source_type": "Literature",
                "confidence": "Medium",
            },
        ],
    }
    return json.dumps(example, indent=2, ensure_ascii=False)


def build_literature_extraction_prompt(
    *,
    seed_category_name: str,
    seed_category_slug: str,
    source_content: str,
    is_ternary: bool = False,
) -> str:
    ternary_note = ""
    if is_ternary:
        ternary_note = """
Ternary blends are binder SYSTEMS, not a single material.
Extract binder_system_name into binder_system, and constituent_materials as a JSON array of
objects with material_name and fraction_percent (use NA if a percentage is omitted).
Do not flatten all constituents into canonical_material_name.
"""
    return f"""Extract structured SCM evidence from the following scientific literature source.

Seed category context:
- Display name: {seed_category_name}
- seed_category id: {seed_category_slug}
- Category: Supplementary Cementitious Materials

Prioritize: material identity, origin, processing, replacement rate/basis, strength, test age,
comparison baseline, durability, carbon reduction, lifecycle boundary, energy, cost, availability.

Set source_type to "Literature".
Set category to "Supplementary Cementitious Materials".
Set seed_category to "{seed_category_slug}".
Set pipeline_branch to "seed_category".

Return JSON with a "records" array. Fields: {", ".join(EVIDENCE_FIELDS)}.
{ternary_note}
SOURCE DOCUMENT:
{source_content}

Example shape:
{_ternary_example() if is_ternary else _evidence_example()}

Return JSON only."""


def build_web_extraction_prompt(
    *,
    seed_category_name: str,
    seed_category_slug: str,
    source_content: str,
    is_ternary: bool = False,
) -> str:
    return f"""Extract structured SCM evidence from the following web source.

Seed category context:
- Display name: {seed_category_name}
- seed_category id: {seed_category_slug}

Prioritize: companies, commercial products, demonstration projects, production facilities,
deployment stage, project location, production scale, commercial claims, EPDs, procurement,
cost and emissions claims. Preserve provenance; do not treat claims as peer-reviewed fact.

Set source_type to "Web".
Set category to "Supplementary Cementitious Materials".
Set seed_category to "{seed_category_slug}".
Set pipeline_branch to "seed_category".

Return JSON with a "records" array. Fields: {", ".join(EVIDENCE_FIELDS)}.

SOURCE DOCUMENT:
{source_content}

Return JSON only."""


def build_discovery_screening_prompt(*, title: str, abstract: str) -> str:
    return f"""Decide whether this paper discusses SCM or SCM-like cement/clinker replacement materials.

Title: {title}
Abstract: {abstract}

Return JSON:
{{
  "is_relevant": true or false,
  "confidence": 0.0 to 1.0,
  "reason": "brief explanation based only on title and abstract",
  "mentioned_materials": ["optional raw material names if clearly stated"]
}}

Mark relevant for pozzolanic/hydraulic/latent-hydraulic/other reactive binder replacements.
Exclude aggregates-only, fibers, pigments, non-binder admixtures, background mentions.
Carbon reduction numbers are NOT required for relevance."""


def build_discovery_extraction_prompt(*, source_content: str, source_type: str) -> str:
    seed_list = json.dumps(list(SCM_SEED_CATEGORIES.keys()))
    return f"""Extract open-ended SCM discovery records from this {source_type} source.

Do NOT require a match to seed categories. If a material does not fit a seed category,
keep it as a discovery result (seed_category_match=false, matched_seed_category=NA).

Allowed matched_seed_category values ONLY: {seed_list} or "NA".

Keep these fields OPEN-ENDED (do not force into a closed taxonomy):
raw_material_name, raw_material_origin, raw_material_family, proposed_category_label.

Return JSON with a "records" array using fields:
{", ".join(DISCOVERY_FIELDS)}.

SOURCE DOCUMENT:
{source_content}

Return JSON only."""


def build_clustering_prompt(*, aggregated_candidates_json: str) -> str:
    return f"""You perform CORPUS-LEVEL classification of aggregated SCM candidate materials.

You receive aggregated evidence counts and representative examples — NOT isolated single sources.

Tasks:
1. Group aliases and closely related material labels.
2. Identify coherent material families.
3. Keep materially distinct pathways separate.
4. Detect categories already covered by seed pipelines: {json.dumps(SCM_SEED_CATEGORIES)}.
5. Recommend which repeatedly observed categories may deserve dedicated pipelines.
6. Avoid creating categories based on one unusual source.
7. Provide a concise rationale for every proposed grouping.

Allowed recommended_action values:
MERGE_WITH_SEED_CATEGORY, CREATE_DEDICATED_PIPELINE,
RETAIN_AS_BROAD_DISCOVERY_CATEGORY, INSUFFICIENT_EVIDENCE, MANUAL_REVIEW.

Return JSON:
{{
  "groupings": [
    {{
      "proposed_category": "...",
      "canonical_material_names": ["..."],
      "common_aliases": ["..."],
      "seed_category_overlap": "slag_cement or NA",
      "classification_coherence": "High|Medium|Low|NA",
      "recommended_action": "CREATE_DEDICATED_PIPELINE",
      "recommendation_reason": "concise rationale"
    }}
  ]
}}

AGGREGATED CANDIDATES:
{aggregated_candidates_json}

Return JSON only. Do not overwrite source-level records."""
