"""Deterministic taxonomy-aware web query planning."""

from __future__ import annotations

from typing import Any

from pipeline.cementitious.taxonomy import Taxonomy, TaxonomyNode
from pipeline.cementitious.web_config import WebLimits

QUERY_TYPES = (
    "Technology Overview",
    "Company or Organization",
    "Project or Deployment",
    "Performance",
    "Carbon Reduction",
    "Energy",
    "Cost",
    "Commercialization",
    "Standards or Approval",
    "Production Process",
    "Feedstock or Supply",
    "Environmental Risk",
    "Durability",
    "Other",
)

DEFAULT_NEGATIVES = (
    "aggregate only",
    "soil amendment",
    "road base",
    "unrelated industry",
)

BIOMASS_ASH_NEGATIVES = (
    "biomass kiln fuel",
    "biomass as fuel",
    "refuse derived fuel",
    "alternative fuel cement kiln",
)

KILN_FUEL_NEGATIVES = (
    "biomass ash SCM",
    "rice husk ash cement replacement",
    "pozzolanic biomass ash",
)

EXPECTED_SOURCE_TYPES = [
    "Company Website",
    "Government Website",
    "Technical Report",
    "Industry Association",
    "News",
    "Conference or Project Website",
]


def _templates_for_node(node: TaxonomyNode, *, parent: TaxonomyNode | None) -> list[tuple[str, str]]:
    """Return (query_type, template) pairs for a sub-subcategory node."""
    name = node.display_name
    domain = node.expected_technology_domain
    templates: list[tuple[str, str]] = [
        ("Technology Overview", f"{name} cement concrete"),
        ("Project or Deployment", f"{name} cement plant pilot project OR demonstration"),
        ("Commercialization", f"{name} commercial deployment cement"),
    ]
    if "Carbon Capture" in domain or (parent and "carbon_capture" in parent.slug):
        templates = [
            ("Technology Overview", f"cement plant {name} carbon capture"),
            ("Project or Deployment", f"cement kiln {name} CO2 capture project deployment"),
            ("Energy", f"cement {name} carbon capture energy penalty"),
            ("Cost", f"cement {name} carbon capture cost CAPEX OPEX"),
            (
                "Company or Organization",
                f"cement {name} solvent OR membrane OR looping capture company project",
            ),
        ]
    elif "Manufacturing" in domain or (parent and "manufacturing" in parent.slug):
        templates = [
            ("Technology Overview", f"cement plant {name}"),
            ("Production Process", f"cement kiln {name} efficiency"),
            ("Energy", f"cement {name} energy consumption"),
            ("Project or Deployment", f"cement plant {name} retrofit project"),
        ]
    elif "Feedstock" in domain or (parent and "feedstock" in parent.slug):
        templates = [
            ("Feedstock or Supply", f"{name} clinker raw meal cement"),
            ("Technology Overview", f"{name} alternative limestone cement kiln"),
            ("Project or Deployment", f"{name} cement plant feedstock demonstration"),
        ]
    elif "Filler" in domain or (parent and "filler" in parent.slug):
        templates = [
            ("Technology Overview", f"{name} cement filler concrete"),
            ("Performance", f"{name} concrete particle packing workability"),
            ("Commercialization", f"{name} cementitious filler commercial"),
        ]
    elif "Binder" in domain or (parent and "alternative_cement" in (parent.slug if parent else "")):
        templates = [
            ("Technology Overview", f"{name} alternative cement binder"),
            ("Performance", f"{name} compressive strength concrete"),
            ("Commercialization", f"{name} commercial cement plant"),
            ("Carbon Reduction", f"{name} CO2 reduction cement"),
        ]
    elif "Supplementary" in domain or (
        parent and "supplementary" in (parent.slug if parent else "")
    ):
        templates = [
            (
                "Technology Overview",
                f"{name} supplementary cementitious material cement replacement",
            ),
            ("Performance", f"{name} cement replacement compressive strength"),
            ("Carbon Reduction", f"{name} clinker substitution CO2 reduction"),
            ("Commercialization", f"{name} SCM commercial concrete"),
            ("Durability", f"{name} concrete durability SCM"),
        ]
    elif parent and "blend" in parent.slug:
        templates = [
            ("Technology Overview", f"{name} cementitious blend concrete"),
            ("Performance", f"{name} ternary OR binary cement blend strength"),
            ("Carbon Reduction", f"{name} high SCM binder CO2"),
        ]

    for variant in node.representative_technology_variants[:2]:
        templates.append(("Technology Overview", f"{variant} cement concrete OR carbon capture"))
    return templates


def _templates_for_subcategory(parent: TaxonomyNode) -> list[tuple[str, str]]:
    """Subcategory-level overview queries (not tied to one child)."""
    name = parent.display_name
    templates = [
        ("Technology Overview", f"{name} cement industry technologies"),
        ("Commercialization", f"{name} commercial projects cement plant"),
        ("Company or Organization", f"{name} companies cement deployment"),
    ]
    if "carbon_capture" in parent.slug:
        templates = [
            ("Technology Overview", f"cement plant carbon capture {name}"),
            ("Project or Deployment", f"cement kiln CO2 capture projects {name}"),
            ("Commercialization", f"cement carbon capture commercial deployment"),
        ]
    elif "supplementary" in parent.slug:
        templates = [
            ("Technology Overview", f"{name} SCM cement replacement"),
            ("Performance", f"{name} concrete compressive strength"),
            ("Commercialization", f"{name} commercial concrete binders"),
        ]
    for syn in parent.representative_synonyms[:2]:
        templates.append(("Technology Overview", f"{syn} cement concrete"))
    return templates


