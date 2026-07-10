"""Prompt templates for machine-readable carbon capture extraction."""

from __future__ import annotations

import json

from pipeline.carbon_capture_schema import CANONICAL_FIELDS, NA

SYSTEM_PROMPT = """You are a research analyst specializing in cement and concrete decarbonization technologies.

Extract machine-readable structured data from the provided source(s) for the specified carbon capture methodology.

STRICT RULES:
1. Return valid JSON only — no markdown, no commentary, no code fences.
2. Use the canonical schema exactly.
3. Use "N.A." for every missing, unknown, or unavailable value.
4. Do not include prose in controlled vocabulary fields (confidence, deployment_stage, source_type, metric_dimension).
5. Put explanations only in notes.
6. deployment_stage must reflect the CURRENT stage only — not future projections.
7. confidence must be exactly one of: High, Medium, Low, N.A.
8. deployment_stage must be exactly one of: Laboratory, Pilot, Demonstration, Commercial, N.A.
9. source_type must be exactly one of: Literature, Web, N.A.
10. metric_dimension must be exactly one of: CO2 Reduction, Energy, Cost, Other, N.A.
11. Never invent numerical values. If a number is not explicitly stated, use N.A.
12. Numerical summary fields (co2_reduction, energy_impact, cost_impact) must be concise number + unit only when possible.
13. primary_barriers must be concise comma-separated phrases, not sentences.
14. Preserve metric name, value, unit, and boundary as separate fields — never combine them.
15. Each element of the records array must represent ONE project or ONE technology.
16. If multiple pilots, demonstrations, or commercial projects are mentioned, output one record per project.
17. If no specific project exists, output one technology record with project_name, project_year, and project_location set to N.A.
18. Do not output bare metrics without a parent project/technology record.
19. Extract company_or_organization, project_name, project_year, and project_location whenever deployments are referenced.
20. If multiple metrics belong to the same project/technology, include them in the metrics array on that record.
21. Use ONLY these exact field names (no short aliases like year, location, value, unit, boundary, source, title, url, cost):
    category, subcategory, technology_type, company_or_organization, project_name, project_year,
    project_location, deployment_stage, metric_dimension, metric_name, metric_value, metric_unit,
    metric_boundary, co2_reduction, energy_impact, cost_impact, primary_barriers, source_type,
    source_title, source_url_or_citation, confidence, notes
22. When reporting a metric, always populate metric_name, metric_value, and metric_unit separately.
    Example for cost: metric_dimension=Cost, metric_name=total investment, metric_value=260 million, metric_unit=RMB.
    Do NOT put "260 million RMB" only in metric_value or cost_impact without metric_name."""

RECORD_TEMPLATE = {
    field: NA for field in CANONICAL_FIELDS
}
RECORD_TEMPLATE["metrics"] = [
    {
        "metric_dimension": NA,
        "metric_name": NA,
        "metric_value": NA,
        "metric_unit": NA,
        "metric_boundary": NA,
    },
]


def _records_json_example() -> str:
    example = {
        "records": [
            {
                **{field: NA for field in CANONICAL_FIELDS},
                "technology_type": "oxyfuel combustion",
                "company_or_organization": "Heidelberg Materials",
                "project_name": "Brevik CCS",
                "project_year": "2024",
                "project_location": "Norway",
                "deployment_stage": "Demonstration",
                "co2_reduction": "N.A.",
                "energy_impact": "3.5 GJ/tCO2",
                "cost_impact": "N.A.",
                "metrics": [
                    {
                        "metric_dimension": "Cost",
                        "metric_name": "total investment",
                        "metric_value": "260 million",
                        "metric_unit": "RMB",
                        "metric_boundary": "cement plant",
                    },
                ],
            },
            {
                **{field: NA for field in CANONICAL_FIELDS},
                "technology_type": "partial oxy-fuel combustion",
                "company_or_organization": "N.A.",
                "project_name": "N.A.",
                "project_year": "2017",
                "project_location": "N.A.",
                "deployment_stage": "Laboratory",
                "metrics": [
                    {
                        "metric_dimension": "CO2 Reduction",
                        "metric_name": "CO2 capture rate",
                        "metric_value": "90",
                        "metric_unit": "%",
                        "metric_boundary": "capture unit",
                    },
                ],
            },
        ],
    }
    return json.dumps(example, indent=2, ensure_ascii=False)


def build_literature_extraction_prompt(
    *,
    methodology_name: str,
    methodology_subcategory: str,
    source_content: str,
) -> str:
    return f"""Extract structured carbon capture data from the following scientific literature source.

Methodology context:
- Methodology: {methodology_name}
- Subcategory: {methodology_subcategory}
- Category: Carbon Capture

Return a JSON object with a "records" array.
Each record = one project OR one technology (if no named project).

Required on every record (use exact field names):
category, subcategory, technology_type, company_or_organization, project_name, project_year,
project_location, deployment_stage, co2_reduction, energy_impact, cost_impact, primary_barriers,
source_type, source_title, source_url_or_citation, confidence, notes

Optional metrics array for additional metrics on the same project/technology:
metric_dimension, metric_name, metric_value, metric_unit, metric_boundary

Always populate metric_name when metric_value is present (e.g. total investment, CAPEX, energy penalty).

Set source_type to "Literature".
Set category to "Carbon Capture" and subcategory to the methodology subcategory.

SOURCE DOCUMENT:
{source_content}

Example shape (values are illustrative):
{_records_json_example()}

Return JSON only."""


def build_web_extraction_prompt(
    *,
    methodology_name: str,
    methodology_subcategory: str,
    source_content: str,
) -> str:
    return f"""Extract structured carbon capture data from the following web source.

Methodology context:
- Methodology: {methodology_name}
- Subcategory: {methodology_subcategory}
- Category: Carbon Capture

Return a JSON object with a "records" array.
Each record = one project OR one technology (if no named project).

Web sources often describe pilots, demonstrations, commercial deployments, companies, and project locations.
Extract project_name, company_or_organization, project_year, project_location, and deployment_stage when present.

Required on every record (use exact field names):
category, subcategory, technology_type, company_or_organization, project_name, project_year,
project_location, deployment_stage, co2_reduction, energy_impact, cost_impact, primary_barriers,
source_type, source_title, source_url_or_citation, confidence, notes

Optional metrics array for additional metrics on the same project/technology:
metric_dimension, metric_name, metric_value, metric_unit, metric_boundary

Always populate metric_name when metric_value is present (e.g. total investment, CAPEX, energy penalty).

Set source_type to "Web".

WEB SOURCE:
{source_content}

Example shape (values are illustrative):
{_records_json_example()}

Return JSON only."""
