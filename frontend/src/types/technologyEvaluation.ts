export type TechnologyCategory =
  | "Carbon Capture"
  | "Supplementary Cementitious Material (SCM)"
  | "Alternative SCM"
  | "Alternative Cementitious Material (ACM)"
  | "Aggregate Technology"
  | "Concrete Design"
  | "Structural Design"
  | "Other";

export type DeploymentStage =
  | "Laboratory"
  | "Pilot"
  | "Demonstration"
  | "Commercial"
  | "Unknown";

export type PerformanceMetric =
  | "CO₂ reduction"
  | "Energy reduction"
  | "Cost reduction"
  | "Strength improvement"
  | "Durability improvement"
  | "Resource efficiency"
  | "Other";

export type ConfidenceLevel = "Low" | "Medium" | "High";

export type SourceType =
  | "Company website"
  | "Academic paper"
  | "Government report"
  | "Industry report"
  | "News article"
  | "Other";

export type GeneratedBy = "mock" | "manual" | "ai";

export interface Source {
  title: string;
  url: string | null;
  publisher: string | null;
  year: number | null;
  source_type: SourceType;
  relevant_fields: string[];
}

export interface TechnologyEvaluation {
  id: string;
  query: {
    user_input: string;
    normalized_technology_name: string;
  };
  technology_overview: {
    technology_name: string;
    category: TechnologyCategory[];
    developers: string[];
    deployment_stage: DeploymentStage;
    trl: string | null;
    short_description: string;
  };
  technical_performance: {
    how_it_works: string;
    replaces_or_improves: string;
    performance_metrics_improved: PerformanceMetric[];
    key_inputs: string[];
    key_outputs: string[];
    technical_limitations: string[];
  };
  environmental_performance: {
    reported_ghg_reduction_percent: string | null;
    absolute_emissions_intensity: string | null;
    lifecycle_stage_affected: string[];
    environmental_benefits: string[];
    environmental_tradeoffs: string[];
  };
  cost_and_market: {
    reported_cost_impact: string | null;
    cost_drivers: string[];
    commercialization_status: string;
    target_customers: string[];
    adoption_barriers: string[];
  };
  evidence: {
    sources: Source[];
    confidence_level: ConfidenceLevel;
    missing_information: string[];
    assumptions: string[];
  };
  metadata: {
    created_at: string;
    updated_at: string;
    generated_by: GeneratedBy;
  };
}

export const EXAMPLE_TECHNOLOGIES = [
  "CarbonCure",
  "Sublime Systems",
  "Brimstone",
  "Fortera",
  "CarbonBuilt",
  "Calcium Looping",
  "LC3 Cement",
];
