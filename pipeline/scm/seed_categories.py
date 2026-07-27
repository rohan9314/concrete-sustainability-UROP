"""Playbook-defined SCM seed categories — anchors, not a complete taxonomy."""

from __future__ import annotations

from dataclasses import dataclass

OUTPUT_DIR_NAME = "scm"
CATEGORY_LABEL = "Supplementary Cementitious Materials"

SCM_SEED_CATEGORIES = {
    "slag_cement": "Slag Cement",
    "coal_fly_ash": "Coal Fly Ash",
    "harvested_coal_ash": "Harvested Coal Ash",
    "coal_bottom_ash": "Coal Bottom Ash",
    "silica_fume": "Silica Fume",
    "natural_pozzolans": "Natural Pozzolans",
    "glass_pozzolan": "Glass Pozzolan",
    "ternary_blends": "Ternary Blends",
}


@dataclass(frozen=True)
class ScmSeedCategory:
    slug: str
    display_name: str
    category: str
    search_terms: tuple[str, ...]
    synonyms: tuple[str, ...]
    abbreviations: tuple[str, ...]
    retrieval_query: str
    negative_terms: tuple[str, ...] = ()
    is_binder_system: bool = False

    @property
    def results_filename(self) -> str:
        return f"{self.slug}_results.csv"

    @property
    def citations_filename(self) -> str:
        return f"{self.slug}_citations.csv"

    @property
    def literature_filename(self) -> str:
        return f"{self.slug}_literature.jsonl"

    @property
    def web_filename(self) -> str:
        return f"{self.slug}_web.jsonl"


def _cat(
    slug: str,
    *,
    search_terms: tuple[str, ...],
    synonyms: tuple[str, ...],
    abbreviations: tuple[str, ...] = (),
    retrieval_query: str,
    negative_terms: tuple[str, ...] = (),
    is_binder_system: bool = False,
) -> ScmSeedCategory:
    return ScmSeedCategory(
        slug=slug,
        display_name=SCM_SEED_CATEGORIES[slug],
        category=CATEGORY_LABEL,
        search_terms=search_terms,
        synonyms=synonyms,
        abbreviations=abbreviations,
        retrieval_query=retrieval_query,
        negative_terms=negative_terms,
        is_binder_system=is_binder_system,
    )


