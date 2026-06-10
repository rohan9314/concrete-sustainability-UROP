import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { getReport } from "@/lib/research-store";
import type { Answer, Confidence, ResearchReport, SourceType } from "@/lib/research-types";
import {
  ArrowLeft,
  ChevronDown,
  Download,
  ExternalLink,
  Globe,
  FileText,
  AlertTriangle,
} from "lucide-react";

export const Route = createFileRoute("/report")({
  component: ReportPage,
});

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function ReportPage() {
  const navigate = useNavigate();
  const [report, setReportState] = useState<ResearchReport | null>(null);

  useEffect(() => {
    const r = getReport();
    if (!r) navigate({ to: "/" });
    else setReportState(r);
  }, [navigate]);

  if (!report) return null;
  return <ReportView report={report} />;
}

function ReportView({ report }: { report: ResearchReport }) {
  const navigate = useNavigate();
  const sections = useMemo(
    () => report.answers.map((a) => ({ id: slug(a.question), label: a.question })),
    [report],
  );

  function downloadJson() {
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slug(report.technology)}-report.json`;
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
              <SidebarLink href="#executive-summary" label="Executive Summary" />
              {sections.map((s, i) => (
                <SidebarLink
                  key={s.id}
                  href={`#${s.id}`}
                  label={`${String(i + 1).padStart(2, "0")}. ${s.label}`}
                />
              ))}
            </nav>
          </div>
        </aside>

        <main className="min-w-0">
          <section className="mb-12 border-b border-border pb-10">
            <p className="mb-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              Research Report · Question Set: {report.questions_file} ·{" "}
              {report.answers.length} questions
            </p>
            <h1 className="mb-6 font-serif text-[40px] font-semibold leading-tight tracking-tight">
              {report.technology}
            </h1>
            <RetrievalSummary report={report} />
          </section>

          <section id="executive-summary" className="mb-14 scroll-mt-24">
            <h2 className="mb-5 font-serif text-2xl font-semibold tracking-tight">
              Executive Summary
            </h2>
            <div className="space-y-4 font-serif text-[17px] leading-[1.75] text-foreground/90">
              {report.executive_summary.split("\n\n").map((p, i) => (
                <p key={i}>{p}</p>
              ))}
            </div>
          </section>

          <section>
            <h2 className="mb-6 font-serif text-2xl font-semibold tracking-tight">
              Findings ({report.answers.length})
            </h2>
            <div className="space-y-4">
              {report.answers.map((a, i) => (
                <AnswerCard key={a.question} answer={a} index={i + 1} />
              ))}
            </div>
          </section>
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

function RetrievalSummary({ report }: { report: ResearchReport }) {
  const {
    internet_sources_found,
    scientific_paper_sources_found,
    local_paper_database_enabled,
  } = report.retrieval_summary;
  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-3">
      <Metric
        label="Internet Sources"
        value={internet_sources_found.toString()}
        sub="Found"
      />
      <Metric
        label="Scientific Papers"
        value={scientific_paper_sources_found.toString()}
        sub="Found"
      />
      <Metric
        label="Local Paper Database"
        value={local_paper_database_enabled ? "Enabled" : "Not Available"}
        sub={
          local_paper_database_enabled
            ? "Provided paper dataset"
            : "Database unavailable for this run"
        }
        muted={!local_paper_database_enabled}
      />
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  muted,
}: {
  label: string;
  value: string;
  sub: string;
  muted?: boolean;
}) {
  return (
    <div className="bg-card p-5">
      <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
        {label}
      </p>
      <p
        className={
          "mt-2 font-serif text-2xl font-semibold tracking-tight " +
          (muted ? "text-muted-foreground" : "text-foreground")
        }
      >
        {value}
      </p>
      <p className="mt-1 text-[12px] text-muted-foreground">{sub}</p>
    </div>
  );
}

