#!/usr/bin/env python3
"""Generate config/cementitious_materials_taxonomy.yaml from structured definitions."""

from __future__ import annotations

import json
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_YAML = REPO_ROOT / "config" / "cementitious_materials_taxonomy.yaml"
OUT_JSON = REPO_ROOT / "config" / "cementitious_materials_taxonomy.json"

TAXONOMY_VERSION = "cementitious-materials-v1-2026-07-30"
CATEGORY = "Cementitious Materials"
CATEGORY_SLUG = "cementitious_materials"

# Each subcategory: (slug, display, definition, inclusion, exclusion, domain, roles, children)
# children: list of (slug, display, definition, inclusion, exclusion, synonyms, variants, domain, roles)

SUBCATEGORIES: list[dict] = []


def node(
    *,
    slug: str,
    display: str,
    parent: str,
    level: str,
    definition: str,
    inclusion: list[str],
    exclusion: list[str],
    synonyms: list[str],
    variants: list[str],
    domain: str,
    roles: list[str],
    positive_cues: list[str] | None = None,
    negative_cues: list[str] | None = None,
    retrieval_terms: list[str] | None = None,
) -> dict:
    return {
        "slug": slug,
        "display_name": display,
        "parent": parent,
        "level": level,
        "definition": definition,
        "inclusion_criteria": inclusion,
        "exclusion_criteria": exclusion,
        "representative_synonyms": synonyms,
        "representative_technology_variants": variants,
        "expected_technology_domain": domain,
        "allowed_functional_roles": roles,
        "positive_screening_cues": positive_cues or synonyms[:],
        "negative_screening_cues": negative_cues or [],
        "retrieval_query_terms": retrieval_terms or synonyms[:],
    }


