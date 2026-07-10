import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { fetchCarbonCaptureRecords } from "@/lib/api";
import type { CarbonCaptureRecord } from "@/lib/carbon-capture-record";
import { CarbonCaptureRecordTable } from "@/components/intelligence/CarbonCaptureRecordView";

export const Route = createFileRoute("/carbon-capture")({
  head: () => ({
    meta: [
      { title: "Carbon Capture Pipeline Results" },
      {
        name: "description",
        content: "Canonical carbon capture extraction records from the offline pipeline.",
      },
    ],
  }),
  component: CarbonCapturePage,
});

function CarbonCapturePage() {
  const [records, setRecords] = useState<CarbonCaptureRecord[]>([]);
  const [outputs, setOutputs] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCarbonCaptureRecords()
      .then((response) => {
        setRecords(response.records);
        setOutputs(response.outputs);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="mx-auto max-w-7xl px-8 py-10">
      <section className="mb-8 border-b border-border pb-8">
        <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          Carbon Capture Pipeline
        </p>
        <h1 className="font-serif text-[40px] font-semibold leading-tight tracking-tight">
          Canonical Extraction Records
        </h1>
        <p className="mt-3 max-w-3xl text-[15px] text-muted-foreground">
          Machine-readable records from separate literature and web extraction workflows,
          merged conservatively into a single canonical table.
        </p>
      </section>

      {loading && <p className="text-muted-foreground">Loading pipeline records…</p>}
      {error && <p className="text-destructive">{error}</p>}

      {!loading && !error && (
        <div className="space-y-8">
          <div className="rounded-md border border-border bg-card p-5">
            <p className="text-[13px] text-muted-foreground">
              {records.length} record{records.length === 1 ? "" : "s"} loaded
            </p>
            {outputs.final_output_csv && (
              <p className="mt-2 font-mono text-[12px] text-muted-foreground">
                Source: {outputs.final_output_csv}
              </p>
            )}
          </div>
          <CarbonCaptureRecordTable records={records} />
        </div>
      )}
    </main>
  );
}
