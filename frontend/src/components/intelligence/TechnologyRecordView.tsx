import type { ReactNode } from "react";
import type { ReactNode } from "react";
import type { TechnologyRecord } from "@/lib/technology-record";
import {
  confidenceClass,
  coverageLabel,
  displayValue,
  FIELD_LABELS,
  fieldStatus,
  isReported,
  NOT_REPORTED,
} from "@/lib/technology-record";
import { CitationText, SourcesBibliography } from "./SourcesBibliography";
import { sourceMap } from "@/lib/source-registry";

export function TechnologyRecordView({ record }: { record: TechnologyRecord }) {
  const registry = sourceMap(record.sources);
  return (
    <main className="mx-auto max-w-7xl px-8 py-10">
      <section className="mb-8 border-b border-border pb-8">
        <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Prepared Technology Database
        </p>
        <h1 className="mb-4 font-serif text-[40px] font-semibold leading-tight tracking-tight">
          {displayValue(record.technology_name)}
        </h1>
        <CoverageSection record={record} />
      </section>

      <div className="grid gap-8 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-8">
          <FieldSection title="Overview">
            <FieldRow
              label="Category"
              value={displayValue(record.technology_category)}
              status={fieldStatus("technology_category", record)}
              confidence={record.confidence_by_field.technology_category}
            />
            <FieldRow
              label="Company / Organization"
              value={displayValue(record.company_or_organization)}
              status={fieldStatus("company_or_organization", record)}
              confidence={record.confidence_by_field.company_or_organization}
            />
            <FieldRow
              label="Deployment Stage"
              value={displayValue(record.deployment_stage)}
              status={fieldStatus("deployment_stage", record)}
              confidence={record.confidence_by_field.deployment_stage}
            />
            <FieldRow
              label="Technical Description"
              value={displayValue(record.technical_description)}
              status={fieldStatus("technical_description", record)}
              confidence={record.confidence_by_field.technical_description}
            />
            <FieldRow
              label="Replaces or Improves"
              value={displayValue(record.replaces_or_improves)}
              status={fieldStatus("replaces_or_improves", record)}
              confidence={record.confidence_by_field.replaces_or_improves}
            />
          </FieldSection>

          <FieldSection title="Performance Metrics">
            <FieldRow
              label="Metric Tags"
              value={
                record.performance_metrics.length > 0
                  ? record.performance_metrics.join(", ")
                  : NOT_REPORTED
              }
              status={fieldStatus("performance_metrics", record)}
              confidence={record.confidence_by_field.performance_metrics}
            />
            <FieldRow
              label="GHG Reduction (%)"
              value={displayValue(record.reported_ghg_reduction_percent)}
              renderedValue={
                <CitationText
                  text={displayValue(record.reported_ghg_reduction_percent)}
                  registry={registry}
                />
              }
              status={fieldStatus("reported_ghg_reduction_percent", record)}
              confidence={record.confidence_by_field.reported_ghg_reduction_percent}
            />
            <FieldRow
              label="Emissions Intensity (kg CO2e)"
              value={displayValue(record.absolute_emissions_intensity_kg_co2e)}
              status={fieldStatus("absolute_emissions_intensity_kg_co2e", record)}
              confidence={record.confidence_by_field.absolute_emissions_intensity_kg_co2e}
            />
            <FieldRow
              label="Energy Reduction (%)"
              value={displayValue(record.energy_reduction_percent)}
              status={fieldStatus("energy_reduction_percent", record)}
              confidence={record.confidence_by_field.energy_reduction_percent}
            />
            <FieldRow
              label="Cost Reduction (%)"
              value={displayValue(record.cost_reduction_percent)}
              status={fieldStatus("cost_reduction_percent", record)}
              confidence={record.confidence_by_field.cost_reduction_percent}
            />
          </FieldSection>

          <FieldSection title="Projects">
            <ProjectList
              label="Pilot Projects"
              projects={record.pilot_projects}
              status={fieldStatus("pilot_projects", record)}
            />
            <ProjectList
              label="Demonstration Projects"
              projects={record.demonstration_projects}
              status={fieldStatus("demonstration_projects", record)}
            />
          </FieldSection>

          <FieldSection title="Sources">
            <SourcesBibliography
              sources={record.sources}
              sourcesUsed={record.sources_used}
              sourcesConsidered={record.sources_considered}
              citationWarnings={record.citation_warnings}
            />
          </FieldSection>
        </div>

        <aside className="space-y-6">
          <ConfidencePanel record={record} />
          {record.extraction_notes.length > 0 && (
            <div className="rounded-md border border-border bg-card p-4">
              <h3 className="text-[13px] font-semibold uppercase tracking-widest text-muted-foreground">
                Extraction Notes
              </h3>
              <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px] text-foreground/80">
                {record.extraction_notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

function CoverageSection({ record }: { record: TechnologyRecord }) {
  return (
    <div className="rounded-md border border-border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Coverage
          </p>
          <p className="mt-1 text-[24px] font-semibold">{coverageLabel(record)}</p>
        </div>
        <div className="text-right">
          <p className="text-[13px] text-muted-foreground">Coverage score</p>
          <p className="text-[20px] font-semibold">
            {Math.round(record.coverage_score * 100)}%
          </p>
        </div>
      </div>
      {record.missing_fields.length > 0 && (
        <div className="mt-4 border-t border-border pt-4">
          <p className="mb-2 text-[13px] font-medium">Missing fields</p>
          <div className="flex flex-wrap gap-2">
            {record.missing_fields.map((field) => (
              <span
                key={field}
                className="rounded-full border border-border bg-background px-2.5 py-1 text-[12px] text-muted-foreground"
              >
                {FIELD_LABELS[field] ?? field}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ConfidencePanel({ record }: { record: TechnologyRecord }) {
  const entries = Object.entries(record.confidence_by_field);
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <h3 className="text-[13px] font-semibold uppercase tracking-widest text-muted-foreground">
        Confidence by Field
      </h3>
      {entries.length === 0 ? (
        <p className="mt-3 text-[13px] text-muted-foreground">{NOT_REPORTED}</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {entries.map(([field, level]) => (
            <li key={field} className="flex items-center justify-between gap-3 text-[13px]">
              <span className="text-foreground/80">{FIELD_LABELS[field] ?? field}</span>
              <span className={confidenceClass(level)}>{level}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FieldSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-card p-5">
      <h2 className="mb-4 font-serif text-[22px] font-semibold">{title}</h2>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function FieldRow({
  label,
  value,
  renderedValue,
  status,
  confidence,
}: {
  label: string;
  value: string;
  renderedValue?: ReactNode;
  status: "Reported" | "Not Reported" | "Low Confidence";
  confidence?: string;
}) {
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <p className="text-[12px] font-medium uppercase tracking-widest text-muted-foreground">
          {label}
        </p>
        <StatusBadge status={status} />
        {confidence && confidence !== NOT_REPORTED && (
          <span className={`text-[11px] ${confidenceClass(confidence as never)}`}>
            {confidence}
          </span>
        )}
      </div>
      <p className="text-[15px] leading-relaxed text-foreground/90">
        {renderedValue ?? value}
      </p>
    </div>
  );
}

function StatusBadge({
  status,
}: {
  status: "Reported" | "Not Reported" | "Low Confidence";
}) {
  const classes =
    status === "Reported"
      ? "border-confidence-high/30 bg-confidence-high-bg text-confidence-high"
      : status === "Low Confidence"
        ? "border-confidence-medium/30 bg-confidence-medium-bg text-confidence-medium"
        : "border-border bg-muted text-muted-foreground";

  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${classes}`}>
      {status}
    </span>
  );
}

function ProjectList({
  label,
  projects,
  status,
}: {
  label: string;
  projects: TechnologyRecord["pilot_projects"];
  status: "Reported" | "Not Reported" | "Low Confidence";
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <p className="text-[12px] font-medium uppercase tracking-widest text-muted-foreground">
          {label}
        </p>
        <StatusBadge status={status} />
      </div>
      {projects.length === 0 ? (
        <p className="text-[14px] text-muted-foreground">{NOT_REPORTED}</p>
      ) : (
        <ul className="space-y-3">
          {projects.map((project) => (
            <li key={project.name} className="rounded-md border border-border p-3">
              <p className="font-medium">{project.name}</p>
              {isReported(project.description) && (
                <p className="mt-1 text-[13px] text-foreground/80">{project.description}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
