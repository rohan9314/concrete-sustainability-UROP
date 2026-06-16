"""Coerce LLM structured intelligence output to allowed categorical values."""

from __future__ import annotations

import re
from typing import Any

from intelligence_constants import (
    CCS_SUBCATEGORIES,
    CCS_SUBCATEGORY_ALIASES,
    COMPANY_ROLE_ALIASES,
    COMPANY_ROLES,
    CONFIDENCE_LEVELS,
    DEPLOYMENT_STAGE_ALIASES,
    DEPLOYMENT_STAGES,
    MAIN_CATEGORIES,
    MAIN_CATEGORY_ALIASES,
    PROJECT_STAGES,
)
from schemas.technology_intelligence import (
    CompanyIntel,
    EvidenceSourceIntel,
    MetricIntel,
    PilotDemonstrationProjectIntel,
    TechnologyIntelligence,
    TechnologyOverviewIntel,
)


def _clean_text(value: object, *, default: str = "Not Reported") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _coerce_category(
    value: object,
    allowed: tuple[str, ...],
    aliases: dict[str, str],
    *,
    default: str = "Not Reported",
) -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if text in allowed:
        return text
    lowered = text.lower()
    if lowered in aliases:
        return aliases[lowered]
    for option in allowed:
        if option.lower() == lowered:
            return option
    for option in allowed:
        if lowered in option.lower() or option.lower() in lowered:
            return option
    if default == "Not Reported" and "Other" in allowed:
        return "Other"
    return default


def _coerce_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"-?\d+", str(value))
    if not match:
        return None
    try:
        return int(match.group())
    except ValueError:
        return None


def _coerce_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _coerce_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in {"not reported", "none", "n/a"}:
            return []
        if ";" in cleaned:
            parts = [part.strip() for part in cleaned.split(";")]
        elif "," in cleaned:
            parts = [part.strip() for part in cleaned.split(",")]
        else:
            parts = [cleaned]
        return [part for part in parts if part]
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text.lower() not in {"not reported", "none", "n/a"}:
                items.append(text)
        return items
    return []


def _normalize_overview(raw: dict | None, technology_name: str) -> TechnologyOverviewIntel:
    data = raw if isinstance(raw, dict) else {}
    trl = _coerce_int(data.get("trl"))
    return TechnologyOverviewIntel(
        technology_name=_clean_text(
            data.get("technology_name") or technology_name,
            default=technology_name or "Not Reported",
        ),
        main_category=_coerce_category(
            data.get("main_category"), MAIN_CATEGORIES, MAIN_CATEGORY_ALIASES
        ),
        subcategory=_clean_text(data.get("subcategory")),
        ccs_subcategory=_coerce_category(
            data.get("ccs_subcategory"), CCS_SUBCATEGORIES, CCS_SUBCATEGORY_ALIASES
        ),
        deployment_stage=_coerce_category(
            data.get("deployment_stage"),
            DEPLOYMENT_STAGES,
            DEPLOYMENT_STAGE_ALIASES,
        ),
        trl=trl,
        organizations=_coerce_str_list(data.get("organizations")),
        deployment_partners=_coerce_str_list(data.get("deployment_partners")),
        geography=_coerce_str_list(data.get("geography")),
        source_confidence=_coerce_category(
            data.get("source_confidence"),
            CONFIDENCE_LEVELS,
            {},
        ),
    )


def _normalize_metric(raw: dict | None) -> MetricIntel | None:
    if not isinstance(raw, dict):
        return None
    metric_name = _clean_text(raw.get("metric_name"), default="")
    if not metric_name or metric_name == "Not Reported":
        return None
    return MetricIntel(
        metric_name=metric_name,
        value=_coerce_float(raw.get("value")),
        unit=_clean_text(raw.get("unit"), default=""),
        normalized_value=_coerce_float(raw.get("normalized_value")),
        normalized_unit=_clean_text(raw.get("normalized_unit"), default=""),
        source=_clean_text(raw.get("source"), default=""),
        confidence=_coerce_category(raw.get("confidence"), CONFIDENCE_LEVELS, {}),
        notes=_clean_text(raw.get("notes"), default=""),
    )


def _normalize_company(raw: dict | None) -> CompanyIntel | None:
    if not isinstance(raw, dict):
        return None
    name = _clean_text(raw.get("name"), default="")
    if not name or name == "Not Reported":
        return None
    return CompanyIntel(
        name=name,
        role=_coerce_category(raw.get("role"), COMPANY_ROLES, COMPANY_ROLE_ALIASES),
        associated_technology=_clean_text(raw.get("associated_technology"), default=""),
        associated_projects=_coerce_str_list(raw.get("associated_projects")),
        website_or_source=_clean_text(raw.get("website_or_source"), default=""),
        notes=_clean_text(raw.get("notes"), default=""),
    )


