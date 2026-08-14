"""LLM prompts for Cementitious Materials screening, classification, and extraction."""

from __future__ import annotations

import json
from typing import Any

from pipeline.cementitious.taxonomy import Taxonomy


ROLE_SENSITIVE_EXAMPLES = """
Role-sensitive classification examples (role and intervention determine the branch):
- Rice husk ash used as a cement replacement → Emerging SCMs / Biomass Ashes.
- Rice husk ash used to manufacture pelletized aggregate → NOT Cementitious Materials.
- Steel slag used as an alkali-activated precursor (complete binder) → Alternative Cement Chemistries / Alkali-Activated Cements.
- Carbonated steel slag used directly as an SCM → Emerging SCMs / Carbonated Waste-Derived SCMs.
- Biomass used as kiln fuel → Cement Manufacturing Efficiency / Kiln Fuel Substitution.
- Biomass ash used as an SCM → Emerging SCMs / Biomass Ashes.
- Factory-produced LC3 → Conventional and Blended Cements / Limestone Calcined Clay Cement.
- Calcined clay added directly as an SCM → Conventional SCMs / Calcined Clays.
- Recovered cement paste reclinkered as feedstock → Clinker Feedstock Decarbonization.
- Recovered cement paste used directly as SCM → Emerging SCMs / Recycled Cementitious Materials.
- Vaterite framed as reactive SCM → Emerging SCMs / Synthetic Calcium Carbonates.
- Vaterite framed as inert filler → Inert and Low-Reactivity Fillers / Carbonate Fillers.
""".strip()


def taxonomy_compact(
    taxonomy: Taxonomy,
    *,
    selected_sub_slugs: list[str] | None = None,
    selected_ss_slugs: list[str] | None = None,
) -> str:
    """
    Render the permitted taxonomy block, optionally scoped to a subset.

    When ``selected_ss_slugs`` is set, only those sub-subcategories (and their
    parent subcategories) are included, regardless of ``selected_sub_slugs``.
    This keeps scoped runs (e.g. a single sub-subcategory re-screen) from
    leaking unrelated branches into the permitted taxonomy shown to the model.
    """
    ss_scope = set(selected_ss_slugs) if selected_ss_slugs else None
    sub_scope = set(selected_sub_slugs) if selected_sub_slugs else None
    if ss_scope:
        parent_scope = {
            taxonomy.parent_of_sub_sub[slug]
            for slug in ss_scope
            if slug in taxonomy.parent_of_sub_sub
        }
        sub_scope = (sub_scope | parent_scope) if sub_scope else parent_scope

    lines: list[str] = [
        f"Category: {taxonomy.category_display}",
        f"Taxonomy version: {taxonomy.taxonomy_version}",
        "",
    ]
    for slug, node in taxonomy.subcategories.items():
        if sub_scope and slug not in sub_scope:
            continue
        lines.append(f"## {node.display_name} [{slug}]")
        lines.append(f"Definition: {node.definition}")
        lines.append(f"Include: {'; '.join(node.inclusion_criteria)}")
        lines.append(f"Exclude: {'; '.join(node.exclusion_criteria)}")
        children = taxonomy.children_of(slug)
        if ss_scope:
            children = [child for child in children if child.slug in ss_scope]
        for child in children:
            lines.append(f"  - {child.display_name} [{child.slug}]")
            lines.append(f"    Definition: {child.definition}")
            if child.representative_technology_variants:
                lines.append(
                    "    Variants: "
                    + "; ".join(child.representative_technology_variants[:8])
                )
            if child.negative_screening_cues:
                lines.append(
                    "    Negative cues: " + "; ".join(child.negative_screening_cues[:6])
                )
        lines.append("")
    return "\n".join(lines)


