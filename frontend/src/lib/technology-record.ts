import type { RegisteredSource } from "./source-registry";

export type TechnologyCategory =
  | "Carbon Capture"
  | "Supplementary Cementitious Material"
  | "Alternative SCM"
  | "Alternative Cementitious Material"
  | "Aggregate Technology"
  | "Concrete Design"
  | "Structural Design"
  | "Other";

export type DeploymentStage =
  | "Laboratory"
  | "Pilot"
  | "Demonstration"
  | "Commercial"
  | "Not Reported";

export type PerformanceMetricTag =
  | "CO2 reduction"
  | "Energy reduction"
  | "Cost reduction"
  | "Strength improvement"
  | "Durability improvement"
  | "Resource efficiency"
  | "Other";

export type ConfidenceLevel = "High" | "Medium" | "Low" | "Not Reported";

export const NOT_REPORTED = "Not Reported";

export const TRACKED_FIELD_COUNT = 13;

export const FIELD_LABELS: Record<string, string> = {
  technology_name: "Technology Name",
  technology_category: "Category",
  company_or_organization: "Company / Organization",
  deployment_stage: "Deployment Stage",
  technical_description: "Technical Description",
  replaces_or_improves: "Replaces or Improves",
  performance_metrics: "Performance Metrics",
  reported_ghg_reduction_percent: "GHG Reduction (%)",
  absolute_emissions_intensity_kg_co2e: "Emissions Intensity (kg CO2e)",
  energy_reduction_percent: "Energy Reduction (%)",
  cost_reduction_percent: "Cost Reduction (%)",
  pilot_projects: "Pilot Projects",
  demonstration_projects: "Demonstration Projects",
  relevant_sources: "Relevant Sources",
};

export interface RelevantSource {
  source_id?: string;
  paper_id?: string;
  source_type?: "paper" | "web";
  title: string;
  authors?: string[];
  url: string;
  doi: string;
  year: string;
  journal_or_venue?: string;
  website_or_publisher?: string;
  retrieval_date?: string;
  snippet: string;
}

export interface ProjectRef {
  name: string;
  description: string;
  source_ids: string[];
}

export interface TechnologyRecord {
  record_id: string;
  technology_name: string;
  technology_category: TechnologyCategory;
  company_or_organization: string;
  deployment_stage: DeploymentStage;
  technical_description: string;
  replaces_or_improves: string;
  performance_metrics: PerformanceMetricTag[];
  reported_ghg_reduction_percent: string;
  absolute_emissions_intensity_kg_co2e: string;
  energy_reduction_percent: string;
  cost_reduction_percent: string;
  pilot_projects: ProjectRef[];
  demonstration_projects: ProjectRef[];
  relevant_sources: RelevantSource[];
  missing_fields: string[];
  confidence_by_field: Record<string, ConfidenceLevel>;
  extraction_notes: string[];
  coverage_score: number;
  source_provenance: Record<string, string[]>;
  sources?: RegisteredSource[];
  sources_used?: RegisteredSource[];
  sources_considered?: RegisteredSource[];
  citation_warnings?: string[];
}

export interface TechnologyDatabaseResponse {
  version: string;
  record_count: number;
  records: TechnologyRecord[];
  sources?: RegisteredSource[];
}

export function isReported(value: string | string[] | undefined | null): boolean {
  if (value == null) return false;
  if (Array.isArray(value)) return value.length > 0;
  const text = value.trim();
  return Boolean(text) && text !== NOT_REPORTED;
}

export function displayValue(value: string | undefined | null): string {
  if (!value || !value.trim()) return NOT_REPORTED;
  return value;
}

export function coverageLabel(record: TechnologyRecord): string {
  const reported = TRACKED_FIELD_COUNT - record.missing_fields.length;
  return `${reported}/${TRACKED_FIELD_COUNT} fields reported`;
}

export function confidenceClass(level: ConfidenceLevel | undefined): string {
  switch (level) {
    case "High":
      return "text-confidence-high";
    case "Medium":
      return "text-confidence-medium";
    case "Low":
      return "text-confidence-low";
    default:
      return "text-muted-foreground";
  }
}

export function fieldStatus(
  field: string,
  record: TechnologyRecord,
): "Reported" | "Not Reported" | "Low Confidence" {
  if (record.missing_fields.includes(field)) return "Not Reported";
  const confidence = record.confidence_by_field[field];
  if (confidence === "Low") return "Low Confidence";
  return "Reported";
}
