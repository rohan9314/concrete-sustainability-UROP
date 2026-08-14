"""Canonical Concrete Decarbonization literature screening and heuristic classification.

The five-level taxonomy drives candidate selection. The legacy 9×58 cementitious
tree is used only for smoke-scope runs, migration, and compatibility slug backfill.

Record model: one canonical taxonomy path per extracted record. A paper that
legitimately spans multiple Level-1 branches yields multiple records that share
``source_id`` and list each other in ``related_record_ids``.
"""

from __future__ import annotations

import os
from typing import Any

from pipeline.cementitious.decarbonization_taxonomy import (
    TAXONOMY_NA,
    DecarbNode,
    DecarbonizationTaxonomy,
    get_decarbonization_taxonomy,
)
from pipeline.cementitious.paths import is_taxonomy_na
from pipeline.record_utils import record_dedupe_key
from pipeline.year_utils import normalize_publication_year

LEVEL_1_LABELS = (
    "Cementitious Materials",
    "Aggregate Procurement",
    "Concrete Design",
    "Structural and Construction Design",
    "Operation",
    "Policy",
    "End-of-Life",
)

# Extra retrieval/classification cues beyond node labels and aliases.
LEVEL_1_CUES: dict[str, tuple[str, ...]] = {
    "Cementitious Materials": (
        "cement",
        "clinker",
        "scm",
        "pozzolan",
        "cementitious",
        "geopolymer",
        "alkali-activated",
        "carbon capture",
        "kiln",
        "lc3",
        "amine absorption",
        "portland cement",
    ),
    "Aggregate Procurement": (
        "recycled concrete aggregate",
        "carbonated rca",
        "treated rca",
        "rca",
        "natural aggregate",
        "crushed concrete aggregate",
        "aggregate procurement",
    ),
    "Concrete Design": (
        "self-healing concrete",
        "bacterial self-healing",
        "mix design",
        "design for durability",
        "concrete mix",
    ),
    "Structural and Construction Design": (
        "topology optimization",
        "topology-optimized floors",
        "topology optimised",
        "efficient concrete use",
        "structural optimization",
    ),
    "Operation": (
        "overdesign",
        "mix overdesign",
        "reduced strength overdesign",
        "optimal overdesign",
        "strength overdesign",
    ),
    "Policy": (
        "buy clean",
        "green public procurement",
        "embodied-carbon procurement",
        "embodied carbon procurement",
        "procurement limits",
    ),
    "End-of-Life": (
        "end-of-life carbonation",
        "crushing-enhanced carbonation",
        "enhanced concrete carbonation",
        "demolition carbonation",
        "eol carbonation",
    ),
}

CONCRETE_CONTEXT_TERMS = (
    "concrete",
    "cement",
    "clinker",
    "decarbon",
    "embodied carbon",
    "co2",
    "carbon capture",
    "scm",
    "aggregate",
    "construction",
)


def literature_uses_canonical_taxonomy(
    *,
    focus_sub_slugs: list[str] | None = None,
    focus_ss_slugs: list[str] | None = None,
    environ: dict[str, str] | None = None,
) -> bool:
    """Return True unless smoke/runtime scope is explicitly requested."""
    env = os.environ if environ is None else environ
    raw = str(env.get("LITERATURE_TAXONOMY") or "canonical").strip().lower()
    if raw in {"runtime", "legacy", "cementitious", "9x58"}:
        return False
    if focus_sub_slugs or focus_ss_slugs:
        return False
    return True


def _fold(value: Any) -> str:
    return str(value or "").casefold()


def _has_concrete_context(text: str) -> bool:
    return any(term in text for term in CONCRETE_CONTEXT_TERMS)


def compact_level1_block(tax: DecarbonizationTaxonomy | None = None) -> str:
    tax = tax or get_decarbonization_taxonomy()
    lines = [
        "Level 0: Concrete Decarbonization",
        "Level 1 categories (a paper may match more than one):",
    ]
    for node in tax.nodes_at(1):
        children = ", ".join(c.label for c in tax.children(node.path)[:12])
        extra = f" — Level-2 examples: {children}" if children else ""
        lines.append(f"- {node.label}{extra}")
    return "\n".join(lines)


