import { useMemo, useState } from "react";
import type { ResearchReport } from "@/lib/research-types";
import type {
  CompanyIntel,
  MetricIntel,
  PilotDemonstrationProjectIntel,
} from "@/lib/technology-intelligence";
import { displayList, displayValue } from "@/lib/technology-intelligence";
import { LegacyQASection } from "./LegacyQASection";
import { ChevronDown, ExternalLink } from "lucide-react";

const TABS = [
  "Overview",
  "Metrics",
  "Companies",
  "Projects",
  "Evidence",
  "Summary",
  "Legacy Q&A",
] as const;

type Tab = (typeof TABS)[number];

export function StructuredReport({ report }: { report: ResearchReport }) {
  const [tab, setTab] = useState<Tab>("Overview");
  const intel = report.intelligence;
  const overview = intel?.technology_overview;

  const hasLegacy = (report.legacy_answers?.length ?? 0) > 0;
  const visibleTabs = useMemo(
    () => TABS.filter((t) => t !== "Legacy Q&A" || hasLegacy),
    [hasLegacy],
  );

  if (!intel || !overview) {
    return (
      <main className="mx-auto max-w-4xl px-8 py-16 text-center">
        <p className="font-serif text-2xl font-semibold">No structured data available</p>
        <p className="mt-3 text-[15px] text-muted-foreground">
          This report was generated before structured intelligence output was enabled.
          Run a new search to populate the database view.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-7xl px-8 py-10">
      <section className="mb-8 border-b border-border pb-8">
        <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Structured Technology Intelligence · {report.questions_file}
        </p>
        <h1 className="mb-4 font-serif text-[40px] font-semibold leading-tight tracking-tight">
          {displayValue(overview.technology_name || report.technology)}
        </h1>
        <RetrievalSummaryBar report={report} />
        {(intel.warnings?.length ?? 0) > 0 && (
          <div className="mt-4 rounded-md border border-confidence-medium/30 bg-confidence-medium-bg/40 p-4">
            <p className="text-[13px] font-semibold text-confidence-medium">Warnings</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-foreground/80">
              {intel.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <nav className="mb-8 flex flex-wrap gap-2 border-b border-border pb-4">
        {visibleTabs.map((item) => (
          <button
            key={item}
            onClick={() => setTab(item)}
            className={
              "rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors " +
              (tab === item
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-foreground")
            }
          >
            {item}
          </button>
        ))}
      </nav>

      {tab === "Overview" && <OverviewSection overview={overview} />}
      {tab === "Metrics" && <MetricsSection metrics={intel.metrics ?? []} />}
      {tab === "Companies" && <CompaniesSection companies={intel.companies ?? []} />}
      {tab === "Projects" && (
        <ProjectsSection projects={intel.pilot_demonstration_projects ?? []} />
      )}
      {tab === "Evidence" && (
        <EvidenceSection
          sources={intel.evidence_sources ?? []}
          missingFields={intel.missing_fields ?? []}
        />
      )}
      {tab === "Summary" && <SummarySection summary={report.executive_summary} />}
      {tab === "Legacy Q&A" && hasLegacy && (
        <LegacyQASection answers={report.legacy_answers} />
      )}
    </main>
  );
}

function RetrievalSummaryBar({ report }: { report: ResearchReport }) {
  const { internet_sources_found, scientific_paper_sources_found } =
    report.retrieval_summary;
  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-3">
      <Stat label="Internet Sources" value={String(internet_sources_found)} />
      <Stat label="Scientific Papers" value={String(scientific_paper_sources_found)} />
      <Stat
        label="Extraction Mode"
        value="Structured"
        sub="Standardized categories & metrics"
      />
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="bg-card p-4">
      <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 font-serif text-xl font-semibold">{value}</p>
      {sub && <p className="mt-1 text-[12px] text-muted-foreground">{sub}</p>}
    </div>
  );
}

function OverviewSection({
  overview,
}: {
  overview: ResearchReport["intelligence"]["technology_overview"];
}) {
  const rows: [string, string][] = [
    ["Technology name", displayValue(overview.technology_name)],
    ["Main category", displayValue(overview.main_category)],
    ["Subcategory", displayValue(overview.subcategory)],
    ["CCS subcategory", displayValue(overview.ccs_subcategory)],
    ["Deployment stage", displayValue(overview.deployment_stage)],
    ["TRL", displayValue(overview.trl)],
    ["Developing organizations", displayList(overview.organizations)],
    ["Deployment partners", displayList(overview.deployment_partners)],
    ["Geography / region", displayList(overview.geography)],
    ["Source confidence", displayValue(overview.source_confidence)],
  ];

  return (
    <section>
      <SectionTitle>Technology Overview</SectionTitle>
      <div className="overflow-hidden rounded-md border border-border">
        <table className="w-full text-left text-[14px]">
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label} className="border-b border-border last:border-0">
                <th className="w-1/3 bg-muted/30 px-4 py-3 font-mono text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
                  {label}
                </th>
                <td className="px-4 py-3 text-foreground/90">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MetricsSection({ metrics }: { metrics: MetricIntel[] }) {
  if (metrics.length === 0) {
    return <EmptyState message="No quantitative metrics were reported in the retrieved sources." />;
  }
  return (
    <section>
      <SectionTitle>Technical and Environmental Metrics</SectionTitle>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="min-w-full text-left text-[13px]">
          <thead className="bg-muted/30">
            <tr>
              {[
                "Metric",
                "Value",
                "Unit",
                "Normalized",
                "Source",
                "Confidence",
                "Notes",
              ].map((h) => (
                <th
                  key={h}
                  className="px-3 py-2 font-mono text-[10px] font-medium uppercase tracking-widest text-muted-foreground"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map((m, i) => (
              <tr key={`${m.metric_name}-${i}`} className="border-t border-border">
                <td className="px-3 py-2 font-medium">{displayValue(m.metric_name)}</td>
                <td className="px-3 py-2">{displayValue(m.value)}</td>
                <td className="px-3 py-2">{displayValue(m.unit)}</td>
                <td className="px-3 py-2">
                  {m.normalized_value != null
                    ? `${m.normalized_value} ${m.normalized_unit || ""}`.trim()
                    : "Not Reported"}
                </td>
                <td className="max-w-[180px] truncate px-3 py-2">{displayValue(m.source)}</td>
                <td className="px-3 py-2">{displayValue(m.confidence)}</td>
                <td className="max-w-[220px] px-3 py-2 text-muted-foreground">
                  {displayValue(m.notes)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CompaniesSection({ companies }: { companies: CompanyIntel[] }) {
  if (companies.length === 0) {
    return (
      <EmptyState message="No companies or organizations were identified in the retrieved sources." />
    );
  }
  return (
    <section>
      <SectionTitle>Companies and Organizations</SectionTitle>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="min-w-full text-left text-[13px]">
          <thead className="bg-muted/30">
            <tr>
              {["Name", "Role", "Technology", "Projects", "Source", "Notes"].map((h) => (
                <th
                  key={h}
                  className="px-3 py-2 font-mono text-[10px] font-medium uppercase tracking-widest text-muted-foreground"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {companies.map((c, i) => (
              <tr key={`${c.name}-${i}`} className="border-t border-border">
                <td className="px-3 py-2 font-medium">{displayValue(c.name)}</td>
                <td className="px-3 py-2">{displayValue(c.role)}</td>
                <td className="px-3 py-2">{displayValue(c.associated_technology)}</td>
                <td className="px-3 py-2">{displayList(c.associated_projects)}</td>
                <td className="max-w-[160px] truncate px-3 py-2">
                  {c.website_or_source ? (
                    <a
                      href={c.website_or_source}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                      Link <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : (
                    "Not Reported"
                  )}
                </td>
                <td className="max-w-[200px] px-3 py-2 text-muted-foreground">
                  {displayValue(c.notes)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ProjectsSection({
  projects,
}: {
  projects: PilotDemonstrationProjectIntel[];
}) {
  if (projects.length === 0) {
    return (
      <EmptyState message="No pilot or demonstration projects were identified in the retrieved sources." />
    );
  }
  return (
    <section className="space-y-3">
      <SectionTitle>Pilot and Demonstration Projects</SectionTitle>
      {projects.map((p, i) => (
        <ProjectCard key={`${p.project_name}-${i}`} project={p} />
      ))}
    </section>
  );
}

function ProjectCard({ project }: { project: PilotDemonstrationProjectIntel }) {
  const [open, setOpen] = useState(true);
  return (
    <article className="overflow-hidden rounded-md border border-border bg-card">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left hover:bg-accent/40"
      >
        <div>
          <p className="font-serif text-[17px] font-semibold">
            {displayValue(project.project_name)}
          </p>
          <p className="mt-1 text-[13px] text-muted-foreground">
            {displayValue(project.stage)} · {displayValue(project.location)}
          </p>
        </div>
        <ChevronDown
          className={
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform " +
            (open ? "rotate-180" : "")
          }
        />
      </button>
      {open && (
        <div className="border-t border-border px-4 py-4">
          <dl className="grid gap-3 sm:grid-cols-2">
            {[
              ["Associated technology", displayValue(project.associated_technology)],
              ["Organizations", displayList(project.organizations)],
              ["Scale / capacity", displayValue(project.scale_or_capacity)],
              ["CO₂ captured/reduced", displayValue(project.co2_captured_or_reduced)],
              ["Funding", displayValue(project.funding_amount)],
              ["Start year", displayValue(project.start_year)],
              ["End year / status", displayValue(project.end_year_or_status)],
              ["Key partners", displayList(project.key_partners)],
              ["Confidence", displayValue(project.confidence)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  {label}
                </dt>
                <dd className="mt-1 text-[14px] text-foreground/90">{value}</dd>
              </div>
            ))}
          </dl>
          {project.source && (
            <p className="mt-3 text-[13px]">
              <span className="text-muted-foreground">Source: </span>
              <a
                href={project.source}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                {project.source}
              </a>
            </p>
          )}
          {project.evidence_notes && project.evidence_notes !== "Not Reported" && (
            <p className="mt-3 rounded-md bg-muted/30 p-3 text-[13px] leading-relaxed text-foreground/80">
              {project.evidence_notes}
            </p>
          )}
        </div>
      )}
    </article>
  );
}

function EvidenceSection({
  sources,
  missingFields,
}: {
  sources: ResearchReport["intelligence"]["evidence_sources"];
  missingFields: string[];
}) {
  return (
    <section className="space-y-6">
      <div>
        <SectionTitle>Evidence and Sources</SectionTitle>
        {sources.length === 0 ? (
          <EmptyState message="No evidence sources were linked to extracted fields." />
        ) : (
          <ul className="space-y-3">
            {sources.map((s, i) => (
              <li
                key={`${s.title}-${i}`}
                className="rounded-md border border-border bg-card p-4"
              >
                <p className="font-medium">{displayValue(s.title)}</p>
                <p className="mt-1 text-[12px] text-muted-foreground">
                  {displayValue(s.source_type)}
                  {s.relevant_fields?.length
                    ? ` · Fields: ${s.relevant_fields.join(", ")}`
                    : ""}
                </p>
                {s.url_or_reference && (
                  <a
                    href={s.url_or_reference}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 inline-flex items-center gap-1 text-[13px] text-primary hover:underline"
                  >
                    {s.url_or_reference}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
                {s.snippet && s.snippet !== "Not Reported" && (
                  <p className="mt-2 text-[13px] leading-relaxed text-foreground/80">
                    {s.snippet}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      {missingFields.length > 0 && (
        <div>
          <h3 className="mb-2 font-serif text-lg font-semibold">Missing Fields</h3>
          <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">
            {missingFields.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function SummarySection({ summary }: { summary: string }) {
  if (!summary?.trim()) {
    return <EmptyState message="Executive summary was not generated for this report." />;
  }
  return (
    <section>
      <SectionTitle>Executive Summary</SectionTitle>
      <div className="space-y-4 font-serif text-[17px] leading-[1.75] text-foreground/90">
        {summary.split("\n\n").map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>
    </section>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-4 font-serif text-2xl font-semibold tracking-tight">{children}</h2>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-dashed border-border bg-muted/20 px-6 py-10 text-center">
      <p className="text-[14px] text-muted-foreground">{message}</p>
    </div>
  );
}