CANONICAL_ROLE_EXAMPLES = """
Role-sensitive examples across the Concrete Decarbonization taxonomy:
- Amine solvent CO2 capture at a cement kiln → Cementitious Materials / Cement-Plant Carbon Capture / Chemical Absorption / Amine Absorption.
- Carbonated recycled concrete aggregate → Aggregate Procurement / Recycled Concrete Aggregates / Treated RCA / Carbonated RCA.
- Bacterial self-healing concrete mix design → Concrete Design / Design for Durability / Self-Healing Concrete / Bacterial Self-Healing Concrete.
- Topology-optimized concrete floors that reduce concrete volume → Structural and Construction Design / Efficient Concrete Use / Topology Optimization / Topology-Optimized Floors.
- Reducing mix strength overdesign in ready-mix operation → Operation / Optimal Overdesign / Mix Overdesign Reduction / Reduced Strength Overdesign.
- Buy Clean public procurement limits on embodied carbon → Policy / Green Public Procurement / Embodied-Carbon Procurement Limits / Buy Clean Programs.
- Crushing demolished concrete to enhance atmospheric carbonation → End-of-Life / End-of-Life Carbonation / Enhanced Concrete Carbonation / Crushing-Enhanced Carbonation.
- Rice husk ash used as a cement replacement → Cementitious Materials (SCM). Do not force a Level-4 leaf unless the source names one.
A paper may map to more than one Level-1 branch; return multiple taxonomy_paths rather than dropping a branch.
""".strip()


def screening_system_prompt(*, scoped: bool = False) -> str:
    base = (
        "You screen academic abstracts for relevance to Cementitious Materials "
        "decarbonization technologies. Decide relevance from the described intervention "
        "and technological function, not from material keywords alone. "
    )
    if scoped:
        base += (
            "This screening run is scoped to specific taxonomy branches; only mark a "
            "paper relevant if it matches one of the permitted branches given in the "
            "user prompt, even if it would otherwise fit elsewhere in Cementitious Materials. "
        )
    return base + "Return strict JSON only."


def screening_user_prompt(
    *,
    title: str,
    abstract: str,
    taxonomy: Taxonomy,
    selected_sub_slugs: list[str] | None = None,
    selected_ss_slugs: list[str] | None = None,
) -> str:
    scoped = bool(selected_sub_slugs or selected_ss_slugs)
    taxonomy_block = taxonomy_compact(
        taxonomy,
        selected_sub_slugs=selected_sub_slugs,
        selected_ss_slugs=selected_ss_slugs,
    )
    scope_note = (
        "This run is scoped to the branches below only; do not mark a paper "
        "relevant for any other Cementitious Materials branch."
        if scoped
        else "Screen against the full Cementitious Materials taxonomy below."
    )
    # Full role examples are useful for unscoped runs; scoped runs keep only the
    # permitted taxonomy block to avoid injecting unrelated branch vocabulary.
    examples = "" if scoped else ROLE_SENSITIVE_EXAMPLES + "\n\n"
    return f"""
Screen this paper for Cementitious Materials relevance.

{examples}{scope_note}

PERMITTED TAXONOMY:
{taxonomy_block}

Title: {title}

Abstract:
{abstract}

Return JSON:
{{
  "relevant": true/false,
  "relevance_confidence": "High"|"Medium"|"Low",
  "suggested_technology_domain": one of {json.dumps(taxonomy.controlled_vocabularies.get("technology_domain", []))},
  "suggested_functional_role": one of {json.dumps(taxonomy.controlled_vocabularies.get("functional_role", []))},
  "reason": "one concise evidence-based sentence",
  "negative_match": "if excluded, which exclusion applied, else empty string"
}}
""".strip()


def classification_system_prompt() -> str:
    return (
        "You classify cementitious-materials interventions into a fixed taxonomy. "
        "Classify from the technological function and intervention described by the source, "
        "not from material names alone. Do not invent new subcategories or sub-subcategories "
        "in production mode. Return strict JSON only."
    )


