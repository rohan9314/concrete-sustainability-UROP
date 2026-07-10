import type { ReactNode } from "react";
import type { CarbonCaptureRecord } from "@/lib/carbon-capture-record";
import {
  CARBON_CAPTURE_FIELD_LABELS,
  displayCarbonCaptureValue,
  isNA,
  NA,
  PRIORITY_DISPLAY_FIELDS,
  TABLE_DISPLAY_FIELDS,
} from "@/lib/carbon-capture-record";

export function CarbonCaptureRecordView({ record }: { record: CarbonCaptureRecord }) {
  return (
    <main className="mx-auto max-w-7xl px-8 py-10">
      <section className="mb-8 border-b border-border pb-8">
        <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Carbon Capture Extraction
        </p>
        <h1 className="mb-2 font-serif text-[40px] font-semibold leading-tight tracking-tight">
          {displayCarbonCaptureValue(record.technology_type)}
        </h1>
        <p className="text-[15px] text-muted-foreground">
          {displayCarbonCaptureValue(record.subcategory)}
        </p>
      </section>

      <div className="grid gap-8 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-8">
          <FieldSection title="Technology & Project">
            {PRIORITY_DISPLAY_FIELDS.filter((field) =>
              [
                "subcategory",
                "technology_type",
                "company_or_organization",
                "project_name",
                "project_year",
                "project_location",
                "deployment_stage",
              ].includes(field),
            ).map((field) => (
              <FieldRow
                key={field}
                label={CARBON_CAPTURE_FIELD_LABELS[field]}
                value={displayCarbonCaptureValue(record[field])}
              />
            ))}
          </FieldSection>

          <FieldSection title="Impacts & Metrics">
            {(["co2_reduction", "energy_impact", "cost_impact"] as const).map((field) => (
              <FieldRow
                key={field}
                label={CARBON_CAPTURE_FIELD_LABELS[field]}
                value={displayCarbonCaptureValue(record[field])}
              />
            ))}
            <FieldRow
              label="Metric"
              value={formatMetric(record)}
            />
            <FieldRow
              label={CARBON_CAPTURE_FIELD_LABELS.primary_barriers}
              value={displayCarbonCaptureValue(record.primary_barriers)}
            />
          </FieldSection>

          <FieldSection title="Source">
            <FieldRow
              label={CARBON_CAPTURE_FIELD_LABELS.source_type}
              value={displayCarbonCaptureValue(record.source_type)}
            />
            <FieldRow
              label={CARBON_CAPTURE_FIELD_LABELS.source_url_or_citation}
              value={displayCarbonCaptureValue(record.source_url_or_citation)}
              isLink={!isNA(record.source_url_or_citation)}
            />
          </FieldSection>
        </div>

        <aside className="space-y-6">
          <div className="rounded-md border border-border bg-card p-4">
            <h3 className="text-[13px] font-semibold uppercase tracking-widest text-muted-foreground">
              Confidence
            </h3>
            <p className="mt-3 text-[20px] font-semibold">
              {displayCarbonCaptureValue(record.confidence)}
            </p>
          </div>
          {!isNA(record.notes) && (
            <div className="rounded-md border border-border bg-card p-4">
              <h3 className="text-[13px] font-semibold uppercase tracking-widest text-muted-foreground">
                Notes
              </h3>
              <p className="mt-3 text-[13px] leading-relaxed text-foreground/80">
                {record.notes}
              </p>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

export function CarbonCaptureRecordTable({
  records,
}: {
  records: CarbonCaptureRecord[];
}) {
  if (records.length === 0) {
    return <p className="text-[14px] text-muted-foreground">{NA}</p>;
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="min-w-full text-left text-[13px]">
        <thead className="bg-muted/40">
          <tr>
            {TABLE_DISPLAY_FIELDS.map((field) => (
              <th key={field} className="px-3 py-2 font-medium">
                {CARBON_CAPTURE_FIELD_LABELS[field]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((record, index) => (
            <tr key={`${record.source_url_or_citation}-${index}`} className="border-t border-border">
              {TABLE_DISPLAY_FIELDS.map((field) => (
                <td key={field} className="px-3 py-2 align-top text-foreground/90">
                  {displayCarbonCaptureValue(record[field])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatMetric(record: CarbonCaptureRecord): string {
  const parts = [
    displayCarbonCaptureValue(record.metric_name),
    displayCarbonCaptureValue(record.metric_value),
    displayCarbonCaptureValue(record.metric_unit),
    displayCarbonCaptureValue(record.metric_boundary),
  ].filter((part) => !isNA(part));
  return parts.length > 0 ? parts.join(" · ") : NA;
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
  isLink = false,
}: {
  label: string;
  value: string;
  isLink?: boolean;
}) {
  return (
    <div>
      <p className="mb-1 text-[12px] font-medium uppercase tracking-widest text-muted-foreground">
        {label}
      </p>
      {isLink ? (
        <a
          href={value}
          target="_blank"
          rel="noreferrer"
          className="text-[15px] text-primary underline-offset-2 hover:underline"
        >
          {value}
        </a>
      ) : (
        <p className="text-[15px] leading-relaxed text-foreground/90">{value}</p>
      )}
    </div>
  );
}
