import type { ResearchReport } from "./research-types";
import type { TechnologyRecord } from "./technology-record";

export type ReportViewMode = "database" | "live";

export interface StoredReport {
  mode: ReportViewMode;
  technologyRecord?: TechnologyRecord;
  liveReport?: ResearchReport;
}

let currentReport: StoredReport | null = null;

export function setTechnologyRecord(record: TechnologyRecord) {
  currentReport = { mode: "database", technologyRecord: record };
}

export function setReport(report: ResearchReport) {
  currentReport = { mode: "live", liveReport: report };
}

export function getStoredReport(): StoredReport | null {
  return currentReport;
}

/** @deprecated Use getStoredReport() */
export function getReport(): ResearchReport | null {
  return currentReport?.liveReport ?? null;
}
