"""Shared schema for offline technology records."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TechnologyCategory = Literal[
    "Carbon Capture",
    "Supplementary Cementitious Material",
    "Alternative SCM",
    "Alternative Cementitious Material",
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
    "Not Reported",
]

PerformanceMetricTag = Literal[
    "CO2 reduction",
    "Energy reduction",
    "Cost reduction",
    "Strength improvement",
    "Durability improvement",
    "Resource efficiency",
    "Other",
]

ConfidenceLevel = Literal["High", "Medium", "Low", "Not Reported"]

NOT_REPORTED = "Not Reported"

TECHNOLOGY_CATEGORIES: list[str] = [
    "Carbon Capture",
    "Supplementary Cementitious Material",
    "Alternative SCM",
    "Alternative Cementitious Material",
    "Aggregate Technology",
    "Concrete Design",
    "Structural Design",
    "Other",
]

DEPLOYMENT_STAGES: list[str] = [
    "Laboratory",
    "Pilot",
    "Demonstration",
    "Commercial",
    "Not Reported",
]

PERFORMANCE_METRIC_TAGS: list[str] = [
    "CO2 reduction",
    "Energy reduction",
    "Cost reduction",
    "Strength improvement",
    "Durability improvement",
    "Resource efficiency",
    "Other",
]

TRACKED_FIELDS: list[str] = [
    "technology_name",
    "technology_category",
    "company_or_organization",
    "deployment_stage",
    "technical_description",
    "replaces_or_improves",
    "performance_metrics",
    "reported_ghg_reduction_percent",
    "absolute_emissions_intensity_kg_co2e",
    "energy_reduction_percent",
    "cost_reduction_percent",
    "pilot_projects",
    "demonstration_projects",
    "relevant_sources",
]


class RelevantSource(BaseModel):
    paper_id: str = ""
    title: str = ""
    url: str = ""
    doi: str = ""
    year: str = NOT_REPORTED
    snippet: str = ""


class ProjectRef(BaseModel):
    name: str
    description: str = NOT_REPORTED
    source_ids: list[str] = Field(default_factory=list)


class TechnologyRecord(BaseModel):
    record_id: str = ""
    technology_name: str
    technology_category: TechnologyCategory = "Other"
    company_or_organization: str = NOT_REPORTED
    deployment_stage: DeploymentStage = "Not Reported"
    technical_description: str = NOT_REPORTED
    replaces_or_improves: str = NOT_REPORTED
    performance_metrics: list[PerformanceMetricTag] = Field(default_factory=list)
    reported_ghg_reduction_percent: str = NOT_REPORTED
    absolute_emissions_intensity_kg_co2e: str = NOT_REPORTED
    energy_reduction_percent: str = NOT_REPORTED
    cost_reduction_percent: str = NOT_REPORTED
    pilot_projects: list[ProjectRef] = Field(default_factory=list)
    demonstration_projects: list[ProjectRef] = Field(default_factory=list)
    relevant_sources: list[RelevantSource] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    confidence_by_field: dict[str, ConfidenceLevel] = Field(default_factory=dict)
    extraction_notes: list[str] = Field(default_factory=list)
    coverage_score: float = 0.0
    source_provenance: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("technology_category", mode="before")
    @classmethod
    def coerce_category(cls, value: object) -> str:
        if value in TECHNOLOGY_CATEGORIES:
            return str(value)
        return "Other"

    @field_validator("deployment_stage", mode="before")
    @classmethod
    def coerce_stage(cls, value: object) -> str:
        if value in DEPLOYMENT_STAGES:
            return str(value)
        return NOT_REPORTED


class FilteredPaper(BaseModel):
    paper_id: str
    relevance_score: float
    matched_keywords: list[str] = Field(default_factory=list)
    matched_tier1_keywords: list[str] = Field(default_factory=list)
    matched_tier2_keywords: list[str] = Field(default_factory=list)
    matched_tier3_keywords: list[str] = Field(default_factory=list)
    negative_topic_matches: list[str] = Field(default_factory=list)
    relevance_label: str = "Low"
    relevance_reason: str = ""
    title: str = ""
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = NOT_REPORTED
    year_source: str = "not_reported"
    doi: str = ""
    url: str = ""
    snippet: str = ""
    text: str = ""


class RankedPaper(FilteredPaper):
    rank_score: float = 0.0


class TechnologyDatabase(BaseModel):
    version: str = "1.0"
    record_count: int = 0
    records: list[TechnologyRecord] = Field(default_factory=list)


def is_field_reported(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip() != NOT_REPORTED
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return len(value) > 0
    return True


def compute_missing_fields(record: TechnologyRecord) -> list[str]:
    missing: list[str] = []
    data = record.model_dump()
    for field in TRACKED_FIELDS:
        if field == "technology_name":
            continue
        if not is_field_reported(data.get(field)):
            missing.append(field)
    return missing


def compute_coverage_score(record: TechnologyRecord) -> float:
    """Fraction of tracked fields with reported values (excluding technology_name)."""
    fields = [f for f in TRACKED_FIELDS if f != "technology_name"]
    if not fields:
        return 0.0
    data = record.model_dump()
    reported = sum(1 for field in fields if is_field_reported(data.get(field)))
    return round(reported / len(fields), 4)


def finalize_record(record: TechnologyRecord) -> TechnologyRecord:
    """Compute missing_fields and coverage_score."""
    missing = compute_missing_fields(record)
    coverage = compute_coverage_score(record)
    if not record.record_id:
        key = f"{record.technology_name}|{record.company_or_organization}".lower()
        record.record_id = hashlib.sha256(key.encode()).hexdigest()[:16]
    return record.model_copy(
        update={"missing_fields": missing, "coverage_score": coverage},
    )


def merge_group_key(record: TechnologyRecord) -> str:
    name = re.sub(r"\s+", " ", record.technology_name.strip().lower())
    org = re.sub(r"\s+", " ", record.company_or_organization.strip().lower())
    if org in {"", "not reported"}:
        return name
    return f"{name}|{org}"
