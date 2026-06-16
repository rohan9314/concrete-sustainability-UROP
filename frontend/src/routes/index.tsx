import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  fetchIntelligenceOptions,
  fetchQuestionSets,
  startResearch,
  type QuestionSet,
} from "@/lib/api";
import { EXAMPLE_TOPICS } from "@/lib/research-types";
import type { IntelligenceOptions, ResearchFilters } from "@/lib/technology-intelligence";
import { Search, ArrowRight, BookOpen } from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Concrete Decarbonization Technology Intelligence" },
      {
        name: "description",
        content:
          "Structured technology intelligence database for cement and concrete decarbonization.",
      },
    ],
  }),
  component: SearchPage,
});

const DEFAULT_FILTERS: ResearchFilters = {
  main_category: "Not Reported",
  ccs_subcategory: "Not Reported",
  company_name: "",
  project_stage: "Not Reported",
};

function questionSetForCategory(category: string): string {
  switch (category) {
    case "Carbon Capture":
      return "carbon_capture";
    case "Supplementary Cementitious Material":
    case "Alternative SCM":
      return "scm";
    case "Alternative Cementitious Material":
      return "alternative_cement";
    default:
      return "evaluation_questions";
  }
}

function SearchPage() {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [filters, setFilters] = useState<ResearchFilters>(DEFAULT_FILTERS);
  const [includeLegacyQa, setIncludeLegacyQa] = useState(false);
  const [options, setOptions] = useState<IntelligenceOptions | null>(null);
  const [questionSets, setQuestionSets] = useState<QuestionSet[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(true);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchIntelligenceOptions(), fetchQuestionSets()])
      .then(([intelOptions, qSets]) => {
        setOptions(intelOptions);
        setQuestionSets(qSets.question_sets);
      })
      .catch((error: Error) => {
        const msg = error.message;
        setMetaError(
          msg === "Failed to fetch"
            ? "Cannot reach the backend. Start it with: cd backend && uvicorn api:app --reload --port 8000"
            : msg,
        );
      })
      .finally(() => setLoadingMeta(false));
  }, []);

  const showCcsSubcategory = filters.main_category === "Carbon Capture";

  async function runResearch(t?: string) {
    const subject = (t ?? topic).trim();
    if (!subject || submitting) return;

    const questionSet = questionSetForCategory(filters.main_category);

    setSubmitting(true);
    setSubmitError(null);

    try {
      const job = await startResearch(subject, questionSet, filters, includeLegacyQa);
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
              Cement Decarbonization Technology Intelligence
            </span>
          </div>
          <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            v0.4 · Structured extraction
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-8 pb-24 pt-20">
        <div className="mb-14">
          <p className="mb-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Technology Intelligence Search
          </p>
          <h1 className="mb-5 font-serif text-[44px] font-semibold leading-[1.05] tracking-tight">
            Structured Technology
            <br />
            Database
          </h1>
          <p className="max-w-2xl text-[17px] leading-relaxed text-muted-foreground">
            Extract standardized technology profiles — categories, metrics, companies,
            and pilot/demonstration projects — from local scientific papers and internet
            sources.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            runResearch();
          }}
          className="space-y-6"
        >
          <div>
            <label
              htmlFor="topic"
              className="mb-2 block font-mono text-[11px] uppercase tracking-widest text-muted-foreground"
            >
              Technology or Company Name
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
                placeholder="e.g. CycloneCC, Calcium Looping, CarbonCure…"
                className="h-14 w-full rounded-md border border-border bg-card pl-11 pr-4 text-[15px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-foreground/40 focus:ring-2 focus:ring-ring/20"
              />
            </div>
          </div>

          <div className="grid gap-6 sm:grid-cols-2">
            <FilterSelect
              id="main_category"
              label="Main Category"
              value={filters.main_category}
              disabled={loadingMeta || !!metaError}
              options={options?.main_categories ?? ["Not Reported"]}
              onChange={(value) =>
                setFilters((f) => ({
                  ...f,
                  main_category: value,
                  ccs_subcategory:
                    value === "Carbon Capture" ? f.ccs_subcategory : "Not Reported",
                }))
              }
            />

            {showCcsSubcategory && (
              <FilterSelect
                id="ccs_subcategory"
                label="CCS Subcategory"
                value={filters.ccs_subcategory}
                disabled={loadingMeta || !!metaError}
                options={options?.ccs_subcategories ?? ["Not Reported"]}
                onChange={(value) =>
                  setFilters((f) => ({ ...f, ccs_subcategory: value }))
                }
              />
            )}

            <div className={showCcsSubcategory ? "" : "sm:col-span-1"}>
              <label
                htmlFor="company_name"
                className="mb-2 block font-mono text-[11px] uppercase tracking-widest text-muted-foreground"
              >
                Company Name (optional)
              </label>
              <input
                id="company_name"
                value={filters.company_name}
                onChange={(e) =>
                  setFilters((f) => ({ ...f, company_name: e.target.value }))
                }
                placeholder="e.g. HeidelbergCement, Carbon Clean"
                className="h-12 w-full rounded-md border border-border bg-card px-4 text-[15px] outline-none focus:border-foreground/40 focus:ring-2 focus:ring-ring/20"
              />
            </div>

            <FilterSelect
              id="project_stage"
              label="Project Stage Filter"
              value={filters.project_stage}
              disabled={loadingMeta || !!metaError}
              options={options?.project_stages ?? ["Not Reported"]}
              onChange={(value) =>
                setFilters((f) => ({ ...f, project_stage: value }))
              }
            />
          </div>

          <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <input
              type="checkbox"
              checked={includeLegacyQa}
              onChange={(e) => setIncludeLegacyQa(e.target.checked)}
              className="rounded border-border"
            />
            Also generate legacy 26-question Q&amp;A output (slower)
          </label>

          {metaError ? (
            <p className="text-[13px] text-confidence-low">{metaError}</p>
          ) : (
            <p className="text-[13px] text-muted-foreground">
              Question framework:{" "}
              {questionSets.find((s) => s.id === questionSetForCategory(filters.main_category))
                ?.label ?? "Decarbonization Technology Evaluation Framework"}
            </p>
          )}

          {submitError && (
            <p className="text-[13px] text-confidence-low">{submitError}</p>
          )}

          <button
            type="submit"
            disabled={!topic.trim() || loadingMeta || !!metaError || submitting}
            className="group inline-flex h-12 w-full items-center justify-center gap-2 rounded-md bg-primary px-6 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? "Starting..." : "Extract Structured Intelligence"}
            <ArrowRight
              className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
              strokeWidth={2}
            />
          </button>
        </form>

        <div className="mt-14 border-t border-border pt-8">
          <p className="mb-4 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Example technologies
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
                disabled={loadingMeta || submitting}
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

function FilterSelect({
  id,
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: string[];
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-2 block font-mono text-[11px] uppercase tracking-widest text-muted-foreground"
      >
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="h-12 w-full rounded-md border border-border bg-card px-4 text-[15px] outline-none focus:border-foreground/40 focus:ring-2 focus:ring-ring/20 disabled:opacity-60"
      >
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}
