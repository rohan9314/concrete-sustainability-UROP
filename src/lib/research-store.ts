import type { ResearchReport } from "./research-mock";

// Simple in-memory store to pass the report from search → loading → report page
// without a backend. Replace with real API calls later.
let currentReport: ResearchReport | null = null;

export function setReport(r: ResearchReport) {
  currentReport = r;
}

export function getReport(): ResearchReport | null {
  return currentReport;
}