SEED_CATEGORY_DEFINITIONS: dict[str, ScmSeedCategory] = {
    "slag_cement": _cat(
        "slag_cement",
        search_terms=(
            "slag cement",
            "ground granulated blast furnace slag",
            "blast furnace slag",
            "GGBFS",
            "GGBS",
            "slag binder",
        ),
        synonyms=(
            "slag cement",
            "ggbfs",
            "ggbs",
            "ground granulated blast furnace slag",
            "blast furnace slag",
            "slag binder",
            "slag replacement",
        ),
        abbreviations=("GGBFS", "GGBS", "BFS"),
        retrieval_query=(
            "slag cement GGBFS ground granulated blast furnace slag "
            "cement replacement concrete"
        ),
        negative_terms=("steel slag aggregate", "air-cooled slag aggregate"),
    ),
    "coal_fly_ash": _cat(
        "coal_fly_ash",
        search_terms=(
            "coal fly ash",
            "fly ash",
            "Class F fly ash",
            "Class C fly ash",
            "pulverized fuel ash",
            "PFA",
        ),
        synonyms=(
            "fly ash",
            "coal fly ash",
            "class f fly ash",
            "class c fly ash",
            "pulverized fuel ash",
            "pfa",
            "cfa",
        ),
        abbreviations=("PFA", "CFA", "FA"),
        retrieval_query=(
            "coal fly ash Class F Class C cement replacement pozzolan concrete"
        ),
        negative_terms=("biomass fly ash", "municipal solid waste ash"),
    ),
    "harvested_coal_ash": _cat(
        "harvested_coal_ash",
        search_terms=(
            "harvested coal ash",
            "reclaimed fly ash",
            "landfilled fly ash",
            "ponded ash",
            "harvested ash",
            "reclaimed coal ash",
        ),
        synonyms=(
            "harvested coal ash",
            "reclaimed fly ash",
            "landfilled fly ash",
            "ponded ash",
            "harvested ash",
            "reclaimed coal ash",
            "beneficiated ash",
        ),
        abbreviations=(),
        retrieval_query=(
            "harvested coal ash reclaimed fly ash landfilled ponded ash "
            "cement replacement"
        ),
    ),
    "coal_bottom_ash": _cat(
        "coal_bottom_ash",
        search_terms=(
            "coal bottom ash",
            "bottom ash",
            "boiler bottom ash",
            "furnace bottom ash",
        ),
        synonyms=(
            "coal bottom ash",
            "bottom ash",
            "boiler bottom ash",
            "furnace bottom ash",
            "cba",
        ),
        abbreviations=("CBA", "FBA"),
        retrieval_query=(
            "coal bottom ash cement replacement binder concrete mortar"
        ),
        negative_terms=("bottom ash aggregate only",),
    ),
    "silica_fume": _cat(
        "silica_fume",
        search_terms=(
            "silica fume",
            "microsilica",
            "condensed silica fume",
            "CSF",
        ),
        synonyms=(
            "silica fume",
            "microsilica",
            "condensed silica fume",
            "csf",
            "silicon dioxide fume",
        ),
        abbreviations=("SF", "CSF"),
        retrieval_query=(
            "silica fume microsilica cement replacement high performance concrete"
        ),
    ),
    "natural_pozzolans": _cat(
        "natural_pozzolans",
        search_terms=(
            "natural pozzolan",
            "volcanic ash",
            "pumice",
            "zeolite",
            "tuff",
            "calcined clay",
            "metakaolin",
            "natural pozzolana",
        ),
        synonyms=(
            "natural pozzolan",
            "natural pozzolana",
            "volcanic ash",
            "pumice",
            "zeolite",
            "tuff",
            "calcined clay",
            "metakaolin",
            "trass",
        ),
        abbreviations=("NP", "MK"),
        retrieval_query=(
            "natural pozzolan volcanic ash metakaolin calcined clay "
            "cement replacement"
        ),
    ),
    "glass_pozzolan": _cat(
        "glass_pozzolan",
        search_terms=(
            "glass pozzolan",
            "ground glass",
            "waste glass powder",
            "recycled glass powder",
            "glass powder SCM",
        ),
        synonyms=(
            "glass pozzolan",
            "ground glass",
            "waste glass powder",
            "recycled glass powder",
            "glass powder",
            "cullet powder",
        ),
        abbreviations=("GP", "WGP"),
        retrieval_query=(
            "glass pozzolan ground glass powder cement replacement concrete"
        ),
        negative_terms=("glass aggregate", "glass fiber"),
    ),
    "ternary_blends": _cat(
        "ternary_blends",
        search_terms=(
            "ternary blend",
            "ternary cement",
            "ternary binder",
            "portland cement slag fly ash",
            "multi-component cement",
            "composite cement ternary",
        ),
        synonyms=(
            "ternary blend",
            "ternary cement",
            "ternary binder",
            "ternary mixture",
            "multi-component cement",
            "composite cement",
        ),
        abbreviations=(),
        retrieval_query=(
            "ternary blend cement slag fly ash silica fume binder system "
            "concrete replacement"
        ),
        is_binder_system=True,
    ),
}


def list_seed_category_ids() -> list[str]:
    return list(SCM_SEED_CATEGORIES.keys())


def get_seed_category(slug: str) -> ScmSeedCategory:
    key = slug.strip().lower()
    if key not in SEED_CATEGORY_DEFINITIONS:
        available = ", ".join(list_seed_category_ids())
        raise KeyError(f"Unknown SCM seed category {slug!r}. Available: {available}")
    return SEED_CATEGORY_DEFINITIONS[key]


def all_seed_categories() -> list[ScmSeedCategory]:
    return [SEED_CATEGORY_DEFINITIONS[slug] for slug in list_seed_category_ids()]


def resolve_seed_category_slug(name: str) -> str:
    """Resolve a slug or display name to a seed-category identifier."""
    key = name.strip().lower()
    if key in SEED_CATEGORY_DEFINITIONS:
        return key

    normalized = key.replace(" ", "_").replace("-", "_")
    if normalized in SEED_CATEGORY_DEFINITIONS:
        return normalized

    for slug, display in SCM_SEED_CATEGORIES.items():
        if display.strip().lower() == key:
            return slug

    available = ", ".join(
        f"{slug} ({name})" for slug, name in SCM_SEED_CATEGORIES.items()
    )
    raise KeyError(f"Unknown SCM seed category {name!r}. Available: {available}")
