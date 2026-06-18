"""Pydantic models for structured technology intelligence database output."""

from pydantic import BaseModel, Field


class TechnologyOverviewIntel(BaseModel):
    technology_name: str = "Not Reported"
    main_category: str = "Not Reported"
    subcategory: str = "Not Reported"
    ccs_subcategory: str = "Not Reported"
    deployment_stage: str = "Not Reported"
    trl: int | None = None
    organizations: list[str] = Field(default_factory=list)
    deployment_partners: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    source_confidence: str = "Not Reported"


class MetricIntel(BaseModel):
    metric_name: str = "Not Reported"
    value: float | None = None
    unit: str = ""
    normalized_value: float | None = None
    normalized_unit: str = ""
    source: str = ""
    confidence: str = "Not Reported"
    notes: str = ""


class CompanyIntel(BaseModel):
    name: str = "Not Reported"
    role: str = "Not Reported"
    associated_technology: str = ""
    associated_projects: list[str] = Field(default_factory=list)
    website_or_source: str = ""
    notes: str = ""


class PilotDemonstrationProjectIntel(BaseModel):
    project_name: str = "Not Reported"
    associated_technology: str = ""
    organizations: list[str] = Field(default_factory=list)
    stage: str = "Not Reported"
    location: str = "Not Reported"
    start_year: int | None = None
    end_year_or_status: str = "Not Reported"
    scale_or_capacity: str = "Not Reported"
    co2_captured_or_reduced: str = "Not Reported"
    funding_amount: str = "Not Reported"
    key_partners: list[str] = Field(default_factory=list)
    source: str = ""
    confidence: str = "Not Reported"
    evidence_notes: str = ""


class EvidenceSourceIntel(BaseModel):
    source_id: str = ""
    title: str = "Not Reported"
    url_or_reference: str = ""
    source_type: str = "Not Reported"
    relevant_fields: list[str] = Field(default_factory=list)
    snippet: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = "Not Reported"
    doi: str = ""
    journal_or_venue: str = ""


class TechnologyIntelligence(BaseModel):
    technology_overview: TechnologyOverviewIntel = Field(
        default_factory=TechnologyOverviewIntel
    )
    metrics: list[MetricIntel] = Field(default_factory=list)
    companies: list[CompanyIntel] = Field(default_factory=list)
    pilot_demonstration_projects: list[PilotDemonstrationProjectIntel] = Field(
        default_factory=list
    )
    evidence_sources: list[EvidenceSourceIntel] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResearchFilters(BaseModel):
    main_category: str = "Not Reported"
    ccs_subcategory: str = "Not Reported"
    company_name: str = ""
    project_stage: str = "Not Reported"
