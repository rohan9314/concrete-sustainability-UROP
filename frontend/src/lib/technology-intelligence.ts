export const MAIN_CATEGORIES = [
  "Carbon Capture",
  "Supplementary Cementitious Material",
  "Alternative SCM",
  "Alternative Cementitious Material",
  "Aggregate Technology",
  "Concrete Design",
  "Structural Design",
  "Other",
  "Not Reported",
] as const;

export const CCS_SUBCATEGORIES = [
  "Post-combustion capture",
  "Oxyfuel combustion",
  "Direct separation",
  "Calcium looping",
  "Membrane separation",
  "Adsorption",
  "Mineralization/carbonation",
  "Direct air capture linked to concrete/cement",
  "Other",
  "Not Reported",
] as const;

export const DEPLOYMENT_STAGES = [
  "Laboratory",
  "Pilot",
  "Demonstration",
  "Not Reported",
] as const;

export const PROJECT_STAGES = ["Pilot", "Demonstration", "Not Reported"] as const;

export type MainCategory = (typeof MAIN_CATEGORIES)[number];
export type CcsSubcategory = (typeof CCS_SUBCATEGORIES)[number];
export type DeploymentStage = (typeof DEPLOYMENT_STAGES)[number];
export type ProjectStage = (typeof PROJECT_STAGES)[number];
export type Confidence = "High" | "Medium" | "Low" | "Not Reported";

export interface TechnologyOverviewIntel {
  technology_name: string;
  main_category: string;
  subcategory: string;
  ccs_subcategory: string;
  deployment_stage: string;
  trl: number | null;
  organizations: string[];
  deployment_partners: string[];
  geography: string[];
  source_confidence: string;
}

export interface MetricIntel {
  metric_name: string;
  value: number | null;
  unit: string;
  normalized_value: number | null;
  normalized_unit: string;
  source: string;
  confidence: string;
  notes: string;
}

export interface CompanyIntel {
  name: string;
  role: string;
  associated_technology: string;
  associated_projects: string[];
  website_or_source: string;
  notes: string;
}

export interface PilotDemonstrationProjectIntel {
  project_name: string;
  associated_technology: string;
  organizations: string[];
  stage: string;
  location: string;
  start_year: number | null;
  end_year_or_status: string;
  scale_or_capacity: string;
  co2_captured_or_reduced: string;
  funding_amount: string;
  key_partners: string[];
  source: string;
  confidence: string;
  evidence_notes: string;
}

export interface EvidenceSourceIntel {
  source_id?: string;
  title: string;
  url_or_reference: string;
  source_type: string;
  relevant_fields: string[];
  snippet: string;
  authors?: string[];
  year?: string;
  doi?: string;
  journal_or_venue?: string;
}

export interface TechnologyIntelligence {
  technology_overview: TechnologyOverviewIntel;
  metrics: MetricIntel[];
  companies: CompanyIntel[];
  pilot_demonstration_projects: PilotDemonstrationProjectIntel[];
  evidence_sources: EvidenceSourceIntel[];
  missing_fields: string[];
  warnings: string[];
}

export interface ResearchFilters {
  main_category: string;
  ccs_subcategory: string;
  company_name: string;
  project_stage: string;
}

export interface IntelligenceOptions {
  main_categories: string[];
  ccs_subcategories: string[];
  deployment_stages: string[];
  project_stages: string[];
  company_roles: string[];
  confidence_levels: string[];
}

export function displayValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "Not Reported";
  const text = String(value).trim();
  return text || "Not Reported";
}

export function displayList(values: string[] | null | undefined): string {
  if (!values || values.length === 0) return "Not Reported";
  return values.join(", ");
}
