import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";

type Search = { topic?: string; set?: string };

export const Route = createFileRoute("/loading")({
  validateSearch: (s: Record<string, unknown>): Search => ({
    topic: typeof s.topic === "string" ? s.topic : undefined,
    set: typeof s.set === "string" ? s.set : undefined,
  }),
  component: LoadingPage,
});

const STEPS = [
  "Preparing Question Set",
  "Searching Internet Sources",
  "Searching Scientific Literature",
  "Analyzing Evidence",
  "Generating Report",
];

function LoadingPage() {
  const { topic, set } = Route.useSearch();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!topic) {
      navigate({ to: "/" });
      return;
    }
    const timers: ReturnType<typeof setTimeout>[] = [];
    STEPS.forEach((_, i) => {
      timers.push(setTimeout(() => setStep(i + 1), (i + 1) * 900));
    });
    timers.push(
      setTimeout(() => navigate({ to: "/report" }), STEPS.length * 900 + 400),
    );
    return () => timers.forEach(clearTimeout);
  }, [topic, set, navigate]);

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
          Research reports may take 30 seconds to several minutes depending on
          source availability.
        </p>

        <ol className="space-y-3 border-l border-border pl-6">
          {STEPS.map((label, i) => {
            const done = i < step;
            const active = i === step;
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
      </div>
    </div>
  );
}
