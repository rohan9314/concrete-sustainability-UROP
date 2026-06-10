import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { fetchQuestionSets, startResearch, type QuestionSet } from "@/lib/api";
import { EXAMPLE_TOPICS } from "@/lib/research-types";
import { Search, ArrowRight, BookOpen } from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Concrete Decarbonization Research Agent" },
      {
        name: "description",
        content:
          "Analyze cement and concrete decarbonization technologies using local paper sources and internet research.",
      },
    ],
  }),
  component: SearchPage,
});

function SearchPage() {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [questionSet, setQuestionSet] = useState<string>("");
  const [questionSets, setQuestionSets] = useState<QuestionSet[]>([]);
  const [loadingSets, setLoadingSets] = useState(true);
  const [setsError, setSetsError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    fetchQuestionSets()
      .then((data) => {
        setQuestionSets(data.question_sets);
        setQuestionSet(data.default);
      })
      .catch((error: Error) => {
        const msg = error.message;
        setSetsError(
          msg === "Failed to fetch"
            ? "Cannot reach the backend. Start it with: cd backend && uvicorn api:app --reload --port 8000"
            : msg,
        );
      })
      .finally(() => setLoadingSets(false));
  }, []);

  const selectedSet = questionSets.find((s) => s.id === questionSet);

  async function runResearch(t?: string) {
    const subject = (t ?? topic).trim();
    if (!subject || !questionSet || submitting) return;

    setSubmitting(true);
    setSubmitError(null);

    try {
      const job = await startResearch(subject, questionSet);
      navigate({
        to: "/loading",
        search: { topic: subject, set: questionSet, jobId: job.job_id },
      });
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Failed to start research.");
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-8 py-5">
          <div className="flex items-center gap-2.5">
            <BookOpen className="h-4 w-4 text-muted-foreground" strokeWidth={1.5} />
            <span className="font-serif text-[15px] font-semibold tracking-tight">
              Concrete Decarbonization Research Agent
            </span>
          </div>
          <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            v0.3 · Research pipeline
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-8 pb-24 pt-20">
        <div className="mb-14">
          <p className="mb-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            New Research
          </p>
          <h1 className="mb-5 font-serif text-[44px] font-semibold leading-[1.05] tracking-tight">
            Concrete Decarbonization
            <br />
            Research Agent
          </h1>
          <p className="max-w-2xl text-[17px] leading-relaxed text-muted-foreground">
            Analyze technologies against the full 26-question Decarbonization Technology
            Evaluation Framework using local paper sources and internet research.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            runResearch();
          }}
          className="space-y-8"
        >
          <div>
            <label
              htmlFor="topic"
              className="mb-2 block font-mono text-[11px] uppercase tracking-widest text-muted-foreground"
            >
              Research Subject
            </label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                strokeWidth={1.5}
              />
              <input
                id="topic"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. Calcium Looping, LC3 Cement, CarbonCure…"
                className="h-14 w-full rounded-md border border-border bg-card pl-11 pr-4 text-[15px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-foreground/40 focus:ring-2 focus:ring-ring/20"
              />
            </div>
          </div>

          <div>
            <label
              htmlFor="qset"
              className="mb-2 block font-mono text-[11px] uppercase tracking-widest text-muted-foreground"
            >
              Question Set
            </label>
            <select
              id="qset"
              value={questionSet}
              onChange={(e) => setQuestionSet(e.target.value)}
              disabled={loadingSets || !!setsError}
              className="h-12 w-full rounded-md border border-border bg-card px-4 text-[15px] outline-none focus:border-foreground/40 focus:ring-2 focus:ring-ring/20 disabled:opacity-60"
            >
              {loadingSets ? (
                <option value="">Loading question sets...</option>
              ) : (
                questionSets.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label} ({s.question_count} questions)
                  </option>
                ))
              )}
            </select>
            {setsError ? (
              <p className="mt-2 text-[13px] text-confidence-low">
                Could not load question sets: {setsError}
              </p>
            ) : (
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                {selectedSet?.description}
              </p>
            )}
          </div>

          {submitError && (
            <p className="text-[13px] text-confidence-low">{submitError}</p>
          )}

          <button
            type="submit"
            disabled={!topic.trim() || !questionSet || loadingSets || submitting}
            className="group inline-flex h-12 w-full items-center justify-center gap-2 rounded-md bg-primary px-6 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? "Starting..." : "Run Research"}
            <ArrowRight
              className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
              strokeWidth={2}
            />
          </button>
        </form>

        <div className="mt-14 border-t border-border pt-8">
          <p className="mb-4 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Example subjects
          </p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_TOPICS.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => {
                  setTopic(ex);
                  runResearch(ex);
                }}
                disabled={!questionSet || loadingSets || submitting}
                className="rounded-full border border-border bg-card px-3.5 py-1.5 text-[13px] text-foreground/80 transition-colors hover:border-foreground/40 hover:bg-accent disabled:opacity-40"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
