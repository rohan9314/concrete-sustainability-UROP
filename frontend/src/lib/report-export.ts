import type { ResearchReport } from "./research-types";
import { displayList, displayValue } from "./technology-intelligence";

export function slugFilename(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function downloadBlob(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadReportJson(report: ResearchReport) {
  downloadBlob(
    JSON.stringify(report, null, 2),
    `${slugFilename(report.technology)}-intelligence.json`,
    "application/json",
  );
}

/** Human-readable plain-text export of the same report data as the JSON download. */
export function formatReportAsText(report: ResearchReport): string {
  const lines: string[] = [];
  const intel = report.intelligence;
  const o = intel?.technology_overview;

  lines.push("CONCRETE DECARBONIZATION TECHNOLOGY INTELLIGENCE REPORT");
  lines.push("=".repeat(60));
  lines.push(`Technology: ${report.technology}`);
  lines.push(`Question set: ${report.questions_file}`);
  lines.push(`Generated: ${new Date().toISOString()}`);
  lines.push("");

  if (report.search_filters) {
    lines.push("SEARCH FILTERS");
    lines.push("-".repeat(40));
    lines.push(`Main category: ${report.search_filters.main_category}`);
    lines.push(`CCS subcategory: ${report.search_filters.ccs_subcategory}`);
    lines.push(`Company: ${report.search_filters.company_name || "Not Reported"}`);
    lines.push(`Project stage: ${report.search_filters.project_stage}`);
    lines.push("");
  }

  lines.push("RETRIEVAL SUMMARY");
  lines.push("-".repeat(40));
  lines.push(`Internet sources: ${report.retrieval_summary.internet_sources_found}`);
  lines.push(
    `Scientific papers: ${report.retrieval_summary.scientific_paper_sources_found}`,
  );
  lines.push(
    `Local paper database: ${
      report.retrieval_summary.local_paper_database_enabled ? "Enabled" : "Disabled"
    }`,
  );
  lines.push("");

  if (o) {
    lines.push("TECHNOLOGY OVERVIEW");
    lines.push("-".repeat(40));
    lines.push(`Technology name: ${displayValue(o.technology_name)}`);
    lines.push(`Main category: ${displayValue(o.main_category)}`);
    lines.push(`Subcategory: ${displayValue(o.subcategory)}`);
    lines.push(`CCS subcategory: ${displayValue(o.ccs_subcategory)}`);
    lines.push(`Deployment stage: ${displayValue(o.deployment_stage)}`);
    lines.push(`TRL: ${displayValue(o.trl)}`);
    lines.push(`Organizations: ${displayList(o.organizations)}`);
    lines.push(`Deployment partners: ${displayList(o.deployment_partners)}`);
    lines.push(`Geography: ${displayList(o.geography)}`);
    lines.push(`Source confidence: ${displayValue(o.source_confidence)}`);
    lines.push("");
  }

  if (intel?.metrics?.length) {
    lines.push("TECHNICAL AND ENVIRONMENTAL METRICS");
    lines.push("-".repeat(40));
    intel.metrics.forEach((m, i) => {
      lines.push(`${i + 1}. ${displayValue(m.metric_name)}`);
      lines.push(`   Value: ${displayValue(m.value)} ${m.unit || ""}`.trim());
      if (m.normalized_value != null) {
        lines.push(
          `   Normalized: ${m.normalized_value} ${m.normalized_unit || ""}`.trim(),
        );
      }
      lines.push(`   Source: ${displayValue(m.source)}`);
      lines.push(`   Confidence: ${displayValue(m.confidence)}`);
      if (m.notes && m.notes !== "Not Reported") lines.push(`   Notes: ${m.notes}`);
      lines.push("");
    });
  }

  if (intel?.companies?.length) {
    lines.push("COMPANIES AND ORGANIZATIONS");
    lines.push("-".repeat(40));
    intel.companies.forEach((c, i) => {
      lines.push(`${i + 1}. ${displayValue(c.name)}`);
      lines.push(`   Role: ${displayValue(c.role)}`);
      lines.push(`   Technology: ${displayValue(c.associated_technology)}`);
      lines.push(`   Projects: ${displayList(c.associated_projects)}`);
      lines.push(`   Source: ${displayValue(c.website_or_source)}`);
      if (c.notes && c.notes !== "Not Reported") lines.push(`   Notes: ${c.notes}`);
      lines.push("");
    });
  }

  if (intel?.pilot_demonstration_projects?.length) {
    lines.push("PILOT AND DEMONSTRATION PROJECTS");
    lines.push("-".repeat(40));
    intel.pilot_demonstration_projects.forEach((p, i) => {
      lines.push(`${i + 1}. ${displayValue(p.project_name)}`);
      lines.push(`   Technology: ${displayValue(p.associated_technology)}`);
      lines.push(`   Stage: ${displayValue(p.stage)}`);
      lines.push(`   Location: ${displayValue(p.location)}`);
      lines.push(`   Organizations: ${displayList(p.organizations)}`);
      lines.push(`   Scale/capacity: ${displayValue(p.scale_or_capacity)}`);
      lines.push(`   CO2 captured/reduced: ${displayValue(p.co2_captured_or_reduced)}`);
      lines.push(`   Funding: ${displayValue(p.funding_amount)}`);
      lines.push(`   Start year: ${displayValue(p.start_year)}`);
      lines.push(`   End/status: ${displayValue(p.end_year_or_status)}`);
      lines.push(`   Partners: ${displayList(p.key_partners)}`);
      lines.push(`   Source: ${displayValue(p.source)}`);
      lines.push(`   Confidence: ${displayValue(p.confidence)}`);
      if (p.evidence_notes && p.evidence_notes !== "Not Reported") {
        lines.push(`   Evidence: ${p.evidence_notes}`);
      }
      lines.push("");
    });
  }

  if (report.executive_summary?.trim()) {
    lines.push("EXECUTIVE SUMMARY");
    lines.push("-".repeat(40));
    lines.push(report.executive_summary.trim());
    lines.push("");
  }

  if (intel?.evidence_sources?.length) {
    lines.push("EVIDENCE AND SOURCES");
    lines.push("-".repeat(40));
    intel.evidence_sources.forEach((s, i) => {
      lines.push(`${i + 1}. ${displayValue(s.title)}`);
      lines.push(`   Type: ${displayValue(s.source_type)}`);
      if (s.url_or_reference) lines.push(`   URL: ${s.url_or_reference}`);
      if (s.relevant_fields?.length) {
        lines.push(`   Fields: ${s.relevant_fields.join(", ")}`);
      }
      if (s.snippet && s.snippet !== "Not Reported") {
        lines.push(`   Snippet: ${s.snippet}`);
      }
      lines.push("");
    });
  }

  if (intel?.missing_fields?.length) {
    lines.push("MISSING FIELDS");
    lines.push("-".repeat(40));
    intel.missing_fields.forEach((f) => lines.push(`- ${f}`));
    lines.push("");
  }

  if (intel?.warnings?.length) {
    lines.push("WARNINGS");
    lines.push("-".repeat(40));
    intel.warnings.forEach((w) => lines.push(`- ${w}`));
    lines.push("");
  }

  if (report.legacy_answers?.length) {
    lines.push("LEGACY 26-QUESTION OUTPUT");
    lines.push("-".repeat(40));
    report.legacy_answers.forEach((a, i) => {
      lines.push(`Q${String(i + 1).padStart(2, "0")}: ${a.question}`);
      lines.push(`Answer: ${a.answer}`);
      lines.push(`Confidence: ${a.confidence}`);
      lines.push("");
    });
  }

  lines.push("RAW JSON DATA");
  lines.push("-".repeat(40));
  lines.push(JSON.stringify(report, null, 2));

  return lines.join("\n");
}

export function downloadReportTxt(report: ResearchReport) {
  downloadBlob(
    formatReportAsText(report),
    `${slugFilename(report.technology)}-intelligence.txt`,
    "text/plain;charset=utf-8",
  );
}