def compact_branch_block(
    tax: DecarbonizationTaxonomy,
    level_1_labels: list[str],
) -> str:
    """Bounded prompt: L2→L3→L4 only for selected Level-1 branches."""
    lines: list[str] = []
    wanted = {label.casefold() for label in level_1_labels if label}
    for l1 in tax.nodes_at(1):
        if wanted and l1.label.casefold() not in wanted:
            continue
        lines.append(f"## {l1.label}")
        for l2 in tax.children(l1.path):
            lines.append(f"  ### {l2.label}")
            for l3 in tax.children(l2.path):
                l4 = tax.children(l3.path)
                if l4:
                    leaves = ", ".join(
                        f"{n.label}" + (f" (aka {', '.join(n.aliases[:3])})" if n.aliases else "")
                        for n in l4[:20]
                    )
                    lines.append(f"    - {l3.label}: {leaves}")
                else:
                    alias = f" (aka {', '.join(l3.aliases[:3])})" if l3.aliases else ""
                    lines.append(f"    - {l3.label}{alias}")
        lines.append("")
    return "\n".join(lines).strip()


def _node_terms(node: DecarbNode) -> list[str]:
    terms = [node.label, *node.aliases, *node.path_labels[1:]]
    extra = LEVEL_1_CUES.get(node.path_labels[1] if len(node.path_labels) > 1 else "", ())
    if node.level == 1:
        terms.extend(extra)
    return [t for t in (_fold(x) for x in terms) if t and len(t) >= 3]


def score_node(text: str, node: DecarbNode) -> int:
    score = 0
    label = _fold(node.label)
    if label and label in text:
        score += 5 if node.level >= 3 else 3
    for alias in node.aliases:
        a = _fold(alias)
        if a and len(a) >= 3 and a in text:
            score += 4
    if node.level == 1:
        for cue in LEVEL_1_CUES.get(node.label, ()):
            if cue in text:
                score += 2
    return score


def match_level1_labels(text: str, tax: DecarbonizationTaxonomy | None = None) -> list[str]:
    tax = tax or get_decarbonization_taxonomy()
    scored = [(score_node(text, n), n.label) for n in tax.nodes_at(1)]
    scored.sort(reverse=True)
    hits = [label for score, label in scored if score > 0]
    return hits


def keyword_screen_canonical(
    record: dict[str, Any],
    index: int,
    *,
    taxonomy: DecarbonizationTaxonomy | None = None,
) -> dict[str, Any]:
    """Relevance against the full Concrete Decarbonization tree (not 9×58)."""
    tax = taxonomy or get_decarbonization_taxonomy()
    paper_id = record_dedupe_key(record) or f"paper:{index}"
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    text = f"{title}\n{abstract}".casefold()
    year, _ = normalize_publication_year(record)

    l1_hits = match_level1_labels(text, tax)
    node_hit = False
    for node in tax.ordered_nodes():
        if node.level == 0:
            continue
        if score_node(text, node) > 0:
            node_hit = True
            if node.level == 1 and node.label not in l1_hits:
                l1_hits.append(node.label)
            if node.level > 1 and len(node.path_labels) > 1:
                parent_l1 = node.path_labels[1]
                if parent_l1 not in l1_hits:
                    l1_hits.append(parent_l1)
    relevant = bool((l1_hits or node_hit) and _has_concrete_context(text))
    if not relevant and l1_hits:
        # Policy / buy-clean papers may omit the word "concrete" if they say cement.
        relevant = True
    return {
        "paper_id": paper_id,
        "title": title,
        "year": year or "",
        "doi": str(record.get("doi") or ""),
        "is_relevant": relevant,
        "confidence": "Medium" if relevant else "Low",
        "reason": (
            "canonical taxonomy keyword screen; Level-1 hits: " + ", ".join(l1_hits)
            if l1_hits
            else "canonical taxonomy keyword screen; no Level-1 match"
        ),
        "negative_match": "",
        "screening_mode": "keyword",
        "suggested_level_1": l1_hits,
        "matched_taxonomy_branches": "; ".join(l1_hits),
        "literature_taxonomy": "canonical",
        "selected_subcategories": [],
        "selected_sub_subcategories": [],
    }