def classification_user_prompt(
    *,
    taxonomy: Taxonomy,
    title: str,
    text: str,
    selected_sub_slugs: list[str] | None = None,
    allow_proposals: bool = False,
) -> str:
    proposal_block = ""
    if allow_proposals:
        proposal_block = """
If no valid fit exists, set classification_basis to "Unresolved" and include:
"taxonomy_proposal": {
  "raw_term": "...",
  "proposed_canonical_name": "...",
  "proposed_level": "technology_variant"|"sub_subcategory"|"subcategory",
  "proposed_parent": "...",
  "definition": "...",
  "reason_existing_taxonomy_is_insufficient": "...",
  "suggested_synonyms": ["..."],
  "confidence": "High"|"Medium"|"Low"
}
New subcategory/sub_subcategory proposals require explicit justification.
Technology variants and synonyms may be proposed freely.
""".strip()
    else:
        proposal_block = (
            'If unresolved, set classification_basis to "Unresolved" and leave '
            "subcategory fields empty. Do not invent taxonomy nodes."
        )

    return f"""
Classify the intervention described below.

{ROLE_SENSITIVE_EXAMPLES}

PERMITTED TAXONOMY:
{taxonomy_compact(taxonomy, selected_sub_slugs=selected_sub_slugs)}

Source title: {title}

Evidence text:
{text[:12000]}

Determine:
1. Is this relevant to Cementitious Materials?
2. technology_domain
3. functional_role
4. subcategory (display name + slug)
5. sub_subcategory (display name + slug)
6. technology_variant (prefer representative variants; may propose a new variant string)
7. exact paper terminology (raw_technology_name)
8. classification_basis: Explicit | Strongly Inferred | Weakly Inferred | Unresolved
9. concise classification_reasoning quoting evidence (no hidden chain-of-thought)
10. alternative_classification if another branch is plausible

{proposal_block}

Return JSON:
{{
  "relevant": true/false,
  "technology_domain": "...",
  "functional_role": "...",
  "subcategory": "...",
  "subcategory_slug": "...",
  "sub_subcategory": "...",
  "sub_subcategory_slug": "...",
  "technology_variant": "...",
  "raw_technology_name": "...",
  "canonical_technology_name": "...",
  "taxonomy_confidence": "High"|"Medium"|"Low",
  "classification_basis": "Explicit"|"Strongly Inferred"|"Weakly Inferred"|"Unresolved",
  "classification_reasoning": "...",
  "alternative_classification": "...",
  "evidence_span": "..."
}}
""".strip()


def extraction_system_prompt() -> str:
    return (
        "You extract structured evidence for one Cementitious Materials technology "
        "observation. Do not fabricate numerical values or citations. "
        "Use empty strings for missing values. Never use N/A, unknown, or not found. "
        "Return strict JSON only."
    )


def extraction_user_prompt(
    *,
    classification: dict[str, Any],
    title: str,
    text: str,
    source_meta: dict[str, Any],
) -> str:
    return f"""
Extract one evidence-grounded Cementitious Materials record.

Classification (already determined):
{json.dumps(classification, indent=2)}

Source metadata:
{json.dumps(source_meta, indent=2)}

Title: {title}

Source text:
{text[:14000]}

Rules:
- One record = one distinct technology/material/project/experimental condition when outcomes differ meaningfully.
- Preserve tested replacement ranges and optimum when stated.
- For alkali-activated systems, put activator chemistry in activator_type (not only in taxonomy).
- For coal ash, fill collection_form, recovery_status, ASTM_class via processing_status/notes as available.
- For blends, include binder_components as a JSON list of objects with component_name, canonical_component_name, fraction_percent.
- evidence_text must quote or closely paraphrase supporting evidence.
- extraction_confidence: High|Medium|Low

Return JSON object with any of these keys when available:
record fields matching the cementitious schema, plus binder_components (list).
Always include: evidence_text, extraction_confidence, source_title.
""".strip()


def taxonomy_proposal_system_prompt() -> str:
    return (
        "You propose missing taxonomy variants or, only when justified, new "
        "sub-subcategories/subcategories. Do not auto-approve changes. Return JSON only."
    )


def qc_system_prompt() -> str:
    return (
        "You quality-check Cementitious Materials classifications for role errors "
        "(aggregate vs SCM, kiln fuel vs biomass ash, filler vs reactive SCM, "
        "complete binder vs SCM). Propose corrections but do not invent values. "
        "Return JSON only."
    )