def build() -> dict:
    subcats: list[dict] = []

    # 1 Conventional and Blended Cements
    s1_children = [
        node(
            slug="ordinary_portland_cement",
            display="Ordinary Portland Cement",
            parent="conventional_and_blended_cements",
            level="sub_subcategory",
            definition="Standard Portland cement conforming to ASTM C150 or equivalent without substantial SCM blending at the factory level.",
            inclusion=["OPC", "ASTM C150 Types I–V as primary binder"],
            exclusion=["PLC", "LC3", "Type IP/IS blended cements"],
            synonyms=["OPC", "Portland cement", "ordinary Portland cement"],
            variants=[
                "ASTM C150 Type I",
                "ASTM C150 Type II",
                "ASTM C150 Type III",
                "ASTM C150 Type IV",
                "ASTM C150 Type V",
            ],
            domain="Cement or Binder",
            roles=["Complete Binder", "Clinker-Containing Cement"],
        ),
        node(
            slug="portland_limestone_cement",
            display="Portland-Limestone Cement",
            parent="conventional_and_blended_cements",
            level="sub_subcategory",
            definition="Factory-produced Portland cement with interground or blended limestone (e.g., Type IL).",
            inclusion=["Type IL", "PLC", "limestone-blended Portland cement"],
            exclusion=["Limestone used only as inert filler addition on site", "LC3"],
            synonyms=["PLC", "Type IL", "Portland limestone cement"],
            variants=["Type IL Cement", "Limestone-Blended Portland Cement", "PLC"],
            domain="Cement or Binder",
            roles=["Complete Binder", "Clinker-Containing Cement"],
        ),
        node(
            slug="portland_pozzolan_cement",
            display="Portland-Pozzolan Cement",
            parent="conventional_and_blended_cements",
            level="sub_subcategory",
            definition="Factory-produced blended hydraulic cement containing pozzolan (e.g., Type IP).",
            inclusion=["Type IP", "natural-pozzolan blended cement", "calcined-clay blended cement as factory product"],
            exclusion=["Pozzolan added only as separate SCM at concrete plant"],
            synonyms=["Type IP", "Portland pozzolan cement", "PPC"],
            variants=["Type IP Cement", "Natural-Pozzolan Blended Cement", "Calcined-Clay Blended Cement"],
            domain="Cement or Binder",
            roles=["Complete Binder", "Clinker-Containing Cement"],
        ),
        node(
            slug="portland_blast_furnace_slag_cement",
            display="Portland Blast-Furnace Slag Cement",
            parent="conventional_and_blended_cements",
            level="sub_subcategory",
            definition="Factory-produced Portland cement blended with blast-furnace slag (e.g., Type IS).",
            inclusion=["Type IS", "high-slag blended cement as factory product"],
            exclusion=["GGBFS used only as separate SCM"],
            synonyms=["Type IS", "Portland slag cement", "blast-furnace slag cement"],
            variants=["Type IS Cement", "High-Slag Blended Cement"],
            domain="Cement or Binder",
            roles=["Complete Binder", "Clinker-Containing Cement"],
        ),
        node(
            slug="limestone_calcined_clay_cement",
            display="Limestone Calcined Clay Cement",
            parent="conventional_and_blended_cements",
            level="sub_subcategory",
            definition="Factory-produced or formulated LC3 / limestone–calcined-clay blended cement systems.",
            inclusion=["LC3", "limestone calcined clay cement as binder product"],
            exclusion=["Calcined clay used alone as SCM without LC3 binder framing"],
            synonyms=["LC3", "limestone calcined clay cement", "LC3 cement"],
            variants=["LC3", "Limestone-Calcined-Clay Blend", "Limestone Calcined Clay Cement"],
            domain="Cement or Binder",
            roles=["Complete Binder", "Clinker-Containing Cement", "Multi-Component Binder"],
        ),
        node(
            slug="other_blended_hydraulic_cement",
            display="Other Blended Hydraulic Cement",
            parent="conventional_and_blended_cements",
            level="sub_subcategory",
            definition="Other factory-produced blended hydraulic cements not covered by the specific nodes above.",
            inclusion=["Other ASTM C595 / EN blended cements"],
            exclusion=["Site-batched multi-SCM blends (see Multi-Material Cementitious Blends)"],
            synonyms=["blended hydraulic cement", "composite cement"],
            variants=["Other Blended Hydraulic Cement"],
            domain="Cement or Binder",
            roles=["Complete Binder", "Clinker-Containing Cement"],
        ),
    ]
    subcats.append(
        {
            **node(
                slug="conventional_and_blended_cements",
                display="Conventional and Blended Cements",
                parent=CATEGORY_SLUG,
                level="subcategory",
                definition="Ordinary Portland and factory-produced blended hydraulic cements.",
                inclusion=["OPC", "PLC", "Type IP/IS", "LC3 as cement product"],
                exclusion=["Separate SCM additions", "alkali-activated binders", "non-Portland alternative chemistries"],
                synonyms=["blended cement", "Portland cement", "hydraulic cement"],
                variants=[],
                domain="Cement or Binder",
                roles=["Complete Binder", "Clinker-Containing Cement"],
                negative_cues=["SCM only", "geopolymer", "alkali-activated"],
            ),
            "children": s1_children,
        }
    )

    # 2 Clinker Feedstock Decarbonization
    s2_children = [
        node(
            slug="industrial_waste_derived_clinker_feedstocks",
            display="Industrial Waste-Derived Clinker Feedstocks",
            parent="clinker_feedstock_decarbonization",
            level="sub_subcategory",
            definition="Industrial wastes used as raw meal / clinker kiln feedstocks.",
            inclusion=["slag-derived feedstock", "CKD as feedstock", "carbide sludge feedstock"],
            exclusion=["Same wastes used only as SCMs"],
            synonyms=["waste-derived clinker feedstock", "alternative raw meal"],
            variants=[
                "Slag-Derived Feedstock",
                "Lignite Ash Feedstock",
                "Carbide Sludge Feedstock",
                "Aerated Concrete Meal",
                "Sugar-Industry Lime Residue",
                "Cement Kiln Dust",
                "High-Calcium Industrial Waste",
            ],
            domain="Clinker Feedstock",
            roles=["Clinker Feedstock"],
        ),
        node(
            slug="biogenic_calcium_feedstocks",
            display="Biogenic Calcium Feedstocks",
            parent="clinker_feedstock_decarbonization",
            level="sub_subcategory",
            definition="Biogenic calcium sources used to replace carbonate limestone in clinker production.",
            inclusion=["biogenic limestone", "shell-derived Ca feedstock", "microalgae-grown limestone"],
            exclusion=["Biomass as kiln fuel only"],
            synonyms=["biogenic limestone", "biogenic calcium carbonate"],
            variants=[
                "Microalgae-Grown Limestone",
                "Biogenic Limestone",
                "Biogenic Calcium Carbonate",
                "Shell-Derived Calcium Feedstock",
            ],
            domain="Clinker Feedstock",
            roles=["Clinker Feedstock"],
        ),
        node(
            slug="recycled_cementitious_feedstocks",
            display="Recycled Cementitious Feedstocks",
            parent="clinker_feedstock_decarbonization",
            level="sub_subcategory",
            definition="Recovered cement paste or concrete fines reclinkered or used as kiln feedstock.",
            inclusion=["reclinkered cement paste", "electric cement recycling as feedstock"],
            exclusion=["Recycled cement paste used directly as SCM"],
            synonyms=["recovered cement paste feedstock", "reclinkering"],
            variants=[
                "Recovered Cement Paste",
                "Recycled Concrete Fines",
                "Reclinkered Cement Paste",
                "Electric Cement Recycling",
            ],
            domain="Clinker Feedstock",
            roles=["Clinker Feedstock"],
        ),
        node(
            slug="composite_waste_feedstocks",
            display="Composite Waste Feedstocks",
            parent="clinker_feedstock_decarbonization",
            level="sub_subcategory",
            definition="Composite material wastes used as clinker raw feed.",
            inclusion=["wind-turbine blade feedstock", "fiberglass-containing feedstock"],
            exclusion=["Composite wastes used only as aggregate"],
            synonyms=["composite waste feedstock", "FRP waste feedstock"],
            variants=[
                "Wind-Turbine Blade Feedstock",
                "Composite-Material Waste Feedstock",
                "Fiberglass-Containing Feedstock",
            ],
            domain="Clinker Feedstock",
            roles=["Clinker Feedstock"],
        ),
        node(
            slug="alternative_mineral_feedstocks",
            display="Alternative Mineral Feedstocks",
            parent="clinker_feedstock_decarbonization",
            level="sub_subcategory",
            definition="Non-waste alternative minerals used to reduce carbonate limestone demand.",
            inclusion=["calcium silicate rock feedstock", "non-carbonate calcium feedstock"],
            exclusion=["Standard limestone quarrying without alternative feedstock framing"],
            synonyms=["alternative mineral feedstock", "non-carbonate calcium"],
            variants=[
                "Calcium Silicate Rock Feedstock",
                "Non-Carbonate Calcium Feedstock",
                "Synthetic Limestone Feedstock",
            ],
            domain="Clinker Feedstock",
            roles=["Clinker Feedstock"],
        ),
    ]
    subcats.append(
        {
            **node(
                slug="clinker_feedstock_decarbonization",
                display="Clinker Feedstock Decarbonization",
                parent=CATEGORY_SLUG,
                level="subcategory",
                definition="Substitution of conventional carbonate limestone with alternative clinker raw feedstocks.",
                inclusion=["Alternative raw meal", "reclinkering", "biogenic Ca feedstock"],
                exclusion=["SCM use of same materials", "kiln fuel substitution"],
                synonyms=["alternative raw materials", "clinker feedstock"],
                variants=[],
                domain="Clinker Feedstock",
                roles=["Clinker Feedstock"],
                negative_cues=["used as SCM", "cement replacement", "kiln fuel"],
            ),
            "children": s2_children,
        }
    )

    # 3 Cement Manufacturing Efficiency
    s3_specs = [
        (
            "raw_meal_grinding_efficiency",
            "Raw Meal Grinding Efficiency",
            "Improvements to raw-meal grinding energy and fineness control.",
            [
                "High-Pressure Grinding Rolls",
                "Vertical Roller Mills",
                "Efficient Ball Mills",
                "Roller Presses",
                "Grinding-Aid Optimization",
                "Particle-Size Optimization",
            ],
        ),
        (
            "clinker_milling_efficiency",
            "Clinker Milling Efficiency",
            "Improvements to finish grinding of clinker/cement.",
            [
                "High-Pressure Grinding Rolls",
                "Vertical Roller Mills",
                "Efficient Finish Grinding",
                "Separator Optimization",
                "Closed-Circuit Grinding",
            ],
        ),
        (
            "kiln_fuel_substitution",
            "Kiln Fuel Substitution",
            "Replacement of fossil kiln fuels with alternative or waste fuels.",
            [
                "Biomass Fuel",
                "Biogenic Waste Fuel",
                "Non-Biogenic Waste Fuel",
                "Refuse-Derived Fuel",
                "Waste Tires",
                "Alternative Liquid Fuel",
                "Alternative Solid Fuel",
            ],
        ),
        (
            "kiln_electrification",
            "Kiln Electrification",
            "Electrified heating pathways for calcination or clinkering.",
            [
                "Electric Resistance Heating",
                "Plasma Heating",
                "Electric Calcination",
                "Electrified Thermal Storage",
                "Indirect Electric Heating",
            ],
        ),
        (
            "solar_thermal_kiln_heating",
            "Solar Thermal Kiln Heating",
            "Concentrated solar thermal energy for kiln or calciner heating.",
            [
                "Concentrated Solar Thermal",
                "Solar Calcination",
                "Solar-Assisted Clinker Production",
            ],
        ),
        (
            "hydrogen_based_kiln_heating",
            "Hydrogen-Based Kiln Heating",
            "Hydrogen combustion or plasma as kiln thermal energy.",
            [
                "Hydrogen Combustion",
                "Hydrogen Plasma",
                "Green-Hydrogen Kiln Fuel",
            ],
        ),
        (
            "waste_heat_recovery",
            "Waste Heat Recovery",
            "Recovery of kiln or cooler heat for process or power uses.",
            [
                "Clinker Cooler Heat Recovery",
                "Kiln Exhaust Heat Recovery",
                "Raw Meal Preheating",
                "Steam Generation",
                "Electricity Cogeneration",
                "Organic Rankine Cycle",
            ],
        ),
        (
            "kiln_technology_upgrades",
            "Kiln Technology Upgrades",
            "Major kiln line technology upgrades (dry process, precalciner, etc.).",
            [
                "Dry-Process Kiln",
                "Precalciner",
                "Multistage Cyclone Preheater",
                "Modern Clinker Cooler",
                "Kiln Retrofit",
            ],
        ),
        (
            "kiln_thermal_efficiency_improvements",
            "Kiln Thermal-Efficiency Improvements",
            "Operational and refractory improvements reducing kiln heat loss.",
            [
                "Kiln Insulation",
                "Low-Thermal-Conductivity Refractory",
                "High-Performance Refractory",
                "Reduced Shell Heat Loss",
                "Burner Optimization",
                "Airflow Optimization",
                "Variable-Speed Exhaust Fans",
                "Temperature-Control Optimization",
            ],
        ),
        (
            "digital_and_ai_process_optimization",
            "Digital and AI Process Optimization",
            "Digital twins, MPC, and AI control for cement manufacturing.",
            [
                "AI-Driven Kiln Control",
                "AI-Driven Grinding Optimization",
                "Model-Predictive Control",
                "Digital Twin",
                "Real-Time Process Optimization",
                "Advanced Sensor Control",
                "Variable-Speed Process Control",
            ],
        ),
    ]
    s3_children = []
    for slug, display, definition, variants in s3_specs:
        negative = []
        if slug == "kiln_fuel_substitution":
            negative = [
                "biomass ash used as SCM",
                "biomass ash cement replacement",
                "pozzolanic biomass ash",
            ]
        s3_children.append(
            node(
                slug=slug,
                display=display,
                parent="cement_manufacturing_efficiency",
                level="sub_subcategory",
                definition=definition,
                inclusion=variants[:],
                exclusion=negative or ["Unrelated construction processes"],
                synonyms=[display.lower()] + [v.lower() for v in variants[:3]],
                variants=variants,
                domain="Cement Manufacturing Process",
                roles=["Manufacturing Process", "Kiln Fuel"]
                if slug == "kiln_fuel_substitution"
                else ["Manufacturing Process"],
                negative_cues=negative,
            )
        )
    subcats.append(
        {
            **node(
                slug="cement_manufacturing_efficiency",
                display="Cement Manufacturing Efficiency",
                parent=CATEGORY_SLUG,
                level="subcategory",
                definition="Process, fuel, and digital efficiency improvements in cement manufacturing.",
                inclusion=["grinding efficiency", "kiln fuel substitution", "WHR", "AI kiln control"],
                exclusion=["Carbon capture systems", "SCM materials", "biomass ash as SCM"],
                synonyms=["cement plant efficiency", "kiln efficiency"],
                variants=[],
                domain="Cement Manufacturing Process",
                roles=["Manufacturing Process", "Kiln Fuel"],
                negative_cues=["carbon capture", "SCM", "cement replacement"],
            ),
            "children": s3_children,
        }
    )

    # 4 Cement-Plant Carbon Capture
    s4_specs = [
        (
            "chemical_absorption",
            "Chemical Absorption",
            "Post-combustion solvent / chemical absorption CO2 capture at cement plants.",
            [
                "Aqueous Amine Solvent",
                "Non-Aqueous Solvent",
                "Advanced Amine Solvent",
                "Post-Combustion Solvent Capture",
            ],
            ["amine", "solvent-based capture", "chemical absorption", "MEA"],
        ),
        (
            "cryogenic_carbon_capture",
            "Cryogenic Carbon Capture",
            "Cryogenic separation or purification of CO2 from cement flue gas.",
            [
                "Pressure Swing Adsorption with Cryogenic Purification",
                "Cryogenic Separation",
                "Cryogenic Compression and Purification",
            ],
            ["cryogenic", "cryogenic carbon capture"],
        ),
        (
            "oxy_fuel_combustion",
            "Oxy-Fuel Combustion",
            "Oxygen-enriched or full oxy-fuel combustion for cement kilns.",
            [
                "Partial Oxy-Fuel",
                "Full Oxy-Fuel",
                "Pressurized Oxy-Fuel",
                "Oxygen-Enriched Combustion",
            ],
            ["oxy-fuel", "oxyfuel", "oxygen-enriched combustion"],
        ),
        (
            "membrane_separation",
            "Membrane Separation",
            "Membrane-based CO2 separation from cement flue gas.",
            [
                "Polymeric Membrane",
                "Inorganic Membrane",
                "Hybrid Membrane System",
                "Multi-Stage Membrane Separation",
            ],
            ["membrane separation", "CO2 membrane"],
        ),
        (
            "calcium_looping",
            "Calcium Looping",
            "CaO/CaCO3 looping carbon capture integrated with cement plants.",
            [
                "Tail-End Calcium Looping",
                "Integrated Calcium Looping",
                "Indirect Calcium Looping",
                "Solar-Assisted Calcium Looping",
            ],
            ["calcium looping", "Ca-looping", "CaL"],
        ),
        (
            "direct_separation",
            "Direct Separation",
            "Indirectly heated calciner / LEILAC-type direct separation of process CO2.",
            [
                "Indirectly Heated Calciner",
                "LEILAC-Type Direct Separation",
                "Electrically Heated Direct Separation",
            ],
            ["direct separation", "LEILAC"],
        ),
    ]
    s4_children = []
    for slug, display, definition, variants, synonyms in s4_specs:
        s4_children.append(
            node(
                slug=slug,
                display=display,
                parent="cement_plant_carbon_capture",
                level="sub_subcategory",
                definition=definition,
                inclusion=synonyms + variants,
                exclusion=["Mineralization as utilization only without capture framing", "DAC unrelated to cement plant"],
                synonyms=synonyms,
                variants=variants,
                domain="Carbon Capture Process",
                roles=["Carbon Capture System"],
            )
        )
    subcats.append(
        {
            **node(
                slug="cement_plant_carbon_capture",
                display="Cement-Plant Carbon Capture",
                parent=CATEGORY_SLUG,
                level="subcategory",
                definition="Point-source carbon capture technologies applied at cement plants.",
                inclusion=["amine capture", "oxy-fuel", "membrane", "Ca-looping", "LEILAC", "cryogenic"],
                exclusion=["CCUS utilization without capture", "DAC not at cement plant"],
                synonyms=["cement CCS", "cement plant carbon capture"],
                variants=[],
                domain="Carbon Capture Process",
                roles=["Carbon Capture System"],
            ),
            "children": s4_children,
        }
    )

    # 5 Alternative Cement Chemistries
    s5_specs = [
        (
            "calcium_silicate_cements",
            "Calcium Silicate Cements",
            "Non-Portland calcium silicate binder chemistries.",
            [
                "Electrochemical Calcium Silicate Cement",
                "Calcium Silicate Rock-Derived Cement",
                "Carbonatable Calcium Silicate Cement",
                "Low-Lime Calcium Silicate Cement",
                "Wollastonite-Based Cement",
                "Chemically Leached Calcium Silicate Cement",
            ],
        ),
        (
            "belite_and_calcium_sulfoaluminate_cements",
            "Belite and Calcium Sulfoaluminate Cements",
            "Belite-rich and CSA / BCSA alternative cement chemistries.",
            [
                "Belite Calcium Sulfoaluminate Cement",
                "BCSA Cement",
                "Calcium Sulfoaluminate Cement",
                "Belite-Rich Cement",
                "Belite Calcium Sulfoaluminate Ferrite Cement",
                "Ye'elimite-Rich Cement",
                "Waste-Derived BCSA Cement",
            ],
        ),
        (
            "reactive_magnesia_cements",
            "Reactive Magnesia Cements",
            "Reactive MgO and related magnesium binder systems.",
            [
                "Magnesite-Derived Reactive MgO Cement",
                "Magnesium Silicate-Derived MgO Cement",
                "Olivine-Derived MgO Cement",
                "Seawater-Derived MgO Cement",
                "Brine-Derived MgO Cement",
                "Industrial-Residue-Derived MgO Cement",
                "Carbonation-Cured MgO Cement",
                "Magnesium Oxychloride Cement",
                "Magnesium Oxysulfate Cement",
                "Magnesium Carbonate Cement",
            ],
        ),
        (
            "alkali_activated_cements",
            "Alkali-Activated Cements",
            "Alkali-activated and geopolymer binder systems.",
            [
                "Fly Ash-Based Alkali-Activated Cement",
                "Slag-Based Alkali-Activated Cement",
                "Fly Ash-Slag Alkali-Activated Cement",
                "Metakaolin-Based Alkali-Activated Cement",
                "Calcined-Clay Alkali-Activated Cement",
                "Mine-Tailings Alkali-Activated Cement",
                "Municipal-Ash Alkali-Activated Cement",
                "Hybrid Alkali-Activated Cement",
                "One-Part Alkali-Activated Cement",
                "Two-Part Alkali-Activated Cement",
                "Geopolymer Cement",
            ],
        ),
        (
            "biocements",
            "Biocements",
            "Biologically mediated carbonate or binder-producing cement systems.",
            [
                "Microbially Induced Calcium Carbonate Cement",
                "Enzyme-Induced Carbonate Cement",
                "Cyanobacteria-Based Cement",
                "Microalgae-Based Cement",
                "Bacteria-Grown Cement",
                "Biomineralized Cement",
                "Biologically Produced Binder",
            ],
        ),
        (
            "other_alternative_cement_chemistries",
            "Other Alternative Cement Chemistries",
            "Other non-Portland binders not covered above.",
            [
                "Calcium Aluminate Cement",
                "Calcium Aluminate-Sulfate Cement",
                "Phosphate Cement",
                "Sulfur Cement",
                "Carbonate Cement",
                "Synthetic Calcium Carbonate Cement",
                "Calcium Hydrosilicate Cement",
                "Other Non-Portland Binder",
            ],
        ),
    ]
    s5_children = []
    for slug, display, definition, variants in s5_specs:
        s5_children.append(
            node(
                slug=slug,
                display=display,
                parent="alternative_cement_chemistries",
                level="sub_subcategory",
                definition=definition,
                inclusion=variants[:],
                exclusion=["OPC-based systems", "SCM used only in Portland concrete"],
                synonyms=[display.lower()] + [v.lower() for v in variants[:3]],
                variants=variants,
                domain="Cement or Binder",
                roles=["Complete Binder"]
                + (["Activator"] if slug == "alkali_activated_cements" else []),
            )
        )
    subcats.append(
        {
            **node(
                slug="alternative_cement_chemistries",
                display="Alternative Cement Chemistries",
                parent=CATEGORY_SLUG,
                level="subcategory",
                definition="Non-Portland or substantially alternative binder chemistries.",
                inclusion=["alkali-activated", "CSA", "MgO cement", "biocement", "carbonatable calcium silicate"],
                exclusion=["OPC with SCM replacement only"],
                synonyms=["alternative cement", "non-Portland binder", "geopolymer"],
                variants=[],
                domain="Cement or Binder",
                roles=["Complete Binder"],
                negative_cues=["Portland cement replacement only", "SCM in OPC concrete"],
            ),
            "children": s5_children,
        }
    )

    # 6 Conventional SCMs
    s6_specs = [
        (
            "slag_cement",
            "Slag Cement",
            "Blast-furnace slag used as a conventional SCM.",
            [
                "Ground Granulated Blast-Furnace Slag",
                "GGBFS",
                "GGBS",
                "Granulated Blast-Furnace Slag",
                "Ground Granulated Blast-Furnace Slag Cement",
                "Pelletized Blast-Furnace Slag",
            ],
            ["GGBFS", "slag cement", "blast furnace slag"],
        ),
        (
            "coal_ash",
            "Coal Ash",
            "Coal combustion ashes used as conventional SCMs, including harvested ashes.",
            [
                "Coal Fly Ash",
                "Coal Bottom Ash",
                "Harvested Coal Ash",
                "Harvested Coal Fly Ash",
                "Harvested Coal Bottom Ash",
                "Ponded Coal Ash",
                "Landfilled Coal Ash",
                "Beneficiated Coal Ash",
                "Class F Coal Fly Ash",
                "Class C Coal Fly Ash",
                "High-Calcium Coal Fly Ash",
                "Low-Calcium Coal Fly Ash",
                "Off-Specification Coal Ash",
            ],
            ["fly ash", "coal ash", "bottom ash", "harvested ash"],
        ),
        (
            "silica_fume",
            "Silica Fume",
            "Silica fume / microsilica used as a conventional SCM.",
            [
                "Silica Fume",
                "Microsilica",
                "Condensed Silica Fume",
                "Undensified Silica Fume",
                "Densified Silica Fume",
                "Ferrosilicon Silica Fume",
                "Silicon-Metal Silica Fume",
            ],
            ["silica fume", "microsilica"],
        ),
        (
            "natural_pozzolans",
            "Natural Pozzolans",
            "Naturally occurring pozzolanic materials used as SCMs.",
            [
                "Volcanic Ash",
                "Pumice",
                "Pumicite",
                "Volcanic Tuff",
                "Scoria",
                "Perlite",
                "Diatomaceous Earth",
                "Opaline Shale",
                "Natural Silicate Pozzolan",
                "Basaltic Pozzolan",
                "Granite-Derived Pozzolan",
            ],
            ["natural pozzolan", "volcanic ash", "pumice"],
        ),
        (
            "glass_pozzolans",
            "Glass Pozzolans",
            "Ground glass used as a pozzolanic SCM.",
            [
                "Ground Glass Pozzolan",
                "Post-Consumer Glass Pozzolan",
                "Industrial Waste Glass Pozzolan",
                "Container Glass Pozzolan",
                "Flat Glass Pozzolan",
                "Mixed Waste Glass Pozzolan",
                "Glass Fiber Waste Pozzolan",
            ],
            ["ground glass pozzolan", "waste glass SCM"],
        ),
        (
            "calcined_clays",
            "Calcined Clays",
            "Calcined clays used directly as SCMs (not factory LC3 product).",
            [
                "Calcined Kaolinitic Clay",
                "Metakaolin",
                "Flash-Calcined Clay",
                "Calcined Illitic Clay",
                "Calcined Montmorillonitic Clay",
                "Calcined Shale",
                "Low-Grade Calcined Clay",
            ],
            ["metakaolin", "calcined clay", "calcined kaolin"],
        ),
    ]
    s6_children = []
    for slug, display, definition, variants, synonyms in s6_specs:
        s6_children.append(
            node(
                slug=slug,
                display=display,
                parent="conventional_supplementary_cementitious_materials",
                level="sub_subcategory",
                definition=definition,
                inclusion=["cement replacement", "SCM", "pozzolanic addition"],
                exclusion=["aggregate-only use", "alkali-activated precursor as complete binder"],
                synonyms=synonyms,
                variants=variants,
                domain="Supplementary Cementitious Material",
                roles=["Cement Replacement", "Pozzolanic SCM", "Hydraulic SCM", "Latent Hydraulic SCM", "Clinker Replacement"],
                negative_cues=["aggregate", "road base", "alkali-activated cement"],
            )
        )
    subcats.append(
        {
            **node(
                slug="conventional_supplementary_cementitious_materials",
                display="Conventional Supplementary Cementitious Materials",
                parent=CATEGORY_SLUG,
                level="subcategory",
                definition="Established SCMs used as cement or clinker replacements in Portland systems.",
                inclusion=["slag", "coal ash", "silica fume", "natural pozzolan", "glass pozzolan", "calcined clay as SCM"],
                exclusion=["Factory LC3 product", "alkali-activated binders", "aggregate-only applications"],
                synonyms=["SCM", "supplementary cementitious material", "pozzolan"],
                variants=[],
                domain="Supplementary Cementitious Material",
                roles=["Cement Replacement", "Pozzolanic SCM", "Hydraulic SCM", "Latent Hydraulic SCM"],
                negative_cues=["aggregate only", "geopolymer binder", "LC3 factory cement"],
            ),
            "children": s6_children,
        }
    )

    # 7 Emerging SCMs
    s7_specs = [
        (
            "biomass_ashes",
            "Biomass Ashes",
            "Ashes from biomass combustion used as SCMs.",
            [
                "Rice Husk Ash",
                "Sugarcane Bagasse Ash",
                "Palm Oil Fuel Ash",
                "Wood Ash",
                "Wood Fly Ash",
                "Wood Bottom Ash",
                "Corn Cob Ash",
                "Corn Stover Ash",
                "Wheat Straw Ash",
                "Bamboo Ash",
                "Sawdust Ash",
                "Paper-Mill Biomass Ash",
                "Mixed Biomass Ash",
                "Agricultural Residue Ash",
                "Biomass Power-Plant Ash",
                "Vitrified Biomass Ash",
            ],
            [
                "rice husk ash",
                "bagasse ash",
                "palm oil fuel ash",
                "wood ash",
                "agricultural residue ash",
                "biomass ash cement replacement",
            ],
            [
                "biomass as kiln fuel",
                "biomass ash used only as aggregate",
                "biomass ash soil amendment",
                "biomass ash disposal without cementitious use",
            ],
        ),
        (
            "waste_incineration_ashes",
            "Waste-Incineration Ashes",
            "Incineration ashes used as SCMs.",
            [
                "Municipal Solid-Waste Incineration Fly Ash",
                "Municipal Solid-Waste Incineration Bottom Ash",
                "Industrial Solid-Waste Incineration Ash",
                "Hazardous-Waste Incineration Ash",
                "Waste-to-Energy Ash",
                "Sewage-Sludge Ash",
                "Paper-Sludge Ash",
            ],
            ["MSWI ash", "sewage sludge ash", "waste-to-energy ash"],
            ["ash used only as aggregate", "landfill cover only"],
        ),
        (
            "mine_tailings",
            "Mine Tailings",
            "Mine tailings used as SCMs after optional activation.",
            [
                "Copper Mine Tailings",
                "Gold Mine Tailings",
                "Iron Ore Tailings",
                "Zinc Mine Tailings",
                "Lead Mine Tailings",
                "Diamond Mine Tailings",
                "Bauxite Tailings",
                "Phosphate Tailings",
                "Tungsten Tailings",
                "Molybdenum Tailings",
                "Nickel Tailings",
                "Lithium Mine Tailings",
                "Oil-Sands Tailings",
                "Mixed Mine Tailings",
                "Beneficiated Mine Tailings",
                "Mechanically Activated Mine Tailings",
                "Thermally Activated Mine Tailings",
                "Carbonated Mine Tailings",
            ],
            ["mine tailings SCM", "tailings cement replacement"],
            ["tailings as aggregate only", "mine backfill only"],
        ),
        (
            "carbonated_waste_derived_scms",
            "Carbonated Waste-Derived SCMs",
            "Waste materials carbonated and then used as SCMs.",
            [
                "Carbonated Fly Ash",
                "Carbonated Slag",
                "Carbonated Cement Kiln Dust",
                "Carbonated Aggregate Fines",
                "Carbonated Mine Tailings",
                "Carbonated Lime Mud",
                "Carbonated Recycled Concrete Fines",
                "Carbonated Electric Arc Furnace Slag",
                "Carbonated Clay",
                "Multi-Feedstock Carbonated SCM",
            ],
            ["carbonated slag SCM", "carbonated fly ash cement replacement"],
            ["carbonation curing of concrete only", "CO2 storage without SCM use"],
        ),
        (
            "synthetic_calcium_carbonates",
            "Synthetic Calcium Carbonates",
            "Synthetic CaCO3 materials used as reactive cementitious additions/SCMs.",
            [
                "Vaterite",
                "Synthetic Calcite",
                "Synthetic Aragonite",
                "Precipitated Calcium Carbonate",
                "Flue-Gas-Derived Calcium Carbonate",
                "Waste-Derived Synthetic Calcium Carbonate",
                "Carbon-Negative Calcium Carbonate",
            ],
            ["synthetic calcium carbonate SCM", "vaterite cement"],
            ["inert limestone filler only", "aggregate only"],
        ),
        (
            "recycled_cementitious_materials",
            "Recycled Cementitious Materials",
            "Recycled cement paste/powder used directly as SCMs.",
            [
                "Recycled Cement Paste",
                "Recycled Cement Powder",
                "Recovered Cement Fines",
                "Recycled Concrete Powder",
                "Construction-and-Demolition Cement Fines",
                "Thermally Activated Recycled Cement Paste",
                "Mechanically Activated Recycled Cement Paste",
                "Carbonated Recycled Cement Paste",
            ],
            ["recycled cement paste SCM", "recovered cement fines"],
            ["reclinkered as feedstock", "recycled aggregate only"],
        ),
        (
            "other_industrial_waste_derived_scms",
            "Other Industrial Waste-Derived SCMs",
            "Other industrial wastes used as binder replacements or SCMs.",
            [
                "Red Mud",
                "Bauxite Residue",
                "Cement Kiln Dust",
                "Carbide Sludge",
                "Lime Mud",
                "Phosphogypsum",
                "Steel Slag Powder",
                "Electric Arc Furnace Slag Powder",
                "Basic Oxygen Furnace Slag Powder",
                "Copper Slag Powder",
                "Ceramic Waste Powder",
                "Brick Powder",
                "Tile Waste Powder",
                "Marble Sludge",
                "Granite Sludge",
                "Quarry Fines",
                "Dredged Sediment",
            ],
            ["red mud SCM", "steel slag powder cement replacement", "CKD as SCM"],
            ["aggregate only", "road base only", "alkali-activated complete binder"],
        ),
    ]
    s7_children = []
    for slug, display, definition, variants, synonyms, negatives in s7_specs:
        s7_children.append(
            node(
                slug=slug,
                display=display,
                parent="emerging_supplementary_cementitious_materials",
                level="sub_subcategory",
                definition=definition,
                inclusion=["binder replacement", "SCM", "reactive cementitious addition"],
                exclusion=["aggregate only", "soil amendment", "road base", "unrelated construction material"],
                synonyms=synonyms,
                variants=variants,
                domain="Supplementary Cementitious Material",
                roles=["Cement Replacement", "Pozzolanic SCM", "Hydraulic SCM", "Clinker Replacement"],
                positive_cues=synonyms,
                negative_cues=negatives,
                retrieval_terms=synonyms + [v.lower() for v in variants[:5]],
            )
        )
    subcats.append(
        {
            **node(
                slug="emerging_supplementary_cementitious_materials",
                display="Emerging Supplementary Cementitious Materials",
                parent=CATEGORY_SLUG,
                level="subcategory",
                definition="Emerging wastes and processed materials used as SCMs or binder replacements.",
                inclusion=["biomass ash SCM", "mine tailings SCM", "carbonated waste SCM", "recycled cement paste SCM"],
                exclusion=["aggregate-only", "kiln fuel biomass", "clinker feedstock use"],
                synonyms=["emerging SCM", "alternative SCM", "waste-derived SCM"],
                variants=[],
                domain="Supplementary Cementitious Material",
                roles=["Cement Replacement", "Pozzolanic SCM"],
                negative_cues=["kiln fuel", "aggregate only", "soil amendment"],
            ),
            "children": s7_children,
        }
    )

    # 8 Multi-Material Blends
    s8_specs = [
        (
            "binary_cementitious_blends",
            "Binary Cementitious Blends",
            "Two-component cementitious binder systems.",
            [
                "Portland Cement–Fly Ash",
                "Portland Cement–Slag",
                "Portland Cement–Silica Fume",
                "Portland Cement–Calcined Clay",
                "Portland Cement–Glass Pozzolan",
            ],
        ),
        (
            "ternary_cementitious_blends",
            "Ternary Cementitious Blends",
            "Three-component cementitious binder systems.",
            [
                "Portland Cement–Fly Ash–Slag",
                "Portland Cement–Fly Ash–Silica Fume",
                "Portland Cement–Slag–Silica Fume",
                "Portland Cement–Limestone–Calcined Clay",
                "Portland Cement–Natural Pozzolan–Limestone",
                "Portland Cement–Glass Pozzolan–Slag",
                "Portland Cement–Synthetic Calcium Carbonate–SCM",
            ],
        ),
        (
            "quaternary_cementitious_blends",
            "Quaternary Cementitious Blends",
            "Four-or-more component cementitious blends emphasized as multi-SCM systems.",
            ["Four-Component Cementitious Blend", "Multi-SCM Blend"],
        ),
        (
            "high_scm_binder_systems",
            "High-SCM Binder Systems",
            "High-volume SCM binder systems with substantial clinker reduction.",
            [
                "High-Volume Fly Ash Concrete",
                "High-Volume Slag Concrete",
                "High-Volume SCM Concrete",
                "Clinker-Reduced Multi-SCM Binder",
            ],
        ),
        (
            "hybrid_binder_systems",
            "Hybrid Binder Systems",
            "Hybrids combining Portland and alternative chemistries or hydraulic–carbonating systems.",
            [
                "Portland Cement–Alkali-Activated Hybrid",
                "Portland Cement–Geopolymer Hybrid",
                "Hydraulic–Carbonating Hybrid Binder",
                "Other Hybrid Binder",
            ],
        ),
    ]
    s8_children = []
    for slug, display, definition, variants in s8_specs:
        s8_children.append(
            node(
                slug=slug,
                display=display,
                parent="multi_material_cementitious_blends",
                level="sub_subcategory",
                definition=definition,
                inclusion=variants[:],
                exclusion=["Single-material SCM studies without blend focus", "Factory LC3 as sole focus"],
                synonyms=[display.lower()],
                variants=variants,
                domain="Multi-Material Binder System",
                roles=["Multi-Component Binder"],
            )
        )
    subcats.append(
        {
            **node(
                slug="multi_material_cementitious_blends",
                display="Multi-Material Cementitious Blends",
                parent=CATEGORY_SLUG,
                level="subcategory",
                definition="Multi-component binder systems combining Portland cement and SCMs or hybrid chemistries.",
                inclusion=["binary/ternary/quaternary blends", "HVFA", "hybrid binders"],
                exclusion=["Single SCM replacement studies without multi-material framing"],
                synonyms=["ternary blend", "binary blend", "hybrid binder"],
                variants=[],
                domain="Multi-Material Binder System",
                roles=["Multi-Component Binder"],
            ),
            "children": s8_children,
        }
    )

    # 9 Inert and Low-Reactivity Fillers
    s9_specs = [
        (
            "carbonaceous_fillers",
            "Carbonaceous Fillers",
            "Carbon-rich fillers used primarily for packing or inert filling.",
            [
                "Biochar",
                "Wood-Derived Biochar",
                "Agricultural-Residue Biochar",
                "Sewage-Sludge Biochar",
                "Bamboo Biochar",
                "Rice Husk Biochar",
                "Carbon Black",
                "Graphitic Carbon Filler",
            ],
        ),
        (
            "carbonate_fillers",
            "Carbonate Fillers",
            "Carbonate mineral fillers used primarily as inert or low-reactivity fillers.",
            [
                "Limestone",
                "Ground Limestone",
                "Dolomite",
                "Ground Dolomite",
                "Marble Powder",
                "Chalk",
                "Calcite",
                "Aragonite",
                "Vaterite",
                "Precipitated Calcium Carbonate",
            ],
        ),
        (
            "siliceous_fillers",
            "Siliceous Fillers",
            "Crystalline siliceous fillers with low pozzolanic reactivity framing.",
            [
                "Quartz Powder",
                "Silica Flour",
                "Ground Sand",
                "Crystalline Silica Filler",
                "Quartz Fines",
            ],
        ),
        (
            "rock_and_quarry_fillers",
            "Rock and Quarry Fillers",
            "Quarry and crushed-rock mineral fillers.",
            [
                "Granite Powder",
                "Basalt Powder",
                "Quarry Dust",
                "Stone Dust",
                "Crusher Fines",
                "Andesite Powder",
                "Sandstone Powder",
            ],
        ),
        (
            "industrial_mineral_fillers",
            "Industrial Mineral Fillers",
            "Industrial minerals used primarily as fillers.",
            [
                "Talc",
                "Kaolin",
                "Uncalcined Clay",
                "Bentonite",
                "Wollastonite",
                "Perlite",
                "Diatomite",
            ],
        ),
        (
            "recycled_mineral_fillers",
            "Recycled Mineral Fillers",
            "Recycled mineral powders used primarily as fillers.",
            [
                "Recycled Concrete Fines",
                "Recycled Glass Fines",
                "Ceramic Powder",
                "Brick Powder",
                "Tile Powder",
                "Construction-and-Demolition Fines",
            ],
        ),
        (
            "engineered_ultrafine_fillers",
            "Engineered Ultrafine Fillers",
            "Engineered ultrafine fillers for particle packing.",
            [
                "Ultrafine Limestone",
                "Nanocalcium Carbonate",
                "Nanosilica Used Primarily as Filler",
                "Engineered Particle-Packing Filler",
                "Hybrid Mineral Filler",
            ],
        ),
    ]
    s9_children = []
    for slug, display, definition, variants in s9_specs:
        s9_children.append(
            node(
                slug=slug,
                display=display,
                parent="inert_and_low_reactivity_fillers",
                level="sub_subcategory",
                definition=definition,
                inclusion=["filler", "inert addition", "particle packing"],
                exclusion=["Reactive SCM framing", "complete binder"],
                synonyms=[display.lower()] + [v.lower() for v in variants[:3]],
                variants=variants,
                domain="Filler",
                roles=["Filler"],
                negative_cues=["pozzolanic SCM", "cement replacement with reactivity focus"],
            )
        )
    subcats.append(
        {
            **node(
                slug="inert_and_low_reactivity_fillers",
                display="Inert and Low-Reactivity Fillers",
                parent=CATEGORY_SLUG,
                level="subcategory",
                definition="Inert or low-reactivity mineral and carbonaceous fillers in cementitious systems.",
                inclusion=["limestone filler", "biochar filler", "quarry dust filler"],
                exclusion=["Reactive SCM use", "clinker feedstock"],
                synonyms=["mineral filler", "inert filler"],
                variants=[],
                domain="Filler",
                roles=["Filler"],
                negative_cues=["pozzolanic activity", "SCM replacement"],
            ),
            "children": s9_children,
        }
    )

    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "schema_version": "cementitious-materials-schema-v1",
        "category": {
            "display_name": CATEGORY,
            "slug": CATEGORY_SLUG,
            "definition": (
                "Umbrella category for cementitious binders, SCMs, fillers, "
                "clinker feedstocks, cement manufacturing efficiency, and cement-plant carbon capture."
            ),
        },
        "controlled_vocabularies": {
            "technology_domain": [
                "Cement or Binder",
                "Supplementary Cementitious Material",
                "Filler",
                "Clinker Feedstock",
                "Cement Manufacturing Process",
                "Carbon Capture Process",
                "Multi-Material Binder System",
                "Uncertain",
            ],
            "functional_role": [
                "Complete Binder",
                "Clinker-Containing Cement",
                "Clinker Replacement",
                "Cement Replacement",
                "Pozzolanic SCM",
                "Hydraulic SCM",
                "Latent Hydraulic SCM",
                "Filler",
                "Activator",
                "Clinker Feedstock",
                "Kiln Fuel",
                "Manufacturing Process",
                "Carbon Capture System",
                "Multi-Component Binder",
                "Other",
                "Uncertain",
            ],
            "classification_basis": [
                "Explicit",
                "Strongly Inferred",
                "Weakly Inferred",
                "Unresolved",
            ],
            "confidence": ["High", "Medium", "Low"],
            "duplicate_status": [
                "Unique",
                "Exact Duplicate Removed",
                "Possible Duplicate",
                "Consolidated",
            ],
        },
        "subcategories": subcats,
    }


def main() -> None:
    payload = build()
    OUT_YAML.parent.mkdir(parents=True, exist_ok=True)
    if yaml is not None:
        OUT_YAML.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        print(f"Wrote {OUT_YAML}")
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    n_sub = len(payload["subcategories"])
    n_ss = sum(len(s["children"]) for s in payload["subcategories"])
    print(f"Subcategories: {n_sub}; sub-subcategories: {n_ss}")


if __name__ == "__main__":
    main()
