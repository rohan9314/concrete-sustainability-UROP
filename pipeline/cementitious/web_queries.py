"""Deterministic taxonomy-aware web query planning."""

from __future__ import annotations

from typing import Any

from pipeline.cementitious.decarbonization_taxonomy import (
    TAXONOMY_NA,
    DecarbNode,
    get_decarbonization_taxonomy,
)
from pipeline.cementitious.paths import is_taxonomy_na
from pipeline.cementitious.taxonomy import Taxonomy, TaxonomyNode, get_taxonomy
from pipeline.cementitious.taxonomy_migration import apply_decarbonization_path
from pipeline.cementitious.web_config import WebLimits
from pipeline.cementitious.web_scope import (
    WEB_SEARCH_SCOPE_CANONICAL,
    copy_taxonomy_fields,
    decarb_fields,
    parse_web_search_levels,
    resolve_web_search_scope,
    searchable_web_nodes,
)

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


def _enrich_runtime_query(query: dict[str, Any], taxonomy: Taxonomy) -> dict[str, Any]:
    """Attach five-level columns to a 9×58 runtime query via the migration map."""
    stub = {
        "subcategory_slug": query.get("subcategory_slug") or "",
        "sub_subcategory_slug": query.get("sub_subcategory_slug") or "",
        "category": query.get("category") or taxonomy.category_display,
        "subcategory": query.get("subcategory") or "",
        "sub_subcategory": query.get("sub_subcategory") or "",
    }
    filled = apply_decarbonization_path(stub, runtime=taxonomy)
    copy_taxonomy_fields(query, filled)
    query.setdefault(
        "taxonomy_path",
        "/".join(
            filled.get(f"taxonomy_level_{i}_slug") or ""
            for i in range(5)
            if filled.get(f"taxonomy_level_{i}") not in {"", None, TAXONOMY_NA, "N.A."}
        ),
    )
    query.setdefault(
        "web_search_node_slug",
        query.get("sub_subcategory_slug") or query.get("subcategory_slug") or "",
    )
    query.setdefault("web_search_node_role", "searchable_technology")
    query.setdefault(
        "taxonomy_search_level",
        3 if query.get("sub_subcategory_slug") else 2,
    )
    return query


def _l1_query_context(level_1: str) -> str:
    mapping = {
        "Cementitious Materials": "cement concrete decarbonization",
        "Aggregate Procurement": "concrete aggregate procurement",
        "Concrete Design": "concrete mix design",
        "Structural and Construction Design": "concrete structure construction",
        "Operation": "concrete building operation",
        "Policy": "cement concrete policy regulation",
        "End-of-Life": "concrete demolition recycling end of life",
    }
    return mapping.get(level_1, "cement concrete decarbonization")


def _contextual_query(node: DecarbNode, extra: str = "") -> str:
    """Never emit a bare short label (OPC, Hydrogen) as a query."""
    labels = list(node.path_labels)
    l1 = labels[1] if len(labels) > 1 else ""
    l2 = labels[2] if len(labels) > 2 else ""
    l3 = labels[3] if len(labels) > 3 else ""
    leaf = node.label
    context = _l1_query_context(l1)
    parts = [leaf]
    if l3 and l3.casefold() != leaf.casefold():
        parts.append(l3)
    if l2 and l2.casefold() not in {leaf.casefold(), l3.casefold()}:
        parts.append(l2)
    parts.append(context)
    if extra:
        parts.append(extra)
    return " ".join(p for p in parts if p)


