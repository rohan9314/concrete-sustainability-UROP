#!/usr/bin/env python3
"""Author and emit config/concrete_decarbonization_taxonomy.json.

The nested Python tree below is the authoring form. The committed JSON file is
the machine-readable source of truth loaded at runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.cementitious.paths import taxonomy_slugify

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = REPO_ROOT / "config" / "concrete_decarbonization_taxonomy.json"

TAXONOMY_VERSION = "concrete-decarbonization-v1-2026-08-13"
SCHEMA_VERSION = "concrete-decarbonization-schema-v1"


def N(label: str, children: list | None = None, aliases: list[str] | None = None) -> dict:
    return {"label": label, "aliases": list(aliases or []), "children": list(children or [])}


def _cementitious() -> dict:
    return N(
        "Cementitious Materials",
        [
            N(
                "Conventional and Blended Cements",
                [
                    N(
                        "Ordinary Portland Cement",
                        [N("OPC"), N("ASTM C150 Portland Cement")],
                        aliases=["Portland cement", "ordinary Portland cement"],
                    ),
                    N(
                        "Reduced-Clinker and Blended Cements",
                        [
                            N(
                                "Portland-Limestone Cement (PLC / Type IL)",
                                aliases=["PLC", "Type IL", "Portland limestone cement"],
                            ),
                            N(
                                "Portland-Pozzolan Cement (Type IP)",
                                aliases=["Type IP", "PPC", "Portland pozzolan cement"],
                            ),
                            N(
                                "Portland Blast-Furnace Slag Cement (Type IS)",
                                aliases=["Type IS", "Portland slag cement"],
                            ),
                            N(
                                "Limestone Calcined Clay Cement (LC3)",
                                aliases=["LC3", "LC3 cement"],
                            ),
                            N("Other Blended Hydraulic Cements"),
                        ],
                    ),
                ],
            ),
            N(
                "Clinker Feedstock Decarbonization",
                [
                    N(
                        "Industrial-Waste Feedstocks",
                        [
                            N("Slag-Derived Feedstocks"),
                            N("Lignite Ash"),
                            N("Carbide Sludge"),
                            N("Aerated Concrete Meal"),
                            N("Lime Residues"),
                            N("Other Calcium-Rich Industrial Wastes"),
                        ],
                    ),
                    N(
                        "Recycled Cementitious Feedstocks",
                        [
                            N("Recovered Cement Paste"),
                            N("Recycled Cementitious Material for Reclinkering"),
                        ],
                    ),
                    N(
                        "Biogenic Calcium Feedstocks",
                        [
                            N("Microalgae-Derived Limestone"),
                            N("Algae-Grown Limestone"),
                        ],
                    ),
                    N(
                        "Composite-Waste Feedstocks",
                        [
                            N("Recycled Wind-Turbine Blades"),
                            N("Other Mineral-Rich Composite Waste"),
                        ],
                    ),
                    N(
                        "Alternative Mineral Feedstocks",
                        [
                            N("Non-Carbonate Calcium Feedstocks"),
                            N("Other Reduced-Calcination Mineral Sources"),
                        ],
                    ),
                ],
            ),
            N(
                "Cement Manufacturing Efficiency",
                [
                    N(
                        "Raw Meal Grinding and Clinker Milling",
                        [
                            N("High-Pressure Grinding Rolls"),
                            N("Vertical Roller Mills"),
                            N("AI-Driven Milling Optimization"),
                            N("Model-Based Process Control"),
                            N("Feed-Rate Optimization"),
                            N("Separator-Speed Optimization"),
                            N("Fan Optimization"),
                        ],
                    ),
                    N(
                        "Kiln Fuel Substitution",
                        [
                            N("Biomass Fuels"),
                            N("Biogenic Waste Fuels"),
                            N("Non-Biogenic Waste-Derived Fuels"),
                            N("Other Alternative Fuels"),
                        ],
                    ),
                    N(
                        "Electrification",
                        [
                            N("Electrified Kiln Heating"),
                            N("Electrified Thermal Systems"),
                        ],
                    ),
                    N(
                        "Solar Thermal",
                        [
                            N("Concentrated Solar Energy"),
                            N("Solar-Assisted Clinker Production"),
                        ],
                    ),
                    N(
                        "Hydrogen",
                        [
                            N("Hydrogen Combustion"),
                            N("Hydrogen-Based Thermal Plasma Systems"),
                        ],
                    ),
                    N(
                        "Waste Heat Recovery",
                        [
                            N("Clinker-Cooler Heat Recovery"),
                            N("Kiln-Exhaust Heat Recovery"),
                            N("Electricity Cogeneration"),
                            N("Raw-Meal Preheating"),
                        ],
                    ),
                    N(
                        "Kiln Technology Upgrades",
                        [
                            N("Modern Dry-Process Kilns"),
                            N("Precalciners"),
                            N("Multistage Cyclone Preheaters"),
                        ],
                    ),
                    N(
                        "Thermal Efficiency",
                        [
                            N("Kiln Insulation"),
                            N("High-Performance Refractories"),
                            N("Low-Conductivity Refractories"),
                            N("Heat-Loss Reduction"),
                        ],
                    ),
                    N(
                        "Digital and AI Process Optimization",
                        [
                            N("AI-Driven Process Control"),
                            N("Airflow Optimization"),
                            N("Burner Optimization"),
                            N("Variable-Speed Exhaust Fans"),
                            N("Temperature Optimization"),
                        ],
                    ),
                ],
            ),
            N(
                "Cement-Plant Carbon Capture",
                [
                    N(
                        "Chemical Absorption",
                        [
                            N("Amine Absorption", aliases=["amine", "MEA", "aqueous amine solvent"]),
                            N("Aqueous Solvent Capture"),
                            N("Non-Aqueous Solvent Capture"),
                            N("Other Solvent-Based Post-Combustion Capture"),
                        ],
                        aliases=["amine", "solvent-based capture", "chemical absorption", "MEA"],
                    ),
                    N(
                        "Cryogenic Carbon Capture",
                        [
                            N("Pressure-Swing and Cryogenic Purification"),
                            N("Cryogenic Separation Systems"),
                        ],
                        aliases=["cryogenic", "cryogenic carbon capture"],
                    ),
                    N(
                        "Oxy-Fuel Combustion",
                        [
                            N("Partial Oxy-Fuel"),
                            N("Full Oxy-Fuel"),
                            N("Pressurized Oxy-Fuel"),
                        ],
                        aliases=["oxy-fuel", "oxyfuel", "oxygen-enriched combustion"],
                    ),
                    N(
                        "Membrane Separation",
                        [
                            N("CO2-Selective Membranes"),
                            N("Modular Membrane Capture"),
                        ],
                        aliases=["membrane separation", "CO2 membrane"],
                    ),
                    N(
                        "Calcium Looping",
                        [
                            N("Tail-End Calcium Looping"),
                            N("Integrated Calcium Looping"),
                            N("CaO/CaCO3 Looping Systems"),
                        ],
                        aliases=["calcium looping", "Ca-looping", "CaL"],
                    ),
                    N(
                        "Direct Separation",
                        [
                            N("Indirect Limestone Heating"),
                            N("LEILAC-Type Direct Separation"),
                        ],
                        aliases=["direct separation", "LEILAC"],
                    ),
                ],
            ),
            N(
                "Alternative Cement Chemistries",
                [
                    N(
                        "Calcium Silicate Cements",
                        [
                            N("Electrochemical Calcium-Silicate Cement"),
                            N("Sublime-Type Electrochemical Cement"),
                            N("Calcium-Silicate-Rock Cement"),
                            N("Carbonatable Calcium-Silicate Clinker"),
                            N("Solidia-Type Carbonation Cement"),
                        ],
                    ),
                    N(
                        "Belite Calcium Sulfoaluminate Cements",
                        [
                            N("BCSA Cement"),
                            N("Lower-Temperature BCSA Clinker"),
                            N("Waste-Derived BCSA Feedstocks"),
                        ],
                        aliases=["belite and calcium sulfoaluminate cements", "CSA cement"],
                    ),
                    N(
                        "Reactive Magnesia Cements",
                        [
                            N("Olivine-Derived MgO"),
                            N("Magnesium-Silicate Feedstocks"),
                            N("Lithium-Extraction Magnesium Residues"),
                            N("Seawater-Derived Magnesium"),
                            N("Carbonation-Cured Reactive MgO"),
                        ],
                    ),
                    N(
                        "Alkali-Activated Cements",
                        [
                            N("Fly-Ash-Based Alkali Activation"),
                            N("Slag-Based Alkali Activation"),
                            N("Fly-Ash and Slag Systems"),
                            N("Metakaolin Systems"),
                            N("Sodium Hydroxide Activation"),
                            N("Potassium Hydroxide Activation"),
                            N("Sodium-Silicate Activation"),
                            N("Geopolymer Cement"),
                            N("Cold-Fusion Cement"),
                            N("Slag and Flash-Clay Systems"),
                        ],
                        aliases=["geopolymer", "alkali-activated binder"],
                    ),
                    N(
                        "Biocements",
                        [
                            N("Bacteria-Grown Cement"),
                            N("Microbially Induced Carbonate Cementation"),
                            N("Algae-Grown Cement"),
                            N("Cyanobacteria-Derived Binders"),
                        ],
                    ),
                    N(
                        "Other Alternative Cement Chemistries",
                        [N("Other Evidence-Supported Non-Portland Binder Chemistries")],
                    ),
                ],
            ),
            N(
                "Conventional Supplementary Cementitious Materials",
                [
                    N(
                        "Slag Cement",
                        [N("GGBFS"), N("Ground Granulated Blast-Furnace Slag")],
                        aliases=["GGBFS", "GGBS", "blast furnace slag"],
                    ),
                    N(
                        "Coal Ash",
                        [
                            N("Coal Fly Ash"),
                            N("Class F Fly Ash"),
                            N("Class C Fly Ash"),
                            N("Harvested Coal Ash"),
                            N("Ground Coal Bottom Ash"),
                        ],
                        aliases=["fly ash", "coal ash", "bottom ash"],
                    ),
                    N("Silica Fume", [N("Conventional Silica Fume")], aliases=["microsilica"]),
                    N(
                        "Natural Pozzolans",
                        [
                            N("Natural Pozzolans"),
                            N("Pumice"),
                            N("Other Naturally Reactive Geological Materials"),
                        ],
                        aliases=["natural pozzolan", "volcanic ash"],
                    ),
                    N(
                        "Glass Pozzolans",
                        [
                            N("Ground Waste Glass"),
                            N("Post-Consumer Glass Pozzolan"),
                            N("Industrial Glass Pozzolan"),
                        ],
                    ),
                    N(
                        "Calcined Clays",
                        [
                            N("Calcined Kaolinitic Clay"),
                            N("Metakaolin"),
                            N("Other Calcined Clay SCMs"),
                        ],
                    ),
                ],
            ),
            N(
                "Emerging Supplementary Cementitious Materials",
                [
                    N(
                        "Biomass Ashes",
                        [
                            N("Biomass Ash"),
                            N("Beneficiated Biomass Ash"),
                            N("Vitrified Biomass Ash"),
                            N("Rice-Husk Ash"),
                            N("Other Agricultural Ashes"),
                        ],
                    ),
                    N(
                        "Waste-Incineration Ashes",
                        [
                            N("Municipal Solid-Waste Incineration Ash"),
                            N("Industrial Solid-Waste Incineration Ash"),
                            N("MSWI Bottom Ash"),
                        ],
                    ),
                    N(
                        "Mine Tailings",
                        [
                            N("Copper Tailings"),
                            N("Gold Tailings"),
                            N("Zinc and Lead Tailings"),
                            N("Diamond-Mine Tailings"),
                            N("Oil-Sands Tailings"),
                            N("Other Beneficiated Mine Tailings"),
                        ],
                    ),
                    N(
                        "Carbonated Waste-Derived SCMs",
                        [
                            N("Carbonated Fly Ash"),
                            N("Carbonated Slag"),
                            N("Carbonated EAF Slag"),
                            N("Carbonated Cement-Kiln Dust"),
                            N("Carbonated Aggregate Fines"),
                            N("Carbonated Clay"),
                            N("Carbonated Lime Mud"),
                            N("Other Carbonated Industrial Waste"),
                        ],
                    ),
                    N(
                        "Synthetic Calcium Carbonates",
                        [
                            N("Synthetic Calcium Carbonate"),
                            N("Vaterite"),
                            N("CO2-Derived Reactive Calcium Carbonate"),
                        ],
                    ),
                    N(
                        "Recycled Cementitious Materials",
                        [
                            N("Recycled Cement Paste"),
                            N("Recycled Cement Powder"),
                            N("Recovered Concrete Fines"),
                            N("Recycled Cementitious Fines"),
                        ],
                    ),
                    N(
                        "Silicate-Derived SCMs",
                        [
                            N("Granite-Derived SCM"),
                            N("Basalt-Derived SCM"),
                            N("Sand-Derived SCM"),
                            N("Gravel-Derived SCM"),
                            N("Other Activated Silicate-Rock SCMs"),
                        ],
                    ),
                    N(
                        "Other Industrial Waste-Derived SCMs",
                        [N("Other Processed Industrial Residues with Demonstrated SCM Behavior")],
                    ),
                ],
            ),
            N(
                "Multi-Material Blends",
                [
                    N("Binary Blends", [N("Cement Plus One SCM")]),
                    N("Ternary Blends", [N("Cement Plus Two SCMs")]),
                    N("Quaternary Blends", [N("Cement Plus Three SCMs")]),
                    N("High-SCM Blends", [N("High-Replacement Cement Systems")]),
                    N(
                        "Hybrid Binder Systems",
                        [N("Mixed Hydraulic / Pozzolanic / Alternative Binder Systems")],
                    ),
                ],
                aliases=["Multi-Material Cementitious Blends"],
            ),
            N(
                "Inert and Low-Reactivity Fillers",
                [
                    N(
                        "Carbonaceous Fillers",
                        [N("Biochar"), N("Pyrolysis-Derived Carbon Fillers")],
                    ),
                    N("Carbonate Fillers", [N("Limestone"), N("Dolomite")]),
                    N("Siliceous Fillers", [N("Silica-Rich Inert Fillers")]),
                    N(
                        "Rock and Quarry Fillers",
                        [N("Quarry Fines"), N("Rock Powders"), N("Aggregate Fines")],
                    ),
                    N(
                        "Industrial Mineral Fillers",
                        [N("Mineral-Processing Fines"), N("Other Industrial Mineral Powders")],
                    ),
                    N(
                        "Recycled Mineral Fillers",
                        [N("Recycled Concrete Fines"), N("Recycled Mineral Powder")],
                    ),
                    N(
                        "Engineered Ultrafine Fillers",
                        [N("Engineered Particle-Packing Fillers"), N("Ultrafine Mineral Fillers")],
                    ),
                ],
            ),
        ],
    )


def _aggregate() -> dict:
    return N(
        "Aggregate Procurement",
        [
            N(
                "Carbonated Aggregates",
                [
                    N(
                        "Mineralized Synthetic Aggregates",
                        [
                            N("Synthetic Limestone Aggregate"),
                            N("Carbonated Demolished-Concrete Aggregate"),
                            N("Carbonated Slag Aggregate"),
                            N("Calcium-Rich Waste-Derived Carbonated Aggregate"),
                        ],
                    )
                ],
            ),
            N(
                "Pelletized Aggregates",
                [
                    N(
                        "Cold-Bonded Waste Aggregates",
                        [
                            N("Marble-Sludge Aggregate"),
                            N("Rice-Husk-Ash Aggregate"),
                            N("MSWI-Ash Aggregate"),
                            N("C&D-Waste Aggregate"),
                            N("Aggregate-Washing-Sludge Aggregate"),
                        ],
                    ),
                    N(
                        "Carbon-Negative Pelletized Aggregates",
                        [
                            N("Biochar-Rich Pelletized Aggregate"),
                            N("Other Carbon-Negative Artificial Aggregates"),
                        ],
                    ),
                ],
            ),
            N(
                "Recycled Concrete Aggregates",
                [
                    N("Untreated RCA", [N("Coarse RCA"), N("Fine RCA")]),
                    N(
                        "Treated RCA",
                        [N("Carbonated RCA"), N("Acid-Washed RCA"), N("Beneficiated RCA")],
                    ),
                ],
            ),
            N(
                "Dredged Aggregates",
                [
                    N(
                        "Beneficially Reused Dredged Material",
                        [N("Dredged Sand"), N("Dredged Gravel"), N("Processed Dredged Aggregate")],
                    )
                ],
            ),
            N(
                "By-Product Aggregates",
                [
                    N(
                        "Slag Aggregates",
                        [N("Air-Cooled Blast-Furnace Slag"), N("Copper Slag")],
                    ),
                    N(
                        "Mine-Tailing Aggregates",
                        [
                            N("Copper Tailings Aggregate"),
                            N("Iron-Ore Tailings Aggregate"),
                            N("Gold Tailings Aggregate"),
                        ],
                    ),
                ],
            ),
        ],
    )


def _concrete_design() -> dict:
    return N(
        "Concrete Design",
        [
            N(
                "Data-Driven Design Optimization",
                [
                    N(
                        "AI and Computational Mix Design",
                        [
                            N("Machine-Learning Property Prediction"),
                            N("AI-Driven Mixture Optimization"),
                            N("Stochastic Mix Optimization"),
                            N("Multi-Objective Low-Carbon Mix Optimization"),
                        ],
                    )
                ],
            ),
            N(
                "Design for Durability",
                [
                    N(
                        "SCM-Enabled Durability",
                        [
                            N("Fly-Ash Durability Enhancement"),
                            N("Slag Durability Enhancement"),
                            N("Silica-Fume Durability Enhancement"),
                        ],
                    ),
                    N(
                        "Self-Healing Concrete",
                        [
                            N("Bacterial Self-Healing Concrete"),
                            N("Crystalline Self-Healing Admixtures"),
                        ],
                    ),
                    N(
                        "Fiber-Reinforced Durable Concrete",
                        [
                            N("Ultra-High Performance Concrete"),
                            N("Engineered Cementitious Composites"),
                            N("Strain-Hardening Cementitious Composites"),
                        ],
                    ),
                ],
            ),
            N(
                "Design for Serviceability",
                [
                    N(
                        "Abrasion Resistance",
                        [
                            N("Hard-Aggregate Selection"),
                            N("Reduced Water-to-Cementitious Ratio"),
                            N("Silica Fume plus Nano-TiO2"),
                            N("Abrasion-Resistant Admixtures"),
                        ],
                    )
                ],
            ),
            N(
                "Design for Later-Age Strength",
                [
                    N(
                        "Delayed Strength Specification",
                        [
                            N("56-Day Strength Specification"),
                            N("90-Day Strength Specification"),
                            N("Other Later-Age Strength Specifications"),
                        ],
                    )
                ],
            ),
            N(
                "High-Filler Low-Water Concrete",
                [
                    N(
                        "Particle-Packing Optimization",
                        [
                            N("HFLW Concrete"),
                            N("Engineered Limestone Filler Systems"),
                            N("Engineered Dolomite Filler Systems"),
                            N("Low-Water Particle-Packed Mixtures"),
                        ],
                    )
                ],
            ),
            N(
                "Improved Thermal Envelope",
                [
                    N(
                        "Low-Thermal-Conductivity Concrete",
                        [N("Lightweight-Aggregate Concrete"), N("Insulating Structural Concrete")],
                    ),
                    N(
                        "Thermal Energy Storage",
                        [N("Phase-Change-Material Concrete"), N("Microencapsulated PCM Concrete")],
                    ),
                    N("Insulated Concrete Systems", [N("Insulated Concrete Forms")]),
                ],
            ),
            N(
                "Increased Albedo",
                [
                    N(
                        "High-Reflectance Concrete",
                        [
                            N("White Cement Surfaces"),
                            N("Slag-Lightened Concrete"),
                            N("Integral Pigments"),
                            N("Reflective Surface Finishing"),
                        ],
                    )
                ],
            ),
            N(
                "Reduced Pavement-Vehicle Interaction",
                [
                    N(
                        "Pavement Stiffness and Roughness Optimization",
                        [
                            N("High-Stiffness Concrete Pavement"),
                            N("Reduced Pavement Deflection"),
                            N("Reduced Pavement Roughness"),
                            N("PVI-Oriented Pavement Design"),
                        ],
                    )
                ],
            ),
        ],
    )


def _structural() -> dict:
    return N(
        "Structural and Construction Design",
        [
            N(
                "Efficient Concrete Use",
                [
                    N(
                        "Topology Optimization",
                        [
                            N("Topology-Optimized Frames"),
                            N("Topology-Optimized Floors"),
                            N("Material-Minimized Structural Layouts"),
                        ],
                    ),
                    N(
                        "Sizing Optimization",
                        [N("Member Sizing"), N("Cross-Section Optimization"), N("Rebar Optimization")],
                    ),
                    N(
                        "Structural-System Optimization",
                        [N("Post-Tensioned Systems"), N("Other Material-Efficient Structural Systems")],
                    ),
                ],
            ),
            N(
                "Deconstruction and Reuse",
                [
                    N(
                        "Reusable Concrete Components",
                        [
                            N("Reused Concrete Walls"),
                            N("Reused Floor Elements"),
                            N("Reused Foundations"),
                            N("Design for Disassembly"),
                            N("Component Salvage and Reassembly"),
                        ],
                    )
                ],
            ),
            N(
                "Improved Resilience",
                [
                    N(
                        "Hazard-Resilient Concrete Structures",
                        [
                            N("Hurricane Resilience"),
                            N("Flood Resilience"),
                            N("Fire Resilience"),
                            N("Other Hazard-Resilient Concrete Systems"),
                        ],
                    )
                ],
            ),
        ],
    )


def _operation() -> dict:
    return N(
        "Operation",
        [
            N(
                "Carbon Capture and Utilization of Fresh Concrete",
                [
                    N(
                        "CO2 Curing",
                        [
                            N("Carbonated Steel-Slag Concrete"),
                            N("Carbonated Lime Binder"),
                            N("Controlled Flue-Gas Curing"),
                        ],
                    ),
                    N(
                        "Direct CO2 Injection",
                        [
                            N("Ready-Mix CO2 Injection"),
                            N("Precast CO2 Injection"),
                            N("CarbonCure-Type Systems"),
                        ],
                    ),
                ],
            ),
            N(
                "Optimal Overdesign",
                [
                    N(
                        "Mix Overdesign Reduction",
                        [
                            N("Reduced Strength Overdesign"),
                            N("Improved Quality Control"),
                            N("Reduced Strength-Test Variability"),
                            N("Improved Batch Consistency"),
                        ],
                    )
                ],
            ),
            N(
                "Low-Carbon Transportation",
                [
                    N(
                        "Vehicle Electrification",
                        [
                            N("Battery-Electric Raw-Material Trucks"),
                            N("Electric Mixer Trucks"),
                        ],
                    ),
                    N(
                        "Alternative-Fuel Transportation",
                        [
                            N("Compressed Natural Gas Trucks"),
                            N("Renewable Natural Gas Trucks"),
                            N("Hydrogen Fuel-Cell Trucks"),
                            N("Green-Hydrogen Trucks"),
                        ],
                    ),
                ],
            ),
            N(
                "Minimal Returned Concrete",
                [
                    N(
                        "Demand and Production Matching",
                        [
                            N("BIM-Based Volume Estimation"),
                            N("Advanced Batching Systems"),
                            N("Mobile Volumetric Mixers"),
                            N("Returned-Concrete Reuse"),
                            N("Reduced Overordering"),
                            N("Reduced Overproduction"),
                        ],
                    )
                ],
            ),
        ],
    )


def _policy() -> dict:
    return N(
        "Policy",
        [
            N(
                "Performance-Based Specifications",
                [
                    N(
                        "Performance-Oriented Concrete Requirements",
                        [
                            N("Strength Performance Specifications"),
                            N("Durability Performance Specifications"),
                            N("Workability Performance Specifications"),
                            N("SCM Reactivity Performance Standards"),
                            N("Alkali-Activated Cement Performance Standards"),
                            N("Carbonating-Cement Performance Standards"),
                        ],
                    )
                ],
            ),
            N(
                "Tax Credits",
                [
                    N(
                        "Low-Carbon Production Incentives",
                        [
                            N("Federal Manufacturing Credits"),
                            N("Low-Carbon Cement Credits"),
                            N("Low-Carbon Concrete Credits"),
                            N("SCM Manufacturing Incentives"),
                            N("CCUS Incentives"),
                            N("State Low-Carbon Concrete Tax Incentives"),
                        ],
                    )
                ],
            ),
            N(
                "Environmental Product Declarations",
                [
                    N(
                        "Product Carbon Disclosure",
                        [
                            N("Cement EPDs"),
                            N("Concrete EPDs"),
                            N("SCM EPDs"),
                            N("Aggregate EPDs"),
                            N("Third-Party LCAs for Emerging Products"),
                        ],
                    )
                ],
            ),
            N(
                "Green Public Procurement",
                [
                    N(
                        "Embodied-Carbon Procurement Limits",
                        [
                            N("Buy Clean Programs"),
                            N("GWP Procurement Limits"),
                            N("Strength-Specific Carbon Limits"),
                            N("EPD-Based Procurement"),
                        ],
                    )
                ],
            ),
            N(
                "Carbon Budgeting",
                [
                    N(
                        "Project and Structure Carbon Limits",
                        [
                            N("Project Carbon Budgets"),
                            N("Material Carbon Budgets"),
                            N("Concrete Carbon Budgets"),
                            N("ACI 323-Type Requirements"),
                        ],
                    )
                ],
            ),
        ],
    )


def _end_of_life() -> dict:
    return N(
        "End-of-Life",
        [
            N(
                "End-of-Life Carbonation",
                [
                    N(
                        "Enhanced Concrete Carbonation",
                        [
                            N("Demolition-Concrete Carbonation"),
                            N("Crushing-Enhanced Carbonation"),
                            N("Fine-Particle Carbonation"),
                            N("Extended Stockpiling for Carbonation"),
                            N("Optimized Particle-Size Exposure"),
                            N("Carbonation of Recycled Concrete Fractions"),
                        ],
                    )
                ],
            )
        ],
    )


def nested_tree() -> dict:
    return N(
        "Concrete Decarbonization",
        [
            _cementitious(),
            _aggregate(),
            _concrete_design(),
            _structural(),
            _operation(),
            _policy(),
            _end_of_life(),
        ],
    )


def flatten_tree(root: dict | None = None) -> dict[str, Any]:
    root = root or nested_tree()
    nodes: list[dict[str, Any]] = []

    def walk(raw: dict, level: int, parent_slugs: list[str], parent_labels: list[str]) -> str:
        label = str(raw["label"])
        slug = taxonomy_slugify(label)
        path_slugs = parent_slugs + [slug]
        path_labels = parent_labels + [label]
        child_slugs: list[str] = []
        for child in raw.get("children") or []:
            child_slugs.append(walk(child, level + 1, path_slugs, path_labels))
        if level == 4 and child_slugs:
            raise ValueError(f"Level-4 node must not have children: {label}")
        if level > 4:
            raise ValueError(f"Taxonomy deeper than Level 4: {path_labels}")
        node = {
            "label": label,
            "slug": slug,
            "level": level,
            "parent_slug": parent_slugs[-1] if parent_slugs else "",
            "parent_path": "/".join(parent_slugs),
            "path": "/".join(path_slugs),
            "path_slugs": path_slugs,
            "path_labels": path_labels,
            "aliases": list(raw.get("aliases") or []),
            "children_slugs": child_slugs,
            "child_count": len(child_slugs),
        }
        nodes.append(node)
        return slug

    walk(root, 0, [], [])
    by_path = {n["path"]: n for n in nodes}
    if len(by_path) != len(nodes):
        dupes = [n["path"] for n in nodes if sum(1 for x in nodes if x["path"] == n["path"]) > 1]
        raise ValueError(f"Duplicate canonical paths: {sorted(set(dupes))}")
    counts = {lvl: sum(1 for n in nodes if n["level"] == lvl) for lvl in range(5)}
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "schema_version": SCHEMA_VERSION,
        "root_label": root["label"],
        "root_slug": taxonomy_slugify(root["label"]),
        "level_counts": {str(k): v for k, v in counts.items()},
        "node_count": len(nodes),
        "nodes": nodes,
    }


def write_json(path: Path | None = None) -> Path:
    dest = path or OUT_JSON
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = flatten_tree()
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


if __name__ == "__main__":
    out = write_json()
    payload = json.loads(out.read_text(encoding="utf-8"))
    print(f"Wrote {out}")
    print("level_counts", payload["level_counts"])
    print("node_count", payload["node_count"])