def _normalize_project(raw: dict | None) -> PilotDemonstrationProjectIntel | None:
    if not isinstance(raw, dict):
        return None
    project_name = _clean_text(raw.get("project_name"), default="")
    if not project_name or project_name == "Not Reported":
        return None
    return PilotDemonstrationProjectIntel(
        project_name=project_name,
        associated_technology=_clean_text(raw.get("associated_technology"), default=""),
        organizations=_coerce_str_list(raw.get("organizations")),
        stage=_coerce_category(raw.get("stage"), PROJECT_STAGES, DEPLOYMENT_STAGE_ALIASES),
        location=_clean_text(raw.get("location")),
        start_year=_coerce_int(raw.get("start_year")),
        end_year_or_status=_clean_text(raw.get("end_year_or_status")),
        scale_or_capacity=_clean_text(raw.get("scale_or_capacity")),
        co2_captured_or_reduced=_clean_text(raw.get("co2_captured_or_reduced")),
        funding_amount=_clean_text(raw.get("funding_amount")),
        key_partners=_coerce_str_list(raw.get("key_partners")),
        source=_clean_text(raw.get("source"), default=""),
        confidence=_coerce_category(raw.get("confidence"), CONFIDENCE_LEVELS, {}),
        evidence_notes=_clean_text(raw.get("evidence_notes"), default=""),
    )


def _normalize_evidence(raw: dict | None) -> EvidenceSourceIntel | None:
    if not isinstance(raw, dict):
        return None
    title = _clean_text(raw.get("title"), default="")
    url = _clean_text(raw.get("url_or_reference"), default="")
    if (not title or title == "Not Reported") and not url:
        return None
    return EvidenceSourceIntel(
        title=title or "Not Reported",
        url_or_reference=url,
        source_type=_clean_text(raw.get("source_type"), default="Not Reported"),
        relevant_fields=_coerce_str_list(raw.get("relevant_fields")),
        snippet=_clean_text(raw.get("snippet"), default=""),
    )


def normalize_intelligence(
    data: dict | Any,
    *,
    technology_name: str,
    filter_hints: dict | None = None,
) -> TechnologyIntelligence:
    """Validate and coerce raw LLM JSON into TechnologyIntelligence."""
    payload = data if isinstance(data, dict) else {}
    hints = filter_hints if isinstance(filter_hints, dict) else {}

    overview = _normalize_overview(payload.get("technology_overview"), technology_name)
    if hints.get("main_category") and hints["main_category"] != "Not Reported":
        if overview.main_category in {"Not Reported", "Other"}:
            overview.main_category = _coerce_category(
                hints["main_category"], MAIN_CATEGORIES, MAIN_CATEGORY_ALIASES
            )
    if hints.get("ccs_subcategory") and hints["ccs_subcategory"] != "Not Reported":
        if overview.ccs_subcategory in {"Not Reported", "Other"}:
            overview.ccs_subcategory = _coerce_category(
                hints["ccs_subcategory"], CCS_SUBCATEGORIES, CCS_SUBCATEGORY_ALIASES
            )

    metrics: list[MetricIntel] = []
    for item in payload.get("metrics") or []:
        metric = _normalize_metric(item)
        if metric:
            metrics.append(metric)

    companies: list[CompanyIntel] = []
    for item in payload.get("companies") or []:
        company = _normalize_company(item)
        if company:
            companies.append(company)

    projects: list[PilotDemonstrationProjectIntel] = []
    for item in payload.get("pilot_demonstration_projects") or []:
        project = _normalize_project(item)
        if project:
            projects.append(project)

    evidence_sources: list[EvidenceSourceIntel] = []
    for item in payload.get("evidence_sources") or []:
        evidence = _normalize_evidence(item)
        if evidence:
            evidence_sources.append(evidence)

    missing_fields = _coerce_str_list(payload.get("missing_fields"))
    warnings = _coerce_str_list(payload.get("warnings"))

    return TechnologyIntelligence(
        technology_overview=overview,
        metrics=metrics,
        companies=companies,
        pilot_demonstration_projects=projects,
        evidence_sources=evidence_sources,
        missing_fields=missing_fields,
        warnings=warnings,
    )
