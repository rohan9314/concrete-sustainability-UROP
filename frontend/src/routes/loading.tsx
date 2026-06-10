import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { pollResearchJob, PROGRESS_LABELS } from "@/lib/api";
import { setReport } from "@/lib/research-store";

type Search = { topic?: string; set?: string; jobId?: string };

const STEP_ORDER = [
  "preparing_question_set",
  "searching_local_papers",
  "searching_internet",
  "analyzing_evidence",
  "generating_report",
];

export const Route = createFileRoute("/loading")({
  validateSearch: (s: Record<string, unknown>): Search => ({
    topic: typeof s.topic === "string" ? s.topic : undefined,
    set: typeof s.set === "string" ? s.set : undefined,
    jobId: typeof s.jobId === "string" ? s.jobId : undefined,
  }),
  component: LoadingPage,
});

function LoadingPage() {
  const { topic, set, jobId } = Route.useSearch();
  const navigate = useNavigate();
  const [activeStep, setActiveStep] = useState(0);
  const [message, setMessage] = useState("Queued for processing...");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!topic || !jobId) {
      navigate({ to: "/" });
      return;
    }

    const { promise, cancel } = pollResearchJob(jobId, (job) => {
      if (job.status === "running" && job.progress) {
        const stepIndex = STEP_ORDER.indexOf(job.progress.step);
        setActiveStep(stepIndex >= 0 ? stepIndex + 1 : 1);
        setMessage(job.progress.message);
      }
      if (job.status === "queued") {
        setActiveStep(0);
        setMessage("Queued for processing...");
      }
    });

    promise
      .then((result) => {
        setReport(result);
        navigate({ to: "/report" });
      })
      .catch((err: Error) => {
        setError(err.message);
      });

    return cancel;
  }, [topic, set, jobId, navigate]);

  const steps = STEP_ORDER.map((key) => PROGRESS_LABELS[key] || key);

  return (
    <div className="flex min-h-screen items-center justify-center px-8">
      <div className="w-full max-w-xl">
        <p className="mb-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          {topic} · {set}
        </p>
        <h1 className="mb-3 font-serif text-3xl font-semibold tracking-tight">
          Research in Progress
        </h1>
        <p className="mb-10 text-[15px] leading-relaxed text-muted-foreground">
          Research reports may take several minutes while local papers are loaded and
          answers are generated.
        </p>

        {error ? (
          <div className="rounded-md border border-confidence-low/30 bg-confidence-low-bg/60 p-4">
            <p className="text-[14px] font-semibold text-confidence-low">
              Research failed
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-foreground/80">
              {error}
            </p>
            <button
              onClick={() => navigate({ to: "/" })}
              className="mt-4 inline-flex h-9 items-center rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground"
            >
              Back to Search
            </button>
          </div>
        ) : (
          <>
            <p className="mb-6 text-[14px] text-muted-foreground">{message}</p>
            <ol className="space-y-3 border-l border-border pl-6">
              {steps.map((label, i) => {
                const done = i < activeStep;
                const active = i === activeStep;
                return (
                  <li key={label} className="relative flex items-center gap-3">
                    <span className="absolute -left-[33px] flex h-5 w-5 items-center justify-center rounded-full border border-border bg-background">
                      {done ? (
                        <Check
                          className="h-3 w-3 text-confidence-high"
                          strokeWidth={2.5}
                        />
                      ) : active ? (
                        <Loader2 className="h-3 w-3 animate-spin text-foreground" />
                      ) : (
                        <span className="h-1.5 w-1.5 rounded-full bg-border" />
                      )}
                    </span>
                    <span
                      className={
                        done
                          ? "text-[14px] text-foreground"
                          : active
                            ? "text-[14px] font-medium text-foreground"
                            : "text-[14px] text-muted-foreground"
                      }
                    >
                      {label}
                    </span>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