function AnswerCard({ answer, index }: { answer: Answer; index: number }) {
  const [open, setOpen] = useState(true);
  const notFound = answer.answer.trim() === "Not Found";
  return (
    <article
      id={slug(answer.question)}
      className="scroll-mt-24 overflow-hidden rounded-md border border-border bg-card"
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start justify-between gap-4 px-6 py-5 text-left transition-colors hover:bg-accent/40"
      >
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center gap-2">
            <span className="font-mono text-[11px] tracking-widest text-muted-foreground">
              Q{String(index).padStart(2, "0")}
            </span>
            <ConfidenceBadge confidence={answer.confidence} />
            {answer.source_type_used.map((t) => (
              <SourceBadge key={t} type={t} />
            ))}
          </div>
          <h3 className="font-serif text-[19px] font-semibold leading-snug tracking-tight">
            {answer.question}
          </h3>
        </div>
        <ChevronDown
          className={
            "mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform " +
            (open ? "rotate-180" : "")
          }
          strokeWidth={2}
        />
      </button>

      {open && (
        <div className="border-t border-border px-6 py-6">
          {notFound ? (
            <div className="flex gap-3 rounded-md border border-confidence-low/30 bg-confidence-low-bg/60 p-4">
              <AlertTriangle
                className="mt-0.5 h-4 w-4 shrink-0 text-confidence-low"
                strokeWidth={2}
              />
              <div>
                <p className="text-[14px] font-semibold text-confidence-low">
                  Information Not Available
                </p>
                <p className="mt-1 text-[13px] leading-relaxed text-foreground/80">
                  The agent was unable to find authoritative sources for this question.
                </p>
              </div>
            </div>
          ) : (
            <p className="font-serif text-[16px] leading-[1.75] text-foreground/90">
              {answer.answer}
            </p>
          )}

          {answer.sources.length > 0 && (
            <div className="mt-6 border-t border-border pt-4">
              <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                Sources ({answer.sources.length})
              </p>
              <ul className="space-y-2">
                {answer.sources.map((s, i) => (
                  <li
                    key={i}
                    className="flex items-start justify-between gap-4 rounded border border-border/70 bg-background px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <div className="mb-1.5">
                        <SourceBadge type={normalizeSourceType(s.source_type)} />
                      </div>
                      <p className="truncate text-[13px] font-medium text-foreground">
                        {s.title}
                      </p>
                      <p className="truncate text-[12px] text-muted-foreground">
                        {s.url}
                      </p>
                    </div>
                    {s.url && (
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex shrink-0 items-center gap-1 rounded border border-border bg-card px-2.5 py-1 text-[12px] font-medium transition-colors hover:bg-accent"
                      >
                        Open
                        <ExternalLink className="h-3 w-3" strokeWidth={2} />
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function ConfidenceBadge({ confidence }: { confidence: string }) {
  const normalized: Confidence = ["High", "Medium", "Low"].includes(confidence)
    ? (confidence as Confidence)
    : "Low";
  const styles: Record<Confidence, string> = {
    High: "bg-confidence-high-bg text-confidence-high",
    Medium: "bg-confidence-medium-bg text-confidence-medium",
    Low: "bg-confidence-low-bg text-confidence-low",
  };
  return (
    <span
      className={
        "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-widest " +
        styles[normalized]
      }
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {normalized}
    </span>
  );
}

function normalizeSourceType(type: string): SourceType {
  return type === "internet" ? "internet" : "scientific_paper";
}

function SourceBadge({ type }: { type: SourceType }) {
  if (type === "internet") {
    return (
      <span className="inline-flex items-center gap-1 rounded-sm bg-source-internet-bg px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-widest text-source-internet">
        <Globe className="h-2.5 w-2.5" strokeWidth={2.5} />
        Internet
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-sm bg-source-paper-bg px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-widest text-source-paper">
      <FileText className="h-2.5 w-2.5" strokeWidth={2.5} />
      Scientific Paper
    </span>
  );
}
