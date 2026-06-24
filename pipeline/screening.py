"""
Stage 1 screening helpers: title + abstract only.

Two-stage pipeline design:
  Stage 1 — Abstract screening for cement/concrete CCS relevance and subpath tags.
  Stage 2 — Detailed extraction on selected relevant papers (may use full text).
"""

from __future__ import annotations

from pipeline.schema import FilteredPaper, NOT_REPORTED

# First target taxonomy: CCS capture subpaths for cement/concrete applications.
CCS_SUBPATHS: list[str] = [
    "calcium_looping",
    "chemical_absorption",
    "cryogenic_processes",
    "oxy_fuel_combustion",
    "membrane_separation",
    "direct_separation",
]

CCS_SUBPATH_DESCRIPTIONS: dict[str, str] = {
    "calcium_looping": "CaL / CaO-CaCO3 looping, calcination-carbonation cycles for cement kiln CO2 capture",
    "chemical_absorption": "Amine/solvent absorption, post-combustion capture for cement flue gas",
    "cryogenic_processes": "Cryogenic or low-temperature CO2 separation / liquefaction",
    "oxy_fuel_combustion": "Oxy-fuel or oxygen-enriched combustion with high-CO2 flue gas",
    "membrane_separation": "Membrane-based CO2 or gas separation for cement applications",
    "direct_separation": "Direct/indirect calciner separation, LEILAC, separated calcination CO2 capture",
}


def get_screening_text(record: dict) -> str:
    """
    Build Stage 1 screening input from a raw corpus record.

    Initial relevance screening intentionally uses only the title and abstract.
    Full paper text (paragraphs) is excluded and must not be used here.
    """
    title = str(record.get("title") or "").strip() or "N/A"
    abstract = str(record.get("abstract") or "").strip() or "N/A"
    return f"Title: {title}\n\nAbstract: {abstract}"


def screening_text_from_paper(paper: FilteredPaper) -> str:
    """Build Stage 1 screening input from a normalized FilteredPaper."""
    title = (paper.title or "").strip() or "N/A"
    abstract = (paper.abstract or "").strip() or "N/A"
    return f"Title: {title}\n\nAbstract: {abstract}"


def screening_text_lower(paper: FilteredPaper) -> str:
    """Lowercased title+abstract text for keyword relevance scoring."""
    return f"{paper.title or ''} {paper.abstract or ''}".lower().strip()


def normalize_subpaths(raw: object) -> list[str]:
    """Coerce model output subpaths to the allowed CCS taxonomy."""
    if not isinstance(raw, list):
        return []
    normalized: list[str] = []
    for item in raw:
        key = str(item).strip().lower().replace("-", "_").replace(" ", "_")
        if key in CCS_SUBPATHS and key not in normalized:
            normalized.append(key)
    return normalized


def coerce_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))
