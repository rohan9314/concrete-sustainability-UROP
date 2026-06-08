import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { getEvaluation } from "@/lib/evaluation-store";
import type { ConfidenceLevel, TechnologyEvaluation } from "@/types/technologyEvaluation";
import { ArrowLeft, Download, ExternalLink } from "lucide-react";

export const Route = createFileRoute("/report")({
  component: ReportPage,
});

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function displayValue(value: string | null | undefined) {
  if (value === null || value === undefined || value.trim() === "") {
    return "Not available";
  }
  return value;
}

function ReportPage() {
  const navigate = useNavigate();
  const [evaluation, setEvaluationState] = useState<TechnologyEvaluation | null>(null);

  useEffect(() => {
    const data = getEvaluation();
    if (!data) navigate({ to: "/" });
    else setEvaluationState(data);
  }, [navigate]);

  if (!evaluation) return null;
  return <ReportView evaluation={evaluation} />;
}

function ReportView({ evaluation }: { evaluation: TechnologyEvaluation }) {
  const navigate = useNavigate();
  const { overview, technical, environmental, market, evidence } = {
    overview: evaluation.technology_overview,
    technical: evaluation.technical_performance,
    environmental: evaluation.environmental_performance,
    market: evaluation.cost_and_market,
    evidence: evaluation.evidence,
  };

  function downloadJson() {
    const blob = new Blob([JSON.stringify(evaluation, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slug(overview.technology_name)}-evaluation.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-8 py-4">
          <Link
            to="/"
            className="flex items-center gap-2 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" strokeWidth={2} />
            Research Agent
          </Link>
          <div className="flex items-center gap-2">
            <button
              onClick={downloadJson}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-[13px] font-medium transition-colors hover:bg-accent"
            >
              <Download className="h-3.5 w-3.5" strokeWidth={2} />
              Download JSON
            </button>
            <button
              onClick={() => navigate({ to: "/" })}
              className="inline-flex h-9 items-center rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
            >
              New Search
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl grid-cols-[1fr] gap-12 px-8 py-12 lg:grid-cols-[220px_1fr]">
        <aside className="hidden lg:block">
          <div className="sticky top-24">
            <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              Contents
            </p>
            <nav className="space-y-1 border-l border-border">
              <SidebarLink href="#technology-overview" label="Technology Overview" />
              <SidebarLink href="#technical-performance" label="Technical Performance" />
              <SidebarLink href="#environmental-performance" label="Environmental Performance" />
              <SidebarLink href="#cost-and-market" label="Cost and Market" />
              <SidebarLink href="#evidence-confidence" label="Evidence and Confidence" />
              <SidebarLink href="#missing-assumptions" label="Missing / Assumptions" />
            </nav>
          </div>
        </aside>

        <main className="min-w-0 space-y-14">
          <section className="border-b border-border pb-10">
            <p className="mb-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              Technology Evaluation · {evaluation.metadata.generated_by}
            </p>
            <h1 className="mb-4 font-serif text-[40px] font-semibold leading-tight tracking-tight">
              {overview.technology_name}
            </h1>
            <p className="max-w-3xl font-serif text-[17px] leading-[1.75] text-foreground/90">
              {displayValue(overview.short_description)}
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              <ConfidenceBadge level={evidence.confidence_level} />
              <Tag label={overview.deployment_stage} />
              {overview.category.map((c) => (
                <Tag key={c} label={c} />
              ))}
            </div>
          </section>

          <Section id="technology-overview" title="Technology Overview">
            <Field label="Technology Name" value={overview.technology_name} />
            <Field label="Category" value={overview.category.join(", ") || "Not available"} />
            <Field label="Developers" value={overview.developers.join(", ") || "Not available"} />
            <Field label="Deployment Stage" value={overview.deployment_stage} />
            <Field label="TRL" value={displayValue(overview.trl)} />
            <Field label="Short Description" value={overview.short_description} />
          </Section>

          <Section id="technical-performance" title="Technical Performance">
            <Field label="How It Works" value={technical.how_it_works} />
            <Field label="Replaces or Improves" value={technical.replaces_or_improves} />
            <BulletField
              label="Performance Metrics Improved"
              items={technical.performance_metrics_improved}
            />
            <BulletField label="Key Inputs" items={technical.key_inputs} />
            <BulletField label="Key Outputs" items={technical.key_outputs} />
            <BulletField label="Technical Limitations" items={technical.technical_limitations} />
          </Section>

          <Section id="environmental-performance" title="Environmental Performance">
            <Field
              label="Reported GHG Reduction"
              value={displayValue(environmental.reported_ghg_reduction_percent)}
            />
            <Field
              label="Absolute Emissions Intensity"
              value={displayValue(environmental.absolute_emissions_intensity)}
            />
            <BulletField
              label="Lifecycle Stages Affected"
              items={environmental.lifecycle_stage_affected}
            />
            <BulletField label="Environmental Benefits" items={environmental.environmental_benefits} />
            <BulletField
              label="Environmental Tradeoffs"
              items={environmental.environmental_tradeoffs}
            />
          </Section>

          <Section id="cost-and-market" title="Cost and Market">
            <Field
              label="Reported Cost Impact"
              value={displayValue(market.reported_cost_impact)}
            />
            <BulletField label="Cost Drivers" items={market.cost_drivers} />
            <Field label="Commercialization Status" value={market.commercialization_status} />
            <BulletField label="Target Customers" items={market.target_customers} />
            <BulletField label="Adoption Barriers" items={market.adoption_barriers} />
          </Section>

          <Section id="evidence-confidence" title="Evidence and Confidence">
            <div className="mb-4">
              <ConfidenceBadge level={evidence.confidence_level} />
            </div>
            {evidence.sources.length > 0 ? (
              <ul className="space-y-3">
                {evidence.sources.map((source, i) => (
                  <li
                    key={i}
                    className="rounded-md border border-border bg-card px-4 py-3"
                  >
                    <p className="text-[14px] font-medium text-foreground">{source.title}</p>
                    <p className="mt-1 text-[12px] text-muted-foreground">
                      {source.publisher || "Unknown publisher"}
                      {source.year ? ` · ${source.year}` : ""}
                      {` · ${source.source_type}`}
                    </p>
                    {source.url && (
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-foreground/80 hover:text-foreground"
                      >
                        Open source
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[14px] text-muted-foreground">Not available</p>
            )}
          </Section>

          <Section id="missing-assumptions" title="Missing Information / Assumptions">
            <BulletField label="Missing Information" items={evidence.missing_information} />
            <BulletField label="Assumptions" items={evidence.assumptions} />
          </Section>
        </main>
      </div>
    </div>
  );
}

function SidebarLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      className="block border-l-2 border-transparent -ml-px py-1.5 pl-4 text-[13px] leading-snug text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground"
    >
      {label}
    </a>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <h2 className="mb-6 font-serif text-2xl font-semibold tracking-tight">{title}</h2>
      <div className="space-y-5">{children}</div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  const display = displayValue(value);
  const unavailable = display === "Not available";
  return (
    <div>
      <p className="mb-1 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
        {label}
      </p>
      <p
        className={
          "font-serif text-[16px] leading-[1.75] " +
          (unavailable ? "text-muted-foreground italic" : "text-foreground/90")
        }
      >
        {display}
      </p>
    </div>
  );
}

function BulletField({ label, items }: { label: string; items: string[] }) {
  if (!items.length) {
    return <Field label={label} value="" />;
  }
  return (
    <div>
      <p className="mb-2 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
        {label}
      </p>
      <ul className="list-disc space-y-1 pl-5 font-serif text-[16px] leading-[1.75] text-foreground/90">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Tag({ label }: { label: string }) {
  return (
    <span className="rounded-sm border border-border bg-card px-2 py-1 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
      {label}
    </span>
  );
}

function ConfidenceBadge({ level }: { level: ConfidenceLevel }) {
  const styles: Record<ConfidenceLevel, string> = {
    High: "bg-confidence-high-bg text-confidence-high",
    Medium: "bg-confidence-medium-bg text-confidence-medium",
    Low: "bg-confidence-low-bg text-confidence-low",
  };
  return (
    <span
      className={
        "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-widest " +
        styles[level]
      }
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {level} Confidence
    </span>
  );
}
