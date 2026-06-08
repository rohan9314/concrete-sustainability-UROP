import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { QUESTION_SETS, EXAMPLE_TOPICS, buildMockReport } from "@/lib/research-mock";
import { setReport } from "@/lib/research-store";
import { Search, ArrowRight, BookOpen } from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Concrete Decarbonization Research Agent" },
      {
        name: "description",
        content:
          "Analyze cement and concrete decarbonization technologies using internet sources and scientific literature.",
      },
    ],
  }),
  component: SearchPage,
});

function SearchPage() {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [questionSet, setQuestionSet] = useState<string>("carbon_capture");

  const selectedSet = QUESTION_SETS.find((s) => s.id === questionSet)!;

  function runResearch(t?: string) {
    const subject = (t ?? topic).trim();
    if (!subject) return;
    // Pre-build the mock so the report page has data when loading finishes.
    setReport(buildMockReport(subject, questionSet));
    navigate({
      to: "/loading",
      search: { topic: subject, set: questionSet },
    });
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
            v0.1 · Research preview
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
            Analyze cement and concrete decarbonization technologies using internet
            sources and scientific literature. Each report is fully cited and includes
            per-question confidence assessments.
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
                placeholder="e.g. Calcium Looping, LC3 Cement, Fortera, Sublime Systems…"
                className="h-14 w-full rounded-md border border-border bg-card pl-11 pr-4 text-[15px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-foreground/40 focus:ring-2 focus:ring-ring/20"
              />
            </div>
            <p className="mt-2 text-[13px] text-muted-foreground">
              Enter any topic, technology, company, material, process, or
              decarbonization strategy.
            </p>
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
              className="h-12 w-full rounded-md border border-border bg-card px-4 text-[15px] outline-none focus:border-foreground/40 focus:ring-2 focus:ring-ring/20"
            >
              {QUESTION_SETS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
            <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
              {selectedSet.description}
            </p>
          </div>

          <button
            type="submit"
            disabled={!topic.trim()}
            className="group inline-flex h-12 w-full items-center justify-center gap-2 rounded-md bg-primary px-6 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Run Research
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
                className="rounded-full border border-border bg-card px-3.5 py-1.5 text-[13px] text-foreground/80 transition-colors hover:border-foreground/40 hover:bg-accent"
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
