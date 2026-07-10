export const NA = "N.A.";

export type ConfidenceLevel = "High" | "Medium" | "Low" | typeof NA;
export type DeploymentStage =
  | "Laboratory"
  | "Pilot"
  | "Demonstration"
  | "Commercial"
  | typeof NA;
export type SourceType = "Literature" | "Web" | typeof NA;
export type MetricDimension = "CO2 Reduction" | "Energy" | "Cost" | "Other" | typeof NA;

export const CANONICAL_FIELDS = [
  "category",
  "subcategory",
  "technology_type",
  "company_or_organization",
  "project_name",
  "project_year",
  "project_location",
  "deployment_stage",
  "metric_dimension",
  "metric_name",
  "metric_value",
  "metric_unit",
  "metric_boundary",
  "co2_reduction",
  "energy_impact",
  "cost_impact",
  "primary_barriers",
  "source_type",
  "source_title",
  "source_url_or_citation",
  "confidence",
  "notes",
] as const;

export type CanonicalField = (typeof CANONICAL_FIELDS)[number];

export interface CarbonCaptureRecord {
  category: string;
  subcategory: string;
  technology_type: string;
  company_or_organization: string;
  project_name: string;
  project_year: string;
  project_location: string;
  deployment_stage: DeploymentStage | string;
  metric_dimension: MetricDimension | string;
  metric_name: string;
  metric_value: string;
  metric_unit: string;
  metric_boundary: string;
  co2_reduction: string;
  energy_impact: string;
  cost_impact: string;
  primary_barriers: string;
  source_type: SourceType | string;
  source_title: string;
  source_url_or_citation: string;
  confidence: ConfidenceLevel | string;
  notes: string;
}

export const CARBON_CAPTURE_FIELD_LABELS: Record<CanonicalField, string> = {
  category: "Category",
  subcategory: "Subcategory",
  technology_type: "Technology Type",
  company_or_organization: "Company / Organization",
  project_name: "Project Name",
  project_year: "Project Year",
  project_location: "Project Location",
  deployment_stage: "Deployment Stage",
  metric_dimension: "Metric Dimension",
  metric_name: "Metric Name",
  metric_value: "Metric Value",
  metric_unit: "Metric Unit",
  metric_boundary: "Metric Boundary",
  co2_reduction: "CO2 Reduction",
  energy_impact: "Energy Impact",
  cost_impact: "Cost Impact",
  primary_barriers: "Primary Barriers",
  source_type: "Source Type",
  source_title: "Source Title",
  source_url_or_citation: "Source URL / Citation",
  confidence: "Confidence",
  notes: "Notes",
};

export const PRIORITY_DISPLAY_FIELDS: CanonicalField[] = [
  "subcategory",
  "technology_type",
  "company_or_organization",
  "project_name",
  "project_year",
  "project_location",
  "deployment_stage",
  "metric_dimension",
  "metric_name",
  "metric_value",
  "metric_unit",
  "co2_reduction",
  "energy_impact",
  "cost_impact",
  "primary_barriers",
  "source_type",
  "source_url_or_citation",
  "confidence",
  "notes",
];

export const TABLE_DISPLAY_FIELDS: CanonicalField[] = [
  "subcategory",
  "technology_type",
  "company_or_organization",
  "project_name",
  "deployment_stage",
  "metric_dimension",
  "metric_name",
  "metric_value",
  "metric_unit",
  "co2_reduction",
  "energy_impact",
  "cost_impact",
  "source_type",
  "confidence",
];

const LEGACY_FIELD_MAP: Record<string, CanonicalField> = {
  company: "company_or_organization",
  organization: "company_or_organization",
  solution_or_technology_type: "technology_type",
  technology_name: "technology_type",
  solution: "technology_type",
  project: "project_name",
  year: "project_year",
  location: "project_location",
  value: "metric_value",
  unit: "metric_unit",
  boundary: "metric_boundary",
  source: "source_type",
  title: "source_title",
  url_citation: "source_url_or_citation",
  url: "source_url_or_citation",
  citation: "source_url_or_citation",
  cost: "cost_impact",
  paper_title: "source_title",
  paper_url: "source_url_or_citation",
  source_url: "source_url_or_citation",
};

export function isNA(value: string | undefined | null): boolean {
  if (!value) return true;
  const text = value.trim().toLowerCase();
  return (
    !text ||
    text === "n.a." ||
    text === "na" ||
    text === "not reported" ||
    text === "not found"
  );
}

export function displayCarbonCaptureValue(value: string | undefined | null): string {
  if (isNA(value)) return NA;
  return value!.trim();
}

export function mapLegacyCarbonCaptureRow(
  row: Record<string, string>,
): CarbonCaptureRecord {
  const mapped: Record<string, string> = {};
  for (const [key, value] of Object.entries(row)) {
    const canonical = LEGACY_FIELD_MAP[key] ?? key;
    if (!mapped[canonical] || isNA(mapped[canonical])) {
      mapped[canonical] = value;
    }
  }

  const record = {} as CarbonCaptureRecord;
  for (const field of CANONICAL_FIELDS) {
    record[field] = displayCarbonCaptureValue(mapped[field]);
  }
  return record;
}

export function technologyRecordToCarbonCapture(
  record: Record<string, unknown>,
): CarbonCaptureRecord {
  return mapLegacyCarbonCaptureRow(
    Object.fromEntries(
      Object.entries(record).map(([key, value]) => [key, String(value ?? NA)]),
    ),
  );
}
