"""Pydantic models for the standardized TechnologyEvaluation contract."""

from typing import Literal

from pydantic import BaseModel, Field

TechnologyCategory = Literal[
    "Carbon Capture",
    "Supplementary Cementitious Material (SCM)",
    "Alternative SCM",
    "Alternative Cementitious Material (ACM)",
    "Aggregate Technology",
    "Concrete Design",
    "Structural Design",
    "Other",
]

DeploymentStage = Literal[
    "Laboratory",
    "Pilot",
    "Demonstration",
    "Commercial",
    "Unknown",
]

PerformanceMetric = Literal[
    "CO₂ reduction",
    "Energy reduction",
    "Cost reduction",
    "Strength improvement",
    "Durability improvement",
    "Resource efficiency",
    "Other",
]

ConfidenceLevel = Literal["Low", "Medium", "High"]

SourceType = Literal[
    "Company website",
    "Academic paper",
    "Government report",
    "Industry report",
    "News article",
    "Other",
]

GeneratedBy = Literal["mock", "manual", "ai"]


class QueryInfo(BaseModel):
    user_input: str
    normalized_technology_name: str


class TechnologyOverview(BaseModel):
    technology_name: str
    category: list[TechnologyCategory] = Field(default_factory=list)
    developers: list[str] = Field(default_factory=list)
    deployment_stage: DeploymentStage = "Unknown"
    trl: str | None = None
    short_description: str = ""


class TechnicalPerformance(BaseModel):
    how_it_works: str = ""
    replaces_or_improves: str = ""
    performance_metrics_improved: list[PerformanceMetric] = Field(default_factory=list)
    key_inputs: list[str] = Field(default_factory=list)
    key_outputs: list[str] = Field(default_factory=list)
    technical_limitations: list[str] = Field(default_factory=list)


class EnvironmentalPerformance(BaseModel):
    reported_ghg_reduction_percent: str | None = None
    absolute_emissions_intensity: str | None = None
    lifecycle_stage_affected: list[str] = Field(default_factory=list)
    environmental_benefits: list[str] = Field(default_factory=list)
    environmental_tradeoffs: list[str] = Field(default_factory=list)


class CostAndMarket(BaseModel):
    reported_cost_impact: str | None = None
    cost_drivers: list[str] = Field(default_factory=list)
    commercialization_status: str = ""
    target_customers: list[str] = Field(default_factory=list)
    adoption_barriers: list[str] = Field(default_factory=list)


class Source(BaseModel):
    title: str
    url: str | None = None
    publisher: str | None = None
    year: int | None = None
    source_type: SourceType = "Other"
    relevant_fields: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    sources: list[Source] = Field(default_factory=list)
    confidence_level: ConfidenceLevel = "Medium"
    missing_information: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class EvaluationMetadata(BaseModel):
    created_at: str
    updated_at: str
    generated_by: GeneratedBy = "mock"


class TechnologyEvaluation(BaseModel):
    id: str
    query: QueryInfo
    technology_overview: TechnologyOverview
    technical_performance: TechnicalPerformance
    environmental_performance: EnvironmentalPerformance
    cost_and_market: CostAndMarket
    evidence: Evidence
    metadata: EvaluationMetadata


class EvaluateRequest(BaseModel):
    technology_name: str = Field(..., min_length=1)


REQUIRED_EVALUATION_FIELDS = (
    "id",
    "query",
    "technology_overview",
    "technical_performance",
    "environmental_performance",
    "cost_and_market",
    "evidence",
    "metadata",
)