def _templates_for_decarb_node(node: DecarbNode) -> list[tuple[str, str]]:
    name = node.label
    context = _l1_query_context(node.path_labels[1] if len(node.path_labels) > 1 else "")
    l1 = node.path_labels[1] if len(node.path_labels) > 1 else ""
    l2 = node.path_labels[2] if len(node.path_labels) > 2 else ""
    l3 = node.path_labels[3] if len(node.path_labels) > 3 else ""
    templates: list[tuple[str, str]] = [
        ("Technology Overview", _contextual_query(node)),
        (
            "Project or Deployment",
            _contextual_query(node, "pilot OR demonstration OR commercial project"),
        ),
        (
            "Company or Organization",
            _contextual_query(node, "company OR technology provider OR project location"),
        ),
        (
            "Performance",
            _contextual_query(node, "capacity OR capture rate OR performance data emissions"),
        ),
        (
            "Cost",
            _contextual_query(node, "cost CAPEX OPEX energy requirement"),
        ),
        (
            "Standards or Approval",
            _contextual_query(node, "standard OR EPD OR ASTM OR government report"),
        ),
        ("Commercialization", _contextual_query(node, "commercial deployment")),
    ]
    joined = " ".join(node.path_labels).casefold()
    if "carbon capture" in joined or "capture" in name.casefold():
        templates[0] = ("Technology Overview", f"cement plant {name} carbon capture")
        templates.append(("Energy", f"cement {name} carbon capture energy penalty"))
        if "amine" in name.casefold() or "amine" in joined:
            templates.extend(
                [
                    ("Project or Deployment", "cement plant amine CO2 capture"),
                    ("Project or Deployment", "cement solvent carbon capture project"),
                    ("Technology Overview", "cement post-combustion amine capture"),
                    ("Project or Deployment", "cement plant chemical absorption demonstration"),
                    ("Project or Deployment", "amine carbon capture cement pilot"),
                ]
            )
    leaf_cf = name.casefold()
    if leaf_cf == "opc" or "ordinary portland" in joined:
        templates.extend(
            [
                ("Technology Overview", "ordinary portland cement decarbonization"),
                ("Technology Overview", "OPC embodied carbon cement"),
                ("Standards or Approval", "ASTM C150 portland cement carbon emissions"),
            ]
        )
    if "hydrogen" in leaf_cf or "hydrogen" in joined:
        templates.extend(
            [
                ("Technology Overview", "hydrogen cement kiln"),
                ("Technology Overview", "hydrogen clinker production"),
                ("Project or Deployment", "cement plant hydrogen heating"),
            ]
        )
    if l2:
        templates.append(("Technology Overview", f"{name} {l2} {context}"))
    if l3 and l3.casefold() != leaf_cf:
        templates.append(("Technology Overview", f"{name} {l3} {l1}"))
    for alias in list(node.aliases)[:6]:
        alias = str(alias).strip()
        if not alias:
            continue
        templates.append(("Technology Overview", f"{alias} {l3} {context}".strip()))
        templates.append(
            ("Project or Deployment", f"{alias} pilot OR demonstration OR commercial {context}")
        )
    return templates


def _cap_queries_preserving_coverage(
    grouped: list[list[dict[str, Any]]],
    max_total: int,
) -> list[dict[str, Any]]:
    """Keep at least one query per searchable node; cap only extra variants."""
    floor: list[dict[str, Any]] = []
    extra_buckets: list[list[dict[str, Any]]] = []
    for group in grouped:
        if not group:
            continue
        floor.append(group[0])
        extra_buckets.append(list(group[1:]))
    if max_total <= 0:
        extras = [q for bucket in extra_buckets for q in bucket]
        return floor + extras
    remaining = max(0, max_total - len(floor))
    extras: list[dict[str, Any]] = []
    idx = 0
    while len(extras) < remaining and any(extra_buckets):
        bucket = extra_buckets[idx % len(extra_buckets)]
        if bucket:
            extras.append(bucket.pop(0))
        idx += 1
        if idx > 1_000_000:
            break
    return floor + extras


def _cap_queries_round_robin(
    grouped: list[list[dict[str, Any]]],
    max_total: int,
) -> list[dict[str, Any]]:
    """Compatibility wrapper: never drops a node that has a query."""
    return _cap_queries_preserving_coverage(grouped, max_total)


