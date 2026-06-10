export type Confidence = "High" | "Medium" | "Low";
export type SourceType = "internet" | "scientific_paper";

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

export interface Answer {
  question: string;
  answer: string;
  confidence: Confidence;
  source_type_used: SourceType[];
  sources: Source[];
}

export interface ResearchReport {
  technology: string;
  questions_file: string;
  executive_summary: string;
  answers: Answer[];
  retrieval_summary: {
    internet_sources_found: number;
    scientific_paper_sources_found: number;
    local_paper_database_enabled: boolean;
  };
}

export const EXAMPLE_TOPICS = [
  "Calcium Looping",
  "LC3 Cement",
  "Fly Ash",
  "Carbon Upcycling",
  "Direct Separation",
  "Fortera",
  "Sublime Systems",
];
