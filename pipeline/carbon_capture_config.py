"""
Carbon capture methodology definitions for the decarbonization levers taxonomy.

Each methodology drives separate retrieval and extraction runs so results are
scoped to a specific capture subcategory rather than generic carbon capture.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OUTPUT_DIR_NAME = "carbon_capture"


@dataclass(frozen=True)
class CarbonCaptureMethodology:
    slug: str
    display_name: str
    category: str
    subcategory: str
    search_keywords: tuple[str, ...]
    synonyms: tuple[str, ...]
    retrieval_query: str
    screening_subpath: str | None = None

    @property
    def answers_filename(self) -> str:
        return f"{self.slug}_answers.csv"

    @property
    def citations_filename(self) -> str:
        return f"{self.slug}_citations.csv"


CARBON_CAPTURE_METHODOLOGIES: dict[str, CarbonCaptureMethodology] = {
    "amine_absorption": CarbonCaptureMethodology(
        slug="amine_absorption",
        display_name="Solvent-based / amine absorption",
        category="Carbon Capture",
        subcategory="Solvent-based / amine absorption",
        search_keywords=(
            "amine absorption",
            "solvent-based capture",
            "post-combustion capture",
            "MEA",
            "monoethanolamine",
            "chemical absorption",
            "amine scrubbing",
        ),
        synonyms=(
            "amine",
            "solvent",
            "absorption",
            "post-combustion",
            "mea",
            "monoethanolamine",
            "chemical absorption",
            "solvent-based capture",
        ),
        retrieval_query=(
            "amine absorption solvent-based carbon capture cement kiln "
            "post-combustion CO2 capture"
        ),
        screening_subpath="chemical_absorption",
    ),
    "membrane_separation": CarbonCaptureMethodology(
        slug="membrane_separation",
        display_name="Membrane separation",
        category="Carbon Capture",
        subcategory="Membrane separation",
        search_keywords=(
            "membrane separation",
            "CO2 membrane",
            "gas separation membrane",
            "polymeric membrane",
            "facilitated transport membrane",
        ),
        synonyms=(
            "membrane",
            "membrane separation",
            "co2 membrane",
            "gas separation membrane",
            "polymeric membrane",
            "ceramic membrane",
        ),
        retrieval_query=(
            "membrane separation carbon capture cement flue gas CO2 separation"
        ),
        screening_subpath="membrane_separation",
    ),
    "calcium_looping": CarbonCaptureMethodology(
        slug="calcium_looping",
        display_name="Calcium looping",
        category="Carbon Capture",
        subcategory="Calcium looping",
        search_keywords=(
            "calcium looping",
            "CaL",
            "calcination carbonation",
            "CaO-CaCO3",
            "sorbent looping",
        ),
        synonyms=(
            "calcium looping",
            "cal",
            "cao",
            "caco3",
            "calcination",
            "carbonation",
            "sorbent looping",
        ),
        retrieval_query="calcium looping carbon capture cement kiln calcination",
        screening_subpath="calcium_looping",
    ),
    "oxyfuel_combustion": CarbonCaptureMethodology(
        slug="oxyfuel_combustion",
        display_name="Oxyfuel combustion",
        category="Carbon Capture",
        subcategory="Oxyfuel combustion",
        search_keywords=(
            "oxyfuel combustion",
            "oxy-fuel",
            "oxygen-enriched combustion",
            "high CO2 flue gas",
            "flue gas recycle",
        ),
        synonyms=(
            "oxyfuel",
            "oxy-fuel",
            "oxy-fuel combustion",
            "oxygen combustion",
            "oxygen-enriched combustion",
            "flue gas recycle",
        ),
        retrieval_query="oxyfuel combustion carbon capture cement kiln high CO2 flue gas",
        screening_subpath="oxy_fuel_combustion",
    ),
    "cryogenic_capture": CarbonCaptureMethodology(
        slug="cryogenic_capture",
        display_name="Cryogenic capture",
        category="Carbon Capture",
        subcategory="Cryogenic capture",
        search_keywords=(
            "cryogenic capture",
            "cryogenic separation",
            "CO2 liquefaction",
            "low temperature separation",
            "phase separation",
        ),
        synonyms=(
            "cryogenic",
            "cryogenic capture",
            "cryogenic separation",
            "liquefaction",
            "co2 liquefaction",
            "low temperature separation",
        ),
        retrieval_query="cryogenic carbon capture cement CO2 liquefaction separation",
        screening_subpath="cryogenic_processes",
    ),
    "mineralization": CarbonCaptureMethodology(
        slug="mineralization",
        display_name="Mineralization / carbonation-based capture",
        category="Carbon Capture",
        subcategory="Mineralization / carbonation-based capture",
        search_keywords=(
            "mineral carbonation",
            "mineralization",
            "accelerated carbonation",
            "CO2 mineralization",
            "carbonation curing",
            "sequestration in concrete",
        ),
        synonyms=(
            "mineralization",
            "mineral carbonation",
            "carbonation",
            "accelerated carbonation",
            "co2 mineralization",
            "carbonation curing",
            "sequestration",
        ),
        retrieval_query=(
            "mineral carbonation mineralization cement concrete CO2 sequestration "
            "carbonation-based capture"
        ),
        screening_subpath=None,
    ),
}


def list_methodology_slugs() -> list[str]:
    return list(CARBON_CAPTURE_METHODOLOGIES.keys())


def get_methodology(slug: str) -> CarbonCaptureMethodology:
    key = slug.strip().lower()
    if key not in CARBON_CAPTURE_METHODOLOGIES:
        available = ", ".join(list_methodology_slugs())
        raise KeyError(f"Unknown methodology {slug!r}. Available: {available}")
    return CARBON_CAPTURE_METHODOLOGIES[key]


def all_methodologies() -> list[CarbonCaptureMethodology]:
    return [CARBON_CAPTURE_METHODOLOGIES[slug] for slug in list_methodology_slugs()]
