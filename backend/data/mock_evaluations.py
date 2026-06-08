"""Mock TechnologyEvaluation profiles for local development.

# TODO: Replace mock generation with real pipeline integrations:
# - Tavily internet search (search.py / retrieve_internet_sources)
# - Edison scientific literature retrieval (edison.py / retrieve_edison_papers)
# - OpenAI structured extraction (llm.py / extract_technology_info)
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from schemas.technology_evaluation import TechnologyEvaluation

KNOWN_PROFILE_KEYS = {
    "carboncure": "CarbonCure",
    "sublimesystems": "Sublime Systems",
    "brimstone": "Brimstone",
    "fortera": "Fortera",
    "carbonbuilt": "CarbonBuilt",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _normalize_display_name(name: str) -> str:
    cleaned = name.strip()
    key = _normalize_key(cleaned)
    return KNOWN_PROFILE_KEYS.get(key, cleaned.title())


def _base_evaluation(
    user_input: str,
    *,
    technology_name: str,
    category: list[str],
    developers: list[str],
    deployment_stage: str,
    trl: str | None,
    short_description: str,
    how_it_works: str,
    replaces_or_improves: str,
    performance_metrics: list[str],
    key_inputs: list[str],
    key_outputs: list[str],
    technical_limitations: list[str],
    ghg_reduction: str | None,
    emissions_intensity: str | None,
    lifecycle_stages: list[str],
    environmental_benefits: list[str],
    environmental_tradeoffs: list[str],
    cost_impact: str | None,
    cost_drivers: list[str],
    commercialization_status: str,
    target_customers: list[str],
    adoption_barriers: list[str],
    sources: list[dict],
    confidence_level: str,
    missing_information: list[str],
    assumptions: list[str],
) -> TechnologyEvaluation:
    timestamp = _now_iso()
    normalized = _normalize_display_name(user_input)

    return TechnologyEvaluation.model_validate(
        {
            "id": f"eval_{uuid.uuid4().hex[:12]}",
            "query": {
                "user_input": user_input,
                "normalized_technology_name": normalized,
            },
            "technology_overview": {
                "technology_name": technology_name,
                "category": category,
                "developers": developers,
                "deployment_stage": deployment_stage,
                "trl": trl,
                "short_description": short_description,
            },
            "technical_performance": {
                "how_it_works": how_it_works,
                "replaces_or_improves": replaces_or_improves,
                "performance_metrics_improved": performance_metrics,
                "key_inputs": key_inputs,
                "key_outputs": key_outputs,
                "technical_limitations": technical_limitations,
            },
            "environmental_performance": {
                "reported_ghg_reduction_percent": ghg_reduction,
                "absolute_emissions_intensity": emissions_intensity,
                "lifecycle_stage_affected": lifecycle_stages,
                "environmental_benefits": environmental_benefits,
                "environmental_tradeoffs": environmental_tradeoffs,
            },
            "cost_and_market": {
                "reported_cost_impact": cost_impact,
                "cost_drivers": cost_drivers,
                "commercialization_status": commercialization_status,
                "target_customers": target_customers,
                "adoption_barriers": adoption_barriers,
            },
            "evidence": {
                "sources": sources,
                "confidence_level": confidence_level,
                "missing_information": missing_information,
                "assumptions": assumptions,
            },
            "metadata": {
                "created_at": timestamp,
                "updated_at": timestamp,
                "generated_by": "mock",
            },
        }
    )


def _carboncure(user_input: str) -> TechnologyEvaluation:
    return _base_evaluation(
        user_input,
        technology_name="CarbonCure",
        category=["Carbon Capture"],
        developers=["CarbonCure Technologies"],
        deployment_stage="Commercial",
        trl="9",
        short_description=(
            "CarbonCure injects captured CO₂ into fresh concrete during mixing, "
            "mineralizing the CO₂ into calcium carbonate and improving compressive strength."
        ),
        how_it_works=(
            "Recycled CO₂ is injected into concrete during batching, where it reacts "
            "with calcium ions to form nano-scale calcium carbonate. This permanently "
            "stores CO₂ and can reduce cement content while maintaining performance."
        ),
        replaces_or_improves="Supplements conventional ready-mix concrete production and reduces cement demand.",
        performance_metrics=["CO₂ reduction", "Strength improvement", "Resource efficiency"],
        key_inputs=["Captured CO₂", "Fresh concrete mix", "Batch plant integration hardware"],
        key_outputs=["Lower-carbon concrete", "Mineralized CO₂ in hardened concrete"],
        technical_limitations=[
            "Requires batch plant retrofit",
            "Benefits vary by mix design and regional supply chains",
            "CO₂ supply logistics can constrain deployment",
        ],
        ghg_reduction="5–8% per cubic yard of concrete (company-reported range)",
        emissions_intensity="Varies by mix; reductions reported relative to conventional mixes",
        lifecycle_stages=["Mix production", "Use phase"],
        environmental_benefits=[
            "Permanent CO₂ mineralization in concrete",
            "Potential cement reduction per mix",
            "Compatible with existing ready-mix workflows",
        ],
        environmental_tradeoffs=[
            "Upstream CO₂ capture and transport emissions",
            "Benefit depends on electricity/grid mix for capture",
        ],
        cost_impact="Low incremental cost at commercial scale; retrofit capex for plants",
        cost_drivers=["CO₂ supply contracts", "Plant retrofit", "Quality control and testing"],
        commercialization_status="Commercial deployments across North America and internationally",
        target_customers=["Ready-mix producers", "Precast manufacturers", "Project owners with low-carbon specs"],
        adoption_barriers=[
            "Plant retrofit capital cost",
            "CO₂ supply availability",
            "Specification and procurement acceptance",
        ],
        sources=[
            {
                "title": "CarbonCure Technology Overview",
                "url": "https://www.carboncure.com/technology",
                "publisher": "CarbonCure",
                "year": 2024,
                "source_type": "Company website",
                "relevant_fields": ["technology_overview", "technical_performance"],
            },
            {
                "title": "NRMCA Low-Carbon Concrete Initiatives",
                "url": "https://www.nrmca.org/",
                "publisher": "NRMCA",
                "year": 2023,
                "source_type": "Industry report",
                "relevant_fields": ["environmental_performance", "cost_and_market"],
            },
        ],
        confidence_level="High",
        missing_information=[
            "Plant-level LCA results for all geographies",
            "Long-term durability studies across all exposure classes",
        ],
        assumptions=[
            "Reported reductions based on company and partner case studies",
            "Commercial status inferred from public deployment announcements",
        ],
    )


def _sublime_systems(user_input: str) -> TechnologyEvaluation:
    return _base_evaluation(
        user_input,
        technology_name="Sublime Systems",
        category=["Alternative Cementitious Material (ACM)"],
        developers=["Sublime Systems"],
        deployment_stage="Pilot",
        trl="6",
        short_description=(
            "Sublime produces a near-zero-carbon cement using electrochemical "
            "processing rather than traditional fossil-fueled kilns."
        ),
        how_it_works=(
            "An electrochemical process produces cementitious phases at ambient "
            "conditions, avoiding limestone calcination and high-temperature kiln emissions."
        ),
        replaces_or_improves="Replaces conventional Portland cement clinker in binder systems.",
        performance_metrics=["CO₂ reduction", "Energy reduction", "Other"],
        key_inputs=["Electrical power", "Raw mineral feedstocks", "Water"],
        key_outputs=["Low-carbon cementitious binder"],
        technical_limitations=[
            "Scale-up from pilot to commercial production",
            "Standards and code acceptance for novel binder chemistry",
            "Performance validation across diverse applications",
        ],
        ghg_reduction="Up to ~90% vs. conventional Portland cement (company-reported)",
        emissions_intensity="Near-zero binder intensity claimed at commercial scale",
        lifecycle_stages=["Binder production", "Concrete manufacturing"],
        environmental_benefits=[
            "Avoids calcination-related process emissions",
            "Potential to eliminate fossil thermal energy for clinker",
        ],
        environmental_tradeoffs=[
            "Electricity emissions depend on grid carbon intensity",
            "Supply chain impacts for novel feedstocks not fully disclosed",
        ],
        cost_impact="Expected premium during early commercial scale",
        cost_drivers=["Electrolysis equipment", "Electricity price", "Manufacturing scale"],
        commercialization_status="Pilot production with first commercial facility under development",
        target_customers=["Cement producers", "Concrete suppliers", "Developers with embodied carbon targets"],
        adoption_barriers=[
            "Building code and standards alignment",
            "Capital cost of first-of-a-kind plants",
            "Market acceptance of novel cement chemistry",
        ],
        sources=[
            {
                "title": "Sublime Systems Technology",
                "url": "https://www.sublime-systems.com/",
                "publisher": "Sublime Systems",
                "year": 2024,
                "source_type": "Company website",
                "relevant_fields": ["technology_overview", "environmental_performance"],
            }
        ],
        confidence_level="Medium",
        missing_information=[
            "Independent third-party LCA at commercial scale",
            "Published durability performance across exposure classes",
            "Final commercial OPEX and CAPEX",
        ],
        assumptions=["Pilot-stage data extrapolated to commercial claims"],
    )


def _brimstone(user_input: str) -> TechnologyEvaluation:
    return _base_evaluation(
        user_input,
        technology_name="Brimstone",
        category=["Alternative Cementitious Material (ACM)"],
        developers=["Brimstone Energy"],
        deployment_stage="Pilot",
        trl="5",
        short_description=(
            "Brimstone produces Portland-equivalent cement from calcium silicate rocks "
            "with a process designed to generate a carbon-negative footprint."
        ),
        how_it_works=(
            "The process uses calcium silicate feedstock and produces cement plus a "
            "magnesium compound byproduct that can be used for carbon storage."
        ),
        replaces_or_improves="Replaces conventional limestone-based Portland cement production.",
        performance_metrics=["CO₂ reduction", "Resource efficiency", "Other"],
        key_inputs=["Calcium silicate rock", "Energy", "Process chemicals"],
        key_outputs=["Portland-equivalent cement", "Carbon-storable byproducts"],
        technical_limitations=[
            "Feedstock availability and processing at scale",
            "Process chemistry optimization for cost and quality",
        ],
        ghg_reduction="Potentially carbon-negative at scale (company-reported)",
        emissions_intensity="Not publicly standardized across commercial plants",
        lifecycle_stages=["Binder production"],
        environmental_benefits=[
            "Avoids limestone calcination emissions",
            "Potential long-term carbon storage in byproducts",
        ],
        environmental_tradeoffs=[
            "Mining and processing impacts for silicate feedstock",
            "Energy requirements for novel process steps",
        ],
        cost_impact="Not available",
        cost_drivers=["Feedstock processing", "Novel reactor capex", "Byproduct handling"],
        commercialization_status="Pilot and engineering development",
        target_customers=["Cement producers", "Infrastructure developers"],
        adoption_barriers=[
            "Technology scale-up risk",
            "Limited public cost and performance data",
            "Regulatory acceptance for novel production route",
        ],
        sources=[
            {
                "title": "Brimstone Energy",
                "url": "https://www.brimstone.com/",
                "publisher": "Brimstone",
                "year": 2024,
                "source_type": "Company website",
                "relevant_fields": ["technology_overview"],
            }
        ],
        confidence_level="Medium",
        missing_information=["Commercial CAPEX/OPEX", "Independent LCA verification", "Durability test data"],
        assumptions=["Public company materials used for pilot-stage assessment"],
    )


def _fortera(user_input: str) -> TechnologyEvaluation:
    return _base_evaluation(
        user_input,
        technology_name="Fortera",
        category=["Alternative Cementitious Material (ACM)", "Carbon Capture"],
        developers=["Fortera Corporation"],
        deployment_stage="Demonstration",
        trl="7",
        short_description=(
            "Fortera captures CO₂ from cement plant flue gas and mineralizes it into "
            "a supplementary cementitious reactive material."
        ),
        how_it_works=(
            "CO₂ from kiln exhaust is absorbed and converted into a reactive mineral "
            "that can replace a portion of clinker in cement production."
        ),
        replaces_or_improves="Reduces clinker demand and captures CO₂ at integrated cement plants.",
        performance_metrics=["CO₂ reduction", "Resource efficiency", "Cost reduction"],
        key_inputs=["Cement kiln flue gas CO₂", "Calcium sources", "Process water"],
        key_outputs=["Reactive SCM-like material", "Reduced clinker factor cement"],
        technical_limitations=[
            "Integration complexity at existing plants",
            "Process yield and product consistency at scale",
        ],
        ghg_reduction="Significant plant-level reduction potential (project-specific)",
        emissions_intensity="Varies by integration design and clinker substitution rate",
        lifecycle_stages=["Clinker production", "Binder production"],
        environmental_benefits=[
            "On-site CO₂ utilization",
            "Lower clinker factor in final cement",
        ],
        environmental_tradeoffs=[
            "Additional process energy and materials",
            "Performance sensitivity to feed chemistry",
        ],
        cost_impact="Project-dependent; potential savings from reduced clinker use",
        cost_drivers=["Plant integration", "CO₂ capture equipment", "Product qualification testing"],
        commercialization_status="Demonstration projects at cement facilities",
        target_customers=["Integrated cement producers", "Low-carbon cement buyers"],
        adoption_barriers=[
            "Capital investment for plant integration",
            "Operational complexity",
            "Product standards and customer acceptance",
        ],
        sources=[
            {
                "title": "Fortera Technology",
                "url": "https://www.forteraglobal.com/",
                "publisher": "Fortera",
                "year": 2024,
                "source_type": "Company website",
                "relevant_fields": ["technical_performance", "environmental_performance"],
            }
        ],
        confidence_level="Medium",
        missing_information=["Standardized $/ton CO₂ abatement", "Multi-site commercial rollout data"],
        assumptions=["Demonstration-scale public disclosures"],
    )


def _carbonbuilt(user_input: str) -> TechnologyEvaluation:
    return _base_evaluation(
        user_input,
        technology_name="CarbonBuilt",
        category=["Carbon Capture", "Concrete Design"],
        developers=["CarbonBuilt (UCLA spinout)"],
        deployment_stage="Demonstration",
        trl="7",
        short_description=(
            "CarbonBuilt reformulates concrete mixes and uses CO₂ curing to produce "
            "lower-carbon blocks and precast products."
        ),
        how_it_works=(
            "A lower-cement mix design is cured with CO₂, mineralizing CO₂ into the "
            "hardened product and improving performance in block/precast applications."
        ),
        replaces_or_improves="Improves conventional concrete block and precast production with CO₂ curing.",
        performance_metrics=["CO₂ reduction", "Cost reduction", "Strength improvement"],
        key_inputs=["CO₂ for curing", "Alternative mix constituents", "Precast production line"],
        key_outputs=["Low-carbon concrete masonry units", "CO₂ mineralized products"],
        technical_limitations=[
            "Application-specific to block/precast formats",
            "Requires curing process modifications",
        ],
        ghg_reduction="10–30% embodied carbon reduction reported in demonstration projects",
        emissions_intensity="Reported per product type; not standardized industry-wide",
        lifecycle_stages=["Precast production", "Use phase"],
        environmental_benefits=[
            "CO₂ utilization in cured products",
            "Lower cement content formulations",
        ],
        environmental_tradeoffs=[
            "CO₂ supply chain impacts",
            "Limited applicability outside block/precast",
        ],
        cost_impact="Potential cost parity with conventional products at scale",
        cost_drivers=["CO₂ supply", "Production line retrofit", "Mix constituent sourcing"],
        commercialization_status="Demonstration and early commercial partnerships",
        target_customers=["Concrete block producers", "Precast manufacturers"],
        adoption_barriers=[
            "Producer retrofit requirements",
            "Regional CO₂ availability",
            "Market education for specifiers",
        ],
        sources=[
            {
                "title": "CarbonBuilt Technology",
                "url": "https://www.carbonbuilt.com/",
                "publisher": "CarbonBuilt",
                "year": 2023,
                "source_type": "Company website",
                "relevant_fields": ["technology_overview", "technical_performance"],
            }
        ],
        confidence_level="Medium",
        missing_information=["Broad commercial deployment statistics", "Long-term durability across climates"],
        assumptions=["Demonstration project disclosures used for performance ranges"],
    )


def _generic(user_input: str) -> TechnologyEvaluation:
    name = _normalize_display_name(user_input)
    return _base_evaluation(
        user_input,
        technology_name=name,
        category=["Other"],
        developers=["Not available"],
        deployment_stage="Unknown",
        trl=None,
        short_description=(
            f"Mock evaluation profile for {name}. Replace with AI-generated output once "
            "OpenAI, Tavily, and Edison integrations are enabled."
        ),
        how_it_works="Not available",
        replaces_or_improves="Not available",
        performance_metrics=["Other"],
        key_inputs=[],
        key_outputs=[],
        technical_limitations=["Insufficient public data in mock mode"],
        ghg_reduction=None,
        emissions_intensity=None,
        lifecycle_stages=[],
        environmental_benefits=[],
        environmental_tradeoffs=[],
        cost_impact=None,
        cost_drivers=[],
        commercialization_status="Not available",
        target_customers=[],
        adoption_barriers=["Limited publicly available information"],
        sources=[],
        confidence_level="Low",
        missing_information=[
            "Detailed technical performance data",
            "Verified environmental performance metrics",
            "Commercial cost and deployment status",
        ],
        assumptions=[
            "Generic mock profile generated without external API calls",
            "Technology name normalized from user input only",
        ],
    )


_PROFILE_BUILDERS = {
    "carboncure": _carboncure,
    "sublimesystems": _sublime_systems,
    "brimstone": _brimstone,
    "fortera": _fortera,
    "carbonbuilt": _carbonbuilt,
}


def build_mock_evaluation(technology_name: str) -> TechnologyEvaluation:
    """Return a recognized mock profile or a generic mock evaluation."""
    key = _normalize_key(technology_name)
    builder = _PROFILE_BUILDERS.get(key)
    if builder:
        return builder(technology_name.strip())
    return _generic(technology_name.strip())
