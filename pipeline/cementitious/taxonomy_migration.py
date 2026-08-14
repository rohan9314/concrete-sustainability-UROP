"""Map the cementitious 9×58 runtime taxonomy onto the five-level canonical tree.

Old runtime:
  category (Cementitious Materials)
    → subcategory (9 groups)
      → sub_subcategory (58 leaves)

New canonical:
  L0 Concrete Decarbonization
    → L1 Cementitious Materials
      → L2 (the old 9 groups, with Multi-Material Blends renamed)
        → L3 technology subfamily
          → L4 specific technology

Historical records that only classified to an old leaf are mapped to the matching
new Level-3 node with taxonomy_level_4 = N.A. unless technology_variant matches a
Level-4 child. We do not invent Level-4 specificity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.cementitious.decarbonization_taxonomy import (
    TAXONOMY_NA,
    DecarbonizationTaxonomy,
    get_decarbonization_taxonomy,
)
from pipeline.cementitious.paths import is_taxonomy_na, taxonomy_slugify
from pipeline.cementitious.taxonomy import Taxonomy, get_taxonomy

L0 = "Concrete Decarbonization"
L1 = "Cementitious Materials"


@dataclass(frozen=True)
class LeafMigration:
    old_leaf_slug: str
    old_leaf_label: str
    old_subcategory_slug: str
    level_2: str
    level_3: str
    level_4: str | None
    status: str
    notes: str


def _m(
    old_slug: str,
    old_label: str,
    old_sub: str,
    level_2: str,
    level_3: str,
    *,
    level_4: str | None = None,
    status: str = "promoted_to_level_3",
    notes: str = "",
) -> LeafMigration:
    return LeafMigration(
        old_leaf_slug=old_slug,
        old_leaf_label=old_label,
        old_subcategory_slug=old_sub,
        level_2=level_2,
        level_3=level_3,
        level_4=level_4,
        status=status,
        notes=notes
        or (
            "Old runtime leaf is now a Level-3 subfamily; Level 4 left N.A. unless "
            "technology_variant matches a Level-4 child."
        ),
    )


LEAF_MIGRATIONS: tuple[LeafMigration, ...] = (
    # Conventional and Blended Cements
    _m(
        "ordinary_portland_cement",
        "Ordinary Portland Cement",
        "conventional_and_blended_cements",
        "Conventional and Blended Cements",
        "Ordinary Portland Cement",
    ),
    _m(
        "portland_limestone_cement",
        "Portland-Limestone Cement",
        "conventional_and_blended_cements",
        "Conventional and Blended Cements",
        "Reduced-Clinker and Blended Cements",
        level_4="Portland-Limestone Cement (PLC / Type IL)",
        status="mapped_to_level_4",
        notes="Old leaf matches a specific Level-4 blended-cement product.",
    ),
    _m(
        "portland_pozzolan_cement",
        "Portland-Pozzolan Cement",
        "conventional_and_blended_cements",
        "Conventional and Blended Cements",
        "Reduced-Clinker and Blended Cements",
        level_4="Portland-Pozzolan Cement (Type IP)",
        status="mapped_to_level_4",
        notes="Old leaf matches a specific Level-4 blended-cement product.",
    ),
    _m(
        "portland_blast_furnace_slag_cement",
        "Portland Blast-Furnace Slag Cement",
        "conventional_and_blended_cements",
        "Conventional and Blended Cements",
        "Reduced-Clinker and Blended Cements",
        level_4="Portland Blast-Furnace Slag Cement (Type IS)",
        status="mapped_to_level_4",
        notes="Old leaf matches a specific Level-4 blended-cement product.",
    ),
    _m(
        "limestone_calcined_clay_cement",
        "Limestone Calcined Clay Cement",
        "conventional_and_blended_cements",
        "Conventional and Blended Cements",
        "Reduced-Clinker and Blended Cements",
        level_4="Limestone Calcined Clay Cement (LC3)",
        status="mapped_to_level_4",
        notes="Old leaf matches a specific Level-4 blended-cement product.",
    ),
    _m(
        "other_blended_hydraulic_cement",
        "Other Blended Hydraulic Cement",
        "conventional_and_blended_cements",
        "Conventional and Blended Cements",
        "Reduced-Clinker and Blended Cements",
        level_4="Other Blended Hydraulic Cements",
        status="mapped_to_level_4",
        notes="Label pluralized; same other-blended-cement bucket.",
    ),
    # Clinker feedstock
    _m(
        "industrial_waste_derived_clinker_feedstocks",
        "Industrial Waste-Derived Clinker Feedstocks",
        "clinker_feedstock_decarbonization",
        "Clinker Feedstock Decarbonization",
        "Industrial-Waste Feedstocks",
        notes="Renamed Industrial Waste-Derived Clinker Feedstocks → Industrial-Waste Feedstocks (L3).",
    ),
    _m(
        "recycled_cementitious_feedstocks",
        "Recycled Cementitious Feedstocks",
        "clinker_feedstock_decarbonization",
        "Clinker Feedstock Decarbonization",
        "Recycled Cementitious Feedstocks",
    ),
    _m(
        "biogenic_calcium_feedstocks",
        "Biogenic Calcium Feedstocks",
        "clinker_feedstock_decarbonization",
        "Clinker Feedstock Decarbonization",
        "Biogenic Calcium Feedstocks",
    ),
    _m(
        "composite_waste_feedstocks",
        "Composite Waste Feedstocks",
        "clinker_feedstock_decarbonization",
        "Clinker Feedstock Decarbonization",
        "Composite-Waste Feedstocks",
        notes="Hyphenated Composite-Waste Feedstocks.",
    ),
    _m(
        "alternative_mineral_feedstocks",
        "Alternative Mineral Feedstocks",
        "clinker_feedstock_decarbonization",
        "Clinker Feedstock Decarbonization",
        "Alternative Mineral Feedstocks",
    ),
    # Manufacturing efficiency — two old grinding leaves collapse into one L3
    _m(
        "raw_meal_grinding_efficiency",
        "Raw Meal Grinding Efficiency",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Raw Meal Grinding and Clinker Milling",
        status="merged_into_level_3",
        notes="Old grinding leaf merged into combined L3 Raw Meal Grinding and Clinker Milling.",
    ),
    _m(
        "clinker_milling_efficiency",
        "Clinker Milling Efficiency",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Raw Meal Grinding and Clinker Milling",
        status="merged_into_level_3",
        notes="Old milling leaf merged into combined L3 Raw Meal Grinding and Clinker Milling.",
    ),
    _m(
        "kiln_fuel_substitution",
        "Kiln Fuel Substitution",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Kiln Fuel Substitution",
    ),
    _m(
        "kiln_electrification",
        "Kiln Electrification",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Electrification",
        notes="Renamed Kiln Electrification → Electrification (L3).",
    ),
    _m(
        "solar_thermal_kiln_heating",
        "Solar Thermal Kiln Heating",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Solar Thermal",
        notes="Renamed Solar Thermal Kiln Heating → Solar Thermal (L3).",
    ),
    _m(
        "hydrogen_based_kiln_heating",
        "Hydrogen-Based Kiln Heating",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Hydrogen",
        notes="Renamed Hydrogen-Based Kiln Heating → Hydrogen (L3).",
    ),
    _m(
        "waste_heat_recovery",
        "Waste Heat Recovery",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Waste Heat Recovery",
    ),
    _m(
        "kiln_technology_upgrades",
        "Kiln Technology Upgrades",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Kiln Technology Upgrades",
    ),
    _m(
        "kiln_thermal_efficiency_improvements",
        "Kiln Thermal-Efficiency Improvements",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Thermal Efficiency",
        notes="Renamed Kiln Thermal-Efficiency Improvements → Thermal Efficiency (L3).",
    ),
    _m(
        "digital_and_ai_process_optimization",
        "Digital and AI Process Optimization",
        "cement_manufacturing_efficiency",
        "Cement Manufacturing Efficiency",
        "Digital and AI Process Optimization",
    ),
    # Cement-plant carbon capture — old leaves become L3
    _m(
        "chemical_absorption",
        "Chemical Absorption",
        "cement_plant_carbon_capture",
        "Cement-Plant Carbon Capture",
        "Chemical Absorption",
    ),
    _m(
        "cryogenic_carbon_capture",
        "Cryogenic Carbon Capture",
        "cement_plant_carbon_capture",
        "Cement-Plant Carbon Capture",
        "Cryogenic Carbon Capture",
    ),
    _m(
        "oxy_fuel_combustion",
        "Oxy-Fuel Combustion",
        "cement_plant_carbon_capture",
        "Cement-Plant Carbon Capture",
        "Oxy-Fuel Combustion",
    ),
    _m(
        "membrane_separation",
        "Membrane Separation",
        "cement_plant_carbon_capture",
        "Cement-Plant Carbon Capture",
        "Membrane Separation",
    ),
    _m(
        "calcium_looping",
        "Calcium Looping",
        "cement_plant_carbon_capture",
        "Cement-Plant Carbon Capture",
        "Calcium Looping",
    ),
    _m(
        "direct_separation",
        "Direct Separation",
        "cement_plant_carbon_capture",
        "Cement-Plant Carbon Capture",
        "Direct Separation",
    ),
    # Alternative chemistries
    _m(
        "calcium_silicate_cements",
        "Calcium Silicate Cements",
        "alternative_cement_chemistries",
        "Alternative Cement Chemistries",
        "Calcium Silicate Cements",
    ),
    _m(
        "belite_and_calcium_sulfoaluminate_cements",
        "Belite and Calcium Sulfoaluminate Cements",
        "alternative_cement_chemistries",
        "Alternative Cement Chemistries",
        "Belite Calcium Sulfoaluminate Cements",
        notes="Renamed Belite and Calcium Sulfoaluminate Cements → Belite Calcium Sulfoaluminate Cements.",
    ),
    _m(
        "reactive_magnesia_cements",
        "Reactive Magnesia Cements",
        "alternative_cement_chemistries",
        "Alternative Cement Chemistries",
        "Reactive Magnesia Cements",
    ),
    _m(
        "alkali_activated_cements",
        "Alkali-Activated Cements",
        "alternative_cement_chemistries",
        "Alternative Cement Chemistries",
        "Alkali-Activated Cements",
    ),
    _m(
        "biocements",
        "Biocements",
        "alternative_cement_chemistries",
        "Alternative Cement Chemistries",
        "Biocements",
    ),
    _m(
        "other_alternative_cement_chemistries",
        "Other Alternative Cement Chemistries",
        "alternative_cement_chemistries",
        "Alternative Cement Chemistries",
        "Other Alternative Cement Chemistries",
    ),
    # Conventional SCMs
    _m(
        "slag_cement",
        "Slag Cement",
        "conventional_supplementary_cementitious_materials",
        "Conventional Supplementary Cementitious Materials",
        "Slag Cement",
    ),
    _m(
        "coal_ash",
        "Coal Ash",
        "conventional_supplementary_cementitious_materials",
        "Conventional Supplementary Cementitious Materials",
        "Coal Ash",
    ),
    _m(
        "silica_fume",
        "Silica Fume",
        "conventional_supplementary_cementitious_materials",
        "Conventional Supplementary Cementitious Materials",
        "Silica Fume",
    ),
    _m(
        "natural_pozzolans",
        "Natural Pozzolans",
        "conventional_supplementary_cementitious_materials",
        "Conventional Supplementary Cementitious Materials",
        "Natural Pozzolans",
    ),
    _m(
        "glass_pozzolans",
        "Glass Pozzolans",
        "conventional_supplementary_cementitious_materials",
        "Conventional Supplementary Cementitious Materials",
        "Glass Pozzolans",
    ),
    _m(
        "calcined_clays",
        "Calcined Clays",
        "conventional_supplementary_cementitious_materials",
        "Conventional Supplementary Cementitious Materials",
        "Calcined Clays",
    ),
    # Emerging SCMs
    _m(
        "biomass_ashes",
        "Biomass Ashes",
        "emerging_supplementary_cementitious_materials",
        "Emerging Supplementary Cementitious Materials",
        "Biomass Ashes",
    ),
    _m(
        "waste_incineration_ashes",
        "Waste-Incineration Ashes",
        "emerging_supplementary_cementitious_materials",
        "Emerging Supplementary Cementitious Materials",
        "Waste-Incineration Ashes",
    ),
    _m(
        "mine_tailings",
        "Mine Tailings",
        "emerging_supplementary_cementitious_materials",
        "Emerging Supplementary Cementitious Materials",
        "Mine Tailings",
    ),
    _m(
        "carbonated_waste_derived_scms",
        "Carbonated Waste-Derived SCMs",
        "emerging_supplementary_cementitious_materials",
        "Emerging Supplementary Cementitious Materials",
        "Carbonated Waste-Derived SCMs",
    ),
    _m(
        "synthetic_calcium_carbonates",
        "Synthetic Calcium Carbonates",
        "emerging_supplementary_cementitious_materials",
        "Emerging Supplementary Cementitious Materials",
        "Synthetic Calcium Carbonates",
    ),
    _m(
        "recycled_cementitious_materials",
        "Recycled Cementitious Materials",
        "emerging_supplementary_cementitious_materials",
        "Emerging Supplementary Cementitious Materials",
        "Recycled Cementitious Materials",
        notes="Distinct from Aggregate Procurement → Recycled Concrete Aggregates.",
    ),
    _m(
        "other_industrial_waste_derived_scms",
        "Other Industrial Waste-Derived SCMs",
        "emerging_supplementary_cementitious_materials",
        "Emerging Supplementary Cementitious Materials",
        "Other Industrial Waste-Derived SCMs",
    ),
    # Multi-material blends — L2 renamed
    _m(
        "binary_cementitious_blends",
        "Binary Cementitious Blends",
        "multi_material_cementitious_blends",
        "Multi-Material Blends",
        "Binary Blends",
        notes="L2 renamed Multi-Material Cementitious Blends → Multi-Material Blends; leaf → Binary Blends.",
    ),
    _m(
        "ternary_cementitious_blends",
        "Ternary Cementitious Blends",
        "multi_material_cementitious_blends",
        "Multi-Material Blends",
        "Ternary Blends",
        notes="Renamed Ternary Cementitious Blends → Ternary Blends.",
    ),
    _m(
        "quaternary_cementitious_blends",
        "Quaternary Cementitious Blends",
        "multi_material_cementitious_blends",
        "Multi-Material Blends",
        "Quaternary Blends",
        notes="Renamed Quaternary Cementitious Blends → Quaternary Blends.",
    ),
    _m(
        "high_scm_binder_systems",
        "High-SCM Binder Systems",
        "multi_material_cementitious_blends",
        "Multi-Material Blends",
        "High-SCM Blends",
        notes="Renamed High-SCM Binder Systems → High-SCM Blends.",
    ),
    _m(
        "hybrid_binder_systems",
        "Hybrid Binder Systems",
        "multi_material_cementitious_blends",
        "Multi-Material Blends",
        "Hybrid Binder Systems",
    ),
    # Fillers
    _m(
        "carbonaceous_fillers",
        "Carbonaceous Fillers",
        "inert_and_low_reactivity_fillers",
        "Inert and Low-Reactivity Fillers",
        "Carbonaceous Fillers",
    ),
    _m(
        "carbonate_fillers",
        "Carbonate Fillers",
        "inert_and_low_reactivity_fillers",
        "Inert and Low-Reactivity Fillers",
        "Carbonate Fillers",
    ),
    _m(
        "siliceous_fillers",
        "Siliceous Fillers",
        "inert_and_low_reactivity_fillers",
        "Inert and Low-Reactivity Fillers",
        "Siliceous Fillers",
    ),
    _m(
        "rock_and_quarry_fillers",
        "Rock and Quarry Fillers",
        "inert_and_low_reactivity_fillers",
        "Inert and Low-Reactivity Fillers",
        "Rock and Quarry Fillers",
    ),
    _m(
        "industrial_mineral_fillers",
        "Industrial Mineral Fillers",
        "inert_and_low_reactivity_fillers",
        "Inert and Low-Reactivity Fillers",
        "Industrial Mineral Fillers",
    ),
    _m(
        "recycled_mineral_fillers",
        "Recycled Mineral Fillers",
        "inert_and_low_reactivity_fillers",
        "Inert and Low-Reactivity Fillers",
        "Recycled Mineral Fillers",
    ),
    _m(
        "engineered_ultrafine_fillers",
        "Engineered Ultrafine Fillers",
        "inert_and_low_reactivity_fillers",
        "Inert and Low-Reactivity Fillers",
        "Engineered Ultrafine Fillers",
    ),
)

MIGRATIONS_BY_LEAF = {m.old_leaf_slug: m for m in LEAF_MIGRATIONS}


def migration_rows() -> list[dict[str, str]]:
    rows = []
    for m in LEAF_MIGRATIONS:
        rows.append(
            {
                "old_subcategory_slug": m.old_subcategory_slug,
                "old_leaf_slug": m.old_leaf_slug,
                "old_path": f"Cementitious Materials / {m.old_subcategory_slug} / {m.old_leaf_slug}",
                "taxonomy_level_0": L0,
                "taxonomy_level_1": L1,
                "taxonomy_level_2": m.level_2,
                "taxonomy_level_3": m.level_3,
                "taxonomy_level_4": m.level_4 or TAXONOMY_NA,
                "mapping_status": m.status,
                "notes": m.notes,
            }
        )
    return rows


def coverage_report(
    runtime: Taxonomy | None = None,
    decarb: DecarbonizationTaxonomy | None = None,
) -> dict[str, Any]:
    runtime = runtime or get_taxonomy()
    decarb = decarb or get_decarbonization_taxonomy()
    old_slugs = set(runtime.sub_subcategories)
    mapped = set(MIGRATIONS_BY_LEAF)
    missing = sorted(old_slugs - mapped)
    extra = sorted(mapped - old_slugs)
    invalid: list[str] = []
    for m in LEAF_MIGRATIONS:
        labels = [L0, L1, m.level_2, m.level_3]
        if m.level_4:
            labels.append(m.level_4)
        try:
            decarb.resolve_path_labels(labels)
        except ValueError as exc:
            invalid.append(f"{m.old_leaf_slug}: {exc}")
    return {
        "old_leaf_count": len(old_slugs),
        "mapped_count": len(mapped),
        "unmapped_old_leaves": missing,
        "unknown_mapped_slugs": extra,
        "invalid_new_paths": invalid,
        "complete": not missing and not extra and not invalid,
        "rows": migration_rows(),
    }


def _match_level4(decarb: DecarbonizationTaxonomy, l3_path: str, variant: str) -> str:
    if is_taxonomy_na(variant):
        return TAXONOMY_NA
    child = decarb.find_child(l3_path, variant)
    if child is not None:
        return child.label
    folded = variant.strip().casefold()
    for child in decarb.children(l3_path):
        haystacks = [child.label, child.slug, *child.aliases]
        if any(folded == h.casefold() or folded in h.casefold() or h.casefold() in folded for h in haystacks):
            return child.label
    return TAXONOMY_NA


def runtime_assignment_for_decarb_node(
    node: Any,
    *,
    runtime: Taxonomy | None = None,
) -> dict[str, str] | None:
    """Map a canonical node onto the 9×58 runtime assignment when it is cementitious.

    Non-cementitious Level-1 branches have no runtime leaf; callers should stamp
    ``taxonomy_level_*`` only.
    """
    labels = list(getattr(node, "path_labels", ()) or [])
    if len(labels) < 2 or labels[1] != L1:
        return None
    runtime = runtime or get_taxonomy()
    l2 = labels[2] if len(labels) > 2 else ""
    l3 = labels[3] if len(labels) > 3 else ""
    l4 = labels[4] if len(labels) > 4 else ""
    best = None
    for mapping in LEAF_MIGRATIONS:
        if mapping.level_2 != l2:
            continue
        if mapping.level_4 and l4 and mapping.level_4 == l4:
            best = mapping
            break
        if mapping.level_3 == l3:
            best = mapping
    if best is None:
        return None
    parent = runtime.subcategories.get(best.old_subcategory_slug)
    child = runtime.sub_subcategories.get(best.old_leaf_slug)
    if parent is None or child is None:
        return None
    return {
        "subcategory": parent.display_name,
        "subcategory_slug": parent.slug,
        "sub_subcategory": child.display_name,
        "sub_subcategory_slug": child.slug,
    }


def apply_decarbonization_path(
    record: dict[str, Any],
    *,
    runtime: Taxonomy | None = None,
    decarb: DecarbonizationTaxonomy | None = None,
) -> dict[str, str]:
    """Fill taxonomy_level_0..4 from existing fields without inventing L4."""
    decarb = decarb or get_decarbonization_taxonomy()
    runtime = runtime or get_taxonomy()
    out = dict(record)

    def _set(level: int, label: str) -> None:
        out[f"taxonomy_level_{level}"] = label
        try:
            out[f"taxonomy_level_{level}_slug"] = (
                TAXONOMY_NA if is_taxonomy_na(label) else taxonomy_slugify(label)
            )
        except ValueError:
            out[f"taxonomy_level_{level}_slug"] = TAXONOMY_NA

    # If a complete new path is already present, just fill slugs.
    if out.get("taxonomy_level_1") and not is_taxonomy_na(out.get("taxonomy_level_1")):
        for i in range(5):
            label = out.get(f"taxonomy_level_{i}") or TAXONOMY_NA
            if not label:
                label = TAXONOMY_NA
            _set(i, label if label else TAXONOMY_NA)
        if is_taxonomy_na(out.get("taxonomy_level_0")):
            _set(0, L0)
        return out

    leaf_slug = str(out.get("sub_subcategory_slug") or "").strip()
    mapping = MIGRATIONS_BY_LEAF.get(leaf_slug)
    if mapping is None:
        _set(0, L0)
        _set(1, out.get("category") or L1)
        for i in range(2, 5):
            if not out.get(f"taxonomy_level_{i}"):
                _set(i, TAXONOMY_NA)
        return out

    _set(0, L0)
    _set(1, L1)
    _set(2, mapping.level_2)
    _set(3, mapping.level_3)
    l3_node = decarb.resolve_path_labels([L0, L1, mapping.level_2, mapping.level_3])
    if mapping.level_4:
        _set(4, mapping.level_4)
    else:
        variant = str(out.get("technology_variant") or out.get("canonical_technology_name") or "")
        _set(4, _match_level4(decarb, l3_node.path, variant))
    return out
