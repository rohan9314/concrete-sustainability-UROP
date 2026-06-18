import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getStoredReport } from "@/lib/research-store";
import { downloadReportJson, downloadReportTxt } from "@/lib/report-export";
import { StructuredReport } from "@/components/intelligence/StructuredReport";
import { TechnologyRecordView } from "@/components/intelligence/TechnologyRecordView";
import { ArrowLeft, Download, FileText } from "lucide-react";

export const Route = createFileRoute("/report")({
  component: ReportPage,
});

function ReportPage() {
  const navigate = useNavigate();
  const [stored, setStored] = useState(getStoredReport());

  useEffect(() => {
    const current = getStoredReport();
    if (!current) navigate({ to: "/" });
    else setStored(current);
  }, [navigate]);

  if (!stored) return null;

  if (stored.mode === "database" && stored.technologyRecord) {
    return <DatabaseReportView record={stored.technologyRecord} />;
  }

  if (stored.mode === "live" && stored.liveReport) {
    return <LiveReportView report={stored.liveReport} />;
  }

  return null;
}

function DatabaseReportView({
  record,
}: {
  record: NonNullable<ReturnType<typeof getStoredReport>>["technologyRecord"];
}) {
  const navigate = useNavigate();
  if (!record) return null;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-8 py-4">
          <Link
            to="/"
            className="flex items-center gap-2 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" strokeWidth={2} />
            Technology Database
          </Link>
          <button
            onClick={() => navigate({ to: "/" })}
            className="inline-flex h-9 items-center rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            New Search
          </button>
        </div>
      </header>
      <TechnologyRecordView record={record} />
    </div>
  );
}

function LiveReportView({
  report,
}: {
  report: NonNullable<ReturnType<typeof getStoredReport>>["liveReport"];
}) {
  const navigate = useNavigate();
  if (!report) return null;

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
              onClick={() => downloadReportJson(report)}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-[13px] font-medium transition-colors hover:bg-accent"
            >
              <Download className="h-3.5 w-3.5" strokeWidth={2} />
              JSON
            </button>
            <button
              onClick={() => downloadReportTxt(report)}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-[13px] font-medium transition-colors hover:bg-accent"
            >
              <FileText className="h-3.5 w-3.5" strokeWidth={2} />
              TXT
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
