import type { ResearchReport } from "./research-types";

let currentReport: ResearchReport | null = null;

export function setReport(report: ResearchReport) {
  currentReport = report;
}

export function getReport(): ResearchReport | null {
  return currentReport;
}