def heuristic_classify_canonical(
    record: dict[str, Any],
    *,
    taxonomy: DecarbonizationTaxonomy | None = None,
    max_paths: int = 3,
) -> list[dict[str, str]]:
    """Return zero or more canonical paths (deepest supported level; no invented L4)."""
    tax = taxonomy or get_decarbonization_taxonomy()
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    text = f"{title}\n{abstract}".casefold()
    ranked: list[tuple[int, DecarbNode]] = []
    for node in tax.ordered_nodes():
        if node.level < 1:
            continue
        score = score_node(text, node)
        if score > 0:
            ranked.append((score, node))
    ranked.sort(key=lambda item: (item[0], item[1].level), reverse=True)
    if not ranked:
        return []

    chosen: list[DecarbNode] = []
    used_l1: set[str] = set()
    best = ranked[0][0]
    for score, node in ranked:
        if score < max(2, best - 2) and chosen:
            break
        l1 = node.path_labels[1] if len(node.path_labels) > 1 else node.label
        # Prefer the deepest node per Level-1 unless a second L1 is also strong.
        if any(c.path.startswith(node.path) or node.path.startswith(c.path) for c in chosen):
            continue
        if l1 in used_l1 and node.level < 3:
            continue
        chosen.append(node)
        used_l1.add(l1)
        if len(chosen) >= max_paths:
            break

    paths: list[dict[str, str]] = []
    for node in chosen:
        labels = list(node.path_labels)
        while len(labels) < 5:
            labels.append(TAXONOMY_NA)
        # Do not invent L4 if the match stopped at L3.
        if node.level < 4:
            labels[4] = TAXONOMY_NA
        paths.append(
            {
                "taxonomy_level_0": labels[0],
                "taxonomy_level_1": labels[1],
                "taxonomy_level_2": labels[2] if not is_taxonomy_na(labels[2]) else TAXONOMY_NA,
                "taxonomy_level_3": labels[3] if not is_taxonomy_na(labels[3]) else TAXONOMY_NA,
                "taxonomy_level_4": labels[4] if not is_taxonomy_na(labels[4]) else TAXONOMY_NA,
                "classification_basis": "Strongly Inferred" if node.level >= 3 else "Weakly Inferred",
                "taxonomy_confidence": "Medium" if node.level >= 3 else "Low",
            }
        )
    return paths


def parse_classification_paths(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize LLM JSON into one or more canonical paths."""
    raw_paths = payload.get("taxonomy_paths")
    paths: list[dict[str, Any]] = []
    if isinstance(raw_paths, list) and raw_paths:
        paths = [p for p in raw_paths if isinstance(p, dict)]
    else:
        paths = [payload]

    out: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for item in paths:
        labels = []
        for i in range(5):
            value = (
                item.get(f"taxonomy_level_{i}")
                or item.get(f"level_{i}")
                or (["Concrete Decarbonization"][i] if i == 0 else "")
            )
            if i == 0 and not value:
                value = "Concrete Decarbonization"
            labels.append(str(value or TAXONOMY_NA).strip() or TAXONOMY_NA)
        if is_taxonomy_na(labels[1]):
            continue
        key = tuple(labels)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "taxonomy_level_0": labels[0],
                "taxonomy_level_1": labels[1],
                "taxonomy_level_2": labels[2],
                "taxonomy_level_3": labels[3],
                "taxonomy_level_4": labels[4],
                "classification_basis": str(
                    item.get("classification_basis") or payload.get("classification_basis") or "Strongly Inferred"
                ),
                "taxonomy_confidence": str(
                    item.get("taxonomy_confidence") or payload.get("taxonomy_confidence") or "Medium"
                ),
                "classification_reasoning": str(
                    item.get("classification_reasoning") or payload.get("classification_reasoning") or ""
                ),
            }
        )
    return out