def _negatives_for(node: TaxonomyNode, parent: TaxonomyNode | None) -> list[str]:
    negatives = list(DEFAULT_NEGATIVES)
    negatives.extend(node.negative_screening_cues[:6])
    if node.slug == "biomass_ashes" or (
        parent
        and parent.slug == "emerging_supplementary_cementitious_materials"
        and "biomass" in node.slug
    ):
        negatives.extend(BIOMASS_ASH_NEGATIVES)
    if node.slug == "kiln_fuel_substitution":
        negatives.extend(KILN_FUEL_NEGATIVES)
    seen: set[str] = set()
    out: list[str] = []
    for term in negatives:
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


def _selected_scope(
    taxonomy: Taxonomy,
    *,
    selected_subcategories: list[str] | None,
    selected_sub_subcategories: list[str] | None,
) -> tuple[list[TaxonomyNode], list[tuple[TaxonomyNode, TaxonomyNode]]]:
    """
    Return (subcategories_for_overview, child_pairs).

    - sub-subcategory selection: only those children; no parent overview queries
    - subcategory selection: parent overviews + all children of those parents
    - neither: all parents + all children
    """
    if selected_sub_subcategories:
        pairs: list[tuple[TaxonomyNode, TaxonomyNode]] = []
        for raw in selected_sub_subcategories:
            slug = taxonomy.resolve_slug(raw, level="sub_subcategory")
            child = taxonomy.sub_subcategories[slug]
            parent = taxonomy.subcategories[taxonomy.parent_of_sub_sub[slug]]
            pairs.append((parent, child))
        return [], pairs

    parents: list[TaxonomyNode] = []
    pairs = []
    if selected_subcategories:
        for raw in selected_subcategories:
            slug = taxonomy.resolve_slug(raw, level="subcategory")
            parent = taxonomy.subcategories[slug]
            parents.append(parent)
            for child in taxonomy.children_of(slug):
                pairs.append((parent, child))
        return parents, pairs

    for parent in taxonomy.subcategories.values():
        parents.append(parent)
        for child in taxonomy.children_of(parent.slug):
            pairs.append((parent, child))
    return parents, pairs


def plan_web_queries(
    taxonomy: Taxonomy,
    limits: WebLimits,
    *,
    selected_subcategories: list[str] | None = None,
    selected_sub_subcategories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Deterministic query generation for the selected taxonomy scope only.

    Emits:
    - up to WEB_QUERIES_PER_SUBCATEGORY overview queries per selected subcategory
      (skipped when only sub-subcategories are selected);
    - up to WEB_QUERIES_PER_SUB_SUBCATEGORY queries per selected sub-subcategory.
    """
    parents, pairs = _selected_scope(
        taxonomy,
        selected_subcategories=selected_subcategories,
        selected_sub_subcategories=selected_sub_subcategories,
    )
    queries: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    qid = 0

    def _append(
        *,
        parent: TaxonomyNode,
        child: TaxonomyNode | None,
        query_type: str,
        text: str,
        purpose: str,
        positive: list[str],
        negative: list[str],
        variant: str = "",
    ) -> bool:
        nonlocal qid
        key = text.casefold().strip()
        if not key or key in seen_text:
            return False
        seen_text.add(key)
        qid += 1
        queries.append(
            {
                "query_id": f"wq_{qid:05d}",
                "category": taxonomy.category_display,
                "subcategory": parent.display_name,
                "subcategory_slug": parent.slug,
                "sub_subcategory": child.display_name if child else "",
                "sub_subcategory_slug": child.slug if child else "",
                "technology_variant": variant,
                "query_text": text,
                "query_type": query_type if query_type in QUERY_TYPES else "Other",
                "purpose": purpose,
                "positive_terms": positive,
                "negative_terms": negative,
                "expected_source_types": list(EXPECTED_SOURCE_TYPES),
                "maximum_results": limits.results_per_query,
                "shard_id": None,
                "query_scope": "sub_subcategory" if child else "subcategory",
            }
        )
        return True

    # 1) Subcategory-level overview queries
    for parent in parents:
        added = 0
        for query_type, text in _templates_for_subcategory(parent):
            if added >= limits.queries_per_subcategory:
                break
            ok = _append(
                parent=parent,
                child=None,
                query_type=query_type,
                text=text,
                purpose=f"Discover web evidence for subcategory {parent.display_name}",
                positive=list(parent.positive_screening_cues[:8])
                or list(parent.representative_synonyms[:8]),
                negative=list(DEFAULT_NEGATIVES) + list(parent.negative_screening_cues[:6]),
            )
            if ok:
                added += 1

    # 2) Sub-subcategory queries
    per_ss_count: dict[str, int] = {}
    for parent, child in pairs:
        templates = _templates_for_node(child, parent=parent)
        for synonym in child.representative_synonyms[:2]:
            templates.append(("Technology Overview", f"{synonym} cement concrete"))
        for query_type, text in templates:
            if per_ss_count.get(child.slug, 0) >= limits.queries_per_sub_subcategory:
                break
            ok = _append(
                parent=parent,
                child=child,
                query_type=query_type,
                text=text,
                purpose=f"Discover web evidence for {child.display_name}",
                positive=list(child.positive_screening_cues[:8])
                or list(child.representative_synonyms[:8]),
                negative=_negatives_for(child, parent),
                variant=(
                    child.representative_technology_variants[0]
                    if child.representative_technology_variants
                    else ""
                ),
            )
            if ok:
                per_ss_count[child.slug] = per_ss_count.get(child.slug, 0) + 1

    return queries
