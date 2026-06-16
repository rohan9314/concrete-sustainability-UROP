"""Prompts for structured technology intelligence extraction."""

import json

from intelligence_constants import (
    CCS_SUBCATEGORIES,
    COMPANY_ROLES,
    CONFIDENCE_LEVELS,
    DEPLOYMENT_STAGES,
    MAIN_CATEGORIES,
    PROJECT_STAGES,
)

INTELLIGENCE_SYSTEM_PROMPT = f"""You are a structured data extraction analyst for cement and concrete decarbonization technologies.

Your task is to extract standardized technology intelligence from:
1. SCIENTIFIC PAPER sources (source_type: "scientific_paper") — local peer-reviewed corpus
2. INTERNET sources (source_type: "internet") — company sites, reports, EPDs, deployment announcements

STRICT RULES:
1. Return valid JSON only — no markdown, no commentary, no code fences.
2. Prefer numerical values and predefined categories over prose.
3. Do not return long paragraphs. Use notes/evidence_notes fields only for short supporting text.
4. If information is unavailable, use null for unknown numbers, [] for unknown lists, and "Not Reported" for unknown categorical fields.
5. Never invent or estimate numerical values. If a number is not explicitly stated, use null.
6. Do not hallucinate companies, projects, or URLs. Only include items supported by sources.
7. For deployment_stage, only use: {json.dumps(list(DEPLOYMENT_STAGES))}
8. For main_category, only use: {json.dumps(list(MAIN_CATEGORIES))}
9. For ccs_subcategory (when main_category is Carbon Capture), only use: {json.dumps(list(CCS_SUBCATEGORIES))}
10. For company role, only use: {json.dumps(list(COMPANY_ROLES))}
11. For project stage, only use: {json.dumps(list(PROJECT_STAGES))}
12. For confidence fields, only use: {json.dumps(list(CONFIDENCE_LEVELS))}
13. Identify companies developing or deploying the technology.
14. Search specifically for pilot and demonstration projects connected to the technology and companies.
15. Include citations in source/url fields and evidence_sources with relevant_fields listing extracted schema paths.
16. When internet and scientific sources disagree, note the conflict in warnings and lower confidence.

For Carbon Capture technologies, explicitly:
1. Identify the CCS technology type and classify ccs_subcategory.
2. Identify companies/organizations associated with the technology.
3. Extract pilot and demonstration projects linked to those companies and technologies.
4. Extract project details (location, scale, CO2 captured/reduced, partners, funding when reported).
"""


def build_intelligence_prompt(
    technology_name: str,
    source_content: str,
    *,
    internet_count: int = 0,
    paper_count: int = 0,
    main_category: str = "Not Reported",
    ccs_subcategory: str = "Not Reported",
    company_name: str = "",
    project_stage: str = "Not Reported",
) -> str:
    """Build the user prompt for structured intelligence extraction."""
    filter_lines = []
    if main_category != "Not Reported":
        filter_lines.append(f"- Expected main category hint: {main_category}")
    if ccs_subcategory != "Not Reported":
        filter_lines.append(f"- Expected CCS subcategory hint: {ccs_subcategory}")
    if company_name.strip():
        filter_lines.append(f"- Focus on company/organization: {company_name.strip()}")
    if project_stage != "Not Reported":
        filter_lines.append(f"- Focus on project stage: {project_stage}")

    filter_block = "\n".join(filter_lines) if filter_lines else "- No additional filters provided."

    return f"""Extract structured technology intelligence for: "{technology_name}"

You have {internet_count} internet source(s) and {paper_count} scientific paper source(s).

Search filters / hints:
{filter_block}

Populate metrics whenever numerical values are explicitly reported, including when available:
- Reported GHG reduction percentage
- Absolute emissions intensity (with units)
- CO2 captured (with units)
- Capture rate percentage
- Energy reduction percentage
- Cost reduction percentage
- Cost per tonne CO2 avoided/captured
- Strength impact percentage or MPa
- Durability impact
- Other quantitative metrics

SOURCE DOCUMENTS:
{source_content}

Return a single JSON object with this exact top-level shape:
{{
  "technology_overview": {{
    "technology_name": "",
    "main_category": "",
    "subcategory": "",
    "ccs_subcategory": "",
    "deployment_stage": "",
    "trl": null,
    "organizations": [],
    "deployment_partners": [],
    "geography": [],
    "source_confidence": ""
  }},
  "metrics": [
    {{
      "metric_name": "",
      "value": null,
      "unit": "",
      "normalized_value": null,
      "normalized_unit": "",
      "source": "",
      "confidence": "",
      "notes": ""
    }}
  ],
  "companies": [
    {{
      "name": "",
      "role": "",
      "associated_technology": "",
      "associated_projects": [],
      "website_or_source": "",
      "notes": ""
    }}
  ],
  "pilot_demonstration_projects": [
    {{
      "project_name": "",
      "associated_technology": "",
      "organizations": [],
      "stage": "",
      "location": "",
      "start_year": null,
      "end_year_or_status": "",
      "scale_or_capacity": "",
      "co2_captured_or_reduced": "",
      "funding_amount": "",
      "key_partners": [],
      "source": "",
      "confidence": "",
      "evidence_notes": ""
    }}
  ],
  "evidence_sources": [
    {{
      "title": "",
      "url_or_reference": "",
      "source_type": "",
      "relevant_fields": [],
      "snippet": ""
    }}
  ],
  "missing_fields": [],
  "warnings": []
}}"""
