import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getReport } from "@/lib/research-store";
import type { ResearchReport } from "@/lib/research-types";
import { StructuredReport } from "@/components/intelligence/StructuredReport";
import { ArrowLeft, Download } from "lucide-react";

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

  function downloadJson() {
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slug(report.technology)}-intelligence.json`;
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
            Technology Intelligence
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

      <StructuredReport report={report} />
    </div>
  );
}