def canonical_screening_system_prompt() -> str:
    return (
        "You screen academic abstracts for relevance to Concrete Decarbonization: "
        "cement and concrete climate-mitigation technologies, materials, design, "
        "construction, operation, policy, and end-of-life. Decide from the described "
        "intervention, not from isolated keywords. A paper is relevant if it concerns "
        "ANY of the seven Level-1 categories, not only cementitious materials. "
        "Prefer high recall. Return strict JSON only."
    )


def canonical_screening_user_prompt(*, title: str, abstract: str) -> str:
    from pipeline.cementitious.decarb_literature import compact_level1_block

    return f"""
Screen this paper for Concrete Decarbonization relevance.

{CANONICAL_ROLE_EXAMPLES}

{compact_level1_block()}

Title: {title}

Abstract:
{abstract}

Return JSON:
{{
  "relevant": true/false,
  "relevance_confidence": "High"|"Medium"|"Low",
  "suggested_level_1": ["one or more Level-1 labels from the list above"],
  "reason": "one concise evidence-based sentence",
  "negative_match": "if excluded, which exclusion applied, else empty string"
}}
""".strip()


def canonical_classification_system_prompt() -> str:
    return (
        "You classify concrete-decarbonization interventions into a fixed five-level "
        "taxonomy. Classify from the technological function described by the source. "
        "Do not invent taxonomy nodes. Assign Level 4 only when the source supports "
        "that specificity; otherwise use N.A. for unsupported deeper levels. "
        "A paper may receive multiple taxonomy_paths when it legitimately spans "
        "Level-1 branches. Return strict JSON only."
    )


def canonical_classification_user_prompt(
    *,
    title: str,
    text: str,
    level_1_labels: list[str] | None = None,
) -> str:
    from pipeline.cementitious.decarb_literature import compact_branch_block, compact_level1_block
    from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy

    tax = get_decarbonization_taxonomy()
    branch = compact_branch_block(tax, list(level_1_labels or []))
    if not branch:
        branch = compact_level1_block(tax)
    return f"""
Classify the intervention described below into the Concrete Decarbonization taxonomy.

{CANONICAL_ROLE_EXAMPLES}

PERMITTED TAXONOMY (bounded to selected Level-1 branches when provided):
{branch}

Source title: {title}

Evidence text:
{text[:12000]}

Rules:
- taxonomy_level_0 is always "Concrete Decarbonization".
- Choose one or more Level-1 labels from the permitted tree.
- Within each selected branch, assign the deepest Level 2/3/4 supported by evidence.
- If evidence supports a Level-3 node but not a specific Level-4 technology, set taxonomy_level_4 to "N.A.".
- Do not fabricate a Level-4 leaf.
- If two Level-1 branches both apply, return both in taxonomy_paths.

Return JSON:
{{
  "relevant": true/false,
  "taxonomy_paths": [
    {{
      "taxonomy_level_0": "Concrete Decarbonization",
      "taxonomy_level_1": "...",
      "taxonomy_level_2": "..."|"N.A.",
      "taxonomy_level_3": "..."|"N.A.",
      "taxonomy_level_4": "..."|"N.A.",
      "classification_basis": "Explicit"|"Strongly Inferred"|"Weakly Inferred"|"Unresolved",
      "taxonomy_confidence": "High"|"Medium"|"Low",
      "classification_reasoning": "quote or paraphrase supporting evidence"
    }}
  ],
  "technology_variant": "...",
  "raw_technology_name": "...",
  "canonical_technology_name": "...",
  "alternative_classification": "...",
  "evidence_span": "..."
}}
""".strip()


def qc_user_prompt(*, record: dict[str, Any]) -> str:
    return f"""
Review this record for taxonomy/role errors.

Record:
{json.dumps(record, indent=2)[:12000]}

Return JSON:
{{
  "original_classification": {{
    "subcategory": "...",
    "sub_subcategory": "...",
    "technology_variant": "...",
    "functional_role": "..."
  }},
  "proposed_corrected_classification": {{
    "subcategory": "...",
    "sub_subcategory": "...",
    "technology_variant": "...",
    "functional_role": "..."
  }},
  "correction_reason": "...",
  "confidence": "High"|"Medium"|"Low",
  "requires_human_review": true/false,
  "issue_flags": ["..."]
}}
""".strip()
