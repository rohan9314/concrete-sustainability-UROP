import type { Answer, Confidence, SourceType } from "./research-types";
import type {
  ResearchFilters,
  TechnologyIntelligence,
} from "./technology-intelligence";

export type { Confidence, SourceType };

export interface SourceMetadata {
  authors: string[];
  year: string;
  journal: string;
  doi: string;
}

export interface Source {
  title: string;
  url: string;
  source_type: string;
  snippet: string;
  full_text: string;
  metadata: SourceMetadata;
}

export interface ResearchReport {
  technology: string;
  questions_file: string;
  executive_summary: string;
  intelligence: TechnologyIntelligence;
  legacy_answers: Answer[];
  retrieval_summary: {
    internet_sources_found: number;
    scientific_paper_sources_found: number;
    local_paper_database_enabled: boolean;
  };
  search_filters?: ResearchFilters;
}

export const EXAMPLE_TOPICS = [
  "Calcium Looping",
  "LC3 Cement",
  "Fly Ash",
  "Carbon Upcycling",
  "Direct Separation",
  "Fortera",
  "Sublime Systems",
  "CycloneCC",
];