def plan_canonical_web_queries(
    limits: WebLimits,
    *,
    decarb=None,
    runtime: Taxonomy | None = None,
    include_parent_l3: bool = False,
    levels: tuple[int, ...] | None = None,
) -> list[dict[str, Any]]:
    """Plan Tavily queries for every searchable canonical taxonomy node."""
    tax = decarb or get_decarbonization_taxonomy()
    runtime = runtime or get_taxonomy()
    nodes = searchable_web_nodes(
        tax,
        include_parent_l3=include_parent_l3,
        levels=levels or parse_web_search_levels(),
    )
    per_node = max(1, int(limits.queries_per_node or 1))
    grouped: list[list[dict[str, Any]]] = []
    seen_text: set[str] = set()
    qid = 0
    for node in nodes:
        fields = decarb_fields(node, runtime=runtime)
        templates = _templates_for_decarb_node(node)
        positives = [node.label, *list(node.aliases)[:6]]
        node_queries: list[dict[str, Any]] = []
        for query_type, text in templates:
            if len(node_queries) >= per_node:
                break
            key = text.casefold().strip()
            if not key:
                continue
            if key in seen_text:
                text = f"{text} {node.path_labels[-1] if node.path_labels else node.slug}"
                key = text.casefold().strip()
                if key in seen_text:
                    text = f"{text} {node.path}"
                    key = text.casefold().strip()
                    if key in seen_text:
                        continue
            seen_text.add(key)
            qid += 1
            row = {
                "query_id": f"wq_{qid:05d}",
                "category": fields.get("category") or fields.get("taxonomy_level_1") or "",
                "subcategory": fields.get("subcategory") or fields.get("taxonomy_level_2") or "",
                "subcategory_slug": fields.get("subcategory_slug")
                or fields.get("taxonomy_level_2_slug")
                or "",
                "sub_subcategory": fields.get("sub_subcategory") or node.label,
                "sub_subcategory_slug": fields.get("sub_subcategory_slug") or node.slug,
                "technology_variant": node.label if node.level == 4 else "",
                "query_text": text,
                "query_type": query_type if query_type in QUERY_TYPES else "Other",
                "purpose": f"Discover web evidence for {node.label}",
                "positive_terms": positives,
                "negative_terms": list(DEFAULT_NEGATIVES),
                "expected_source_types": list(EXPECTED_SOURCE_TYPES),
                "maximum_results": limits.results_per_query,
                "shard_id": None,
                "query_scope": "canonical_technology",
                "aliases_used": list(node.aliases),
            }
            row.update(fields)
            node_queries.append(row)
        if not node_queries:
            text = _contextual_query(node, node.path)
            qid += 1
            row = {
                "query_id": f"wq_{qid:05d}",
                "category": fields.get("category") or fields.get("taxonomy_level_1") or "",
                "subcategory": fields.get("subcategory") or fields.get("taxonomy_level_2") or "",
                "subcategory_slug": fields.get("subcategory_slug") or "",
                "sub_subcategory": node.label,
                "sub_subcategory_slug": fields.get("sub_subcategory_slug") or node.slug,
                "technology_variant": node.label if node.level == 4 else "",
                "query_text": text,
                "query_type": "Technology Overview",
                "purpose": f"Discover web evidence for {node.label}",
                "positive_terms": positives,
                "negative_terms": list(DEFAULT_NEGATIVES),
                "expected_source_types": list(EXPECTED_SOURCE_TYPES),
                "maximum_results": limits.results_per_query,
                "shard_id": None,
                "query_scope": "canonical_technology",
                "aliases_used": list(node.aliases),
            }
            row.update(fields)
            node_queries.append(row)
        grouped.append(node_queries)
    queries = _cap_queries_preserving_coverage(grouped, limits.max_total_queries)
    for i, query in enumerate(queries, start=1):
        query["query_id"] = f"wq_{i:05d}"
    return queries


def plan_web_queries(
    taxonomy: Taxonomy,
    limits: WebLimits,
    *,
    selected_subcategories: list[str] | None = None,
    selected_sub_subcategories: list[str] | None = None,
    web_search_scope: str | None = None,
) -> list[dict[str, Any]]:
    """
    Deterministic query generation for the selected taxonomy scope only.

    Full / unrestricted runs use the canonical five-level searchable-node set.
    Explicit SELECTED_* (pilot smoke) keeps the legacy 9×58 planner.
    """
    scope = web_search_scope or resolve_web_search_scope(
        selected_subcategories=selected_subcategories,
        selected_sub_subcategories=selected_sub_subcategories,
    )
    if scope == WEB_SEARCH_SCOPE_CANONICAL:
        return plan_canonical_web_queries(limits, runtime=taxonomy)

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
        row = {
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
        _enrich_runtime_query(row, taxonomy)
        queries.append(row)
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
