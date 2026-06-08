import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { evaluateTechnology } from "@/lib/api";
import { setEvaluation } from "@/lib/evaluation-store";

type Search = { technology?: string };

export const Route = createFileRoute("/loading")({
  validateSearch: (s: Record<string, unknown>): Search => ({
    technology: typeof s.technology === "string" ? s.technology : undefined,
  }),
  component: LoadingPage,
});

function LoadingPage() {
  const { technology } = Route.useSearch();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!technology) {
      navigate({ to: "/" });
      return;
    }

    let cancelled = false;

    evaluateTechnology(technology)
      .then((evaluation) => {
        if (cancelled) return;
        setEvaluation(evaluation);
        navigate({ to: "/report" });
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, [technology, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center px-8">
      <div className="w-full max-w-xl">
        <p className="mb-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          {technology}
        </p>
        <h1 className="mb-3 font-serif text-3xl font-semibold tracking-tight">
          Generating Evaluation
        </h1>

        {error ? (
          <div className="rounded-md border border-confidence-low/30 bg-confidence-low-bg/60 p-4">
            <p className="text-[14px] font-semibold text-confidence-low">
              Evaluation failed
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
          <div className="flex items-center gap-3 text-[15px] text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            Requesting standardized evaluation from backend...
          </div>
        )}
      </div>
    </div>
  );
}
