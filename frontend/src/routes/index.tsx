import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  fetchIntelligenceOptions,
  fetchQuestionSets,
  fetchTechnologyDatabase,
  searchTechnologyDatabase,
  startResearch,
  type QuestionSet,
} from "@/lib/api";
import { EXAMPLE_TOPICS } from "@/lib/research-types";
import { setTechnologyRecord } from "@/lib/research-store";
import type { IntelligenceOptions, ResearchFilters } from "@/lib/technology-intelligence";
import type { TechnologyRecord } from "@/lib/technology-record";
import { coverageLabel } from "@/lib/technology-record";
import { Search, ArrowRight, BookOpen, FlaskConical } from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Concrete Decarbonization Technology Intelligence" },
      {
        name: "description",
        content:
          "Browse prepared structured technology records from the offline cement decarbonization database.",
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

const UNKNOWN_OPTION = "Not Reported";

const FILTER_LABELS: Record<string, string> = {
  "Not Reported": "Unknown — auto-detect from sources",
};

function sortUnknownFirst(options: string[]): string[] {
  const rest = options.filter((o) => o !== UNKNOWN_OPTION);
  return options.includes(UNKNOWN_OPTION) ? [UNKNOWN_OPTION, ...rest] : options;
}

function optionLabel(value: string): string {
  return FILTER_LABELS[value] ?? value;
}

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
  const [databaseRecords, setDatabaseRecords] = useState<TechnologyRecord[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [showLiveAnalysis, setShowLiveAnalysis] = useState(false);
  const [filters, setFilters] = useState<ResearchFilters>(DEFAULT_FILTERS);
  const [includeLegacyQa, setIncludeLegacyQa] = useState(false);
  const [options, setOptions] = useState<IntelligenceOptions | null>(null);
  const [questionSets, setQuestionSets] = useState<QuestionSet[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(true);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchIntelligenceOptions(), fetchQuestionSets(), fetchTechnologyDatabase()])
      .then(([intelOptions, qSets, database]) => {
        setOptions(intelOptions);
        setQuestionSets(qSets.question_sets);
        setDatabaseRecords(database.records);
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

  async function searchDatabase(query?: string) {
    const subject = (query ?? topic).trim();
    setSearching(true);
    setSearchError(null);
    try {
      if (!subject) {
        const database = await fetchTechnologyDatabase();
        setDatabaseRecords(database.records);
      } else {
        const result = await searchTechnologyDatabase(subject);
        setDatabaseRecords(result.records);
      }
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "Database search failed.");
    } finally {
      setSearching(false);
    }
  }

  function openRecord(record: TechnologyRecord) {
    setTechnologyRecord(record);
    navigate({ to: "/report" });
  }

  async function runLiveResearch(t?: string) {
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

  const showCcsSubcategory = filters.main_category === "Carbon Capture";

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
            v0.5 · Prepared database
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-8 pb-24 pt-20">
        <div className="mb-14">
          <p className="mb-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            Technology Database Search
          </p>
          <h1 className="mb-5 font-serif text-[44px] font-semibold leading-[1.05] tracking-tight">
            Prepared Technology
            <br />
            Records
          </h1>
          <p className="max-w-2xl text-[17px] leading-relaxed text-muted-foreground">
            Browse structured technology profiles from the offline pipeline — categories,
            metrics, projects, sources, coverage, and confidence indicators. The website
            reads prepared records instead of processing the full corpus live.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            searchDatabase();
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
                placeholder="e.g. CycloneCC, LC3, CarbonCure…"
                className="h-14 w-full rounded-md border border-border bg-card pl-11 pr-4 text-[15px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-foreground/40 focus:ring-2 focus:ring-ring/20"
              />
            </div>
          </div>

          {metaError ? (
            <p className="text-[13px] text-confidence-low">{metaError}</p>
          ) : (
            <p className="text-[13px] text-muted-foreground">
              Showing prepared records from the offline pipeline database.
            </p>
          )}

          {searchError && <p className="text-[13px] text-confidence-low">{searchError}</p>}

          <button
            type="submit"
            disabled={loadingMeta || !!metaError || searching}
            className="group inline-flex h-12 w-full items-center justify-center gap-2 rounded-md bg-primary px-6 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {searching ? "Searching database..." : "Search Prepared Database"}
            <ArrowRight
              className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
              strokeWidth={2}
            />
          </button>
        </form>

        <DatabaseResults
          records={databaseRecords}
          loading={loadingMeta || searching}
          onSelect={openRecord}
        />

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
                  searchDatabase(ex);
                }}
                disabled={loadingMeta || searching}
                className="rounded-full border border-border bg-card px-3.5 py-1.5 text-[13px] text-foreground/80 transition-colors hover:border-foreground/40 hover:bg-accent disabled:opacity-40"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>

        <section className="mt-16 rounded-md border border-border bg-card p-6">
          <button
            type="button"
            onClick={() => setShowLiveAnalysis((value) => !value)}
            className="flex w-full items-center justify-between gap-3 text-left"
          >
            <div className="flex items-center gap-2">
              <FlaskConical className="h-4 w-4 text-muted-foreground" strokeWidth={1.5} />
              <div>
                <p className="text-[14px] font-medium">Experimental: Run live analysis</p>
                <p className="text-[13px] text-muted-foreground">
                  Optional live extraction from papers and internet sources (slower).
                </p>
              </div>
            </div>
            <span className="text-[13px] text-muted-foreground">
              {showLiveAnalysis ? "Hide" : "Show"}
            </span>
          </button>

          {showLiveAnalysis && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                runLiveResearch();
              }}
              className="mt-6 space-y-6 border-t border-border pt-6"
            >
              <div className="grid gap-6 sm:grid-cols-2">
                <FilterSelect
                  id="main_category"
                  label="Main Category (optional)"
                  value={filters.main_category}
                  disabled={loadingMeta || !!metaError}
                  options={sortUnknownFirst(options?.main_categories ?? [UNKNOWN_OPTION])}
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
                    options={sortUnknownFirst(options?.ccs_subcategories ?? [UNKNOWN_OPTION])}
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
                  label="Project Stage Filter (optional)"
                  value={filters.project_stage}
                  disabled={loadingMeta || !!metaError}
                  options={sortUnknownFirst(options?.project_stages ?? [UNKNOWN_OPTION])}
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

              <p className="text-[13px] text-muted-foreground">
                Question framework:{" "}
                {questionSets.find((s) => s.id === questionSetForCategory(filters.main_category))
                  ?.label ?? "Decarbonization Technology Evaluation Framework"}
              </p>

              {submitError && (
                <p className="text-[13px] text-confidence-low">{submitError}</p>
              )}

              <button
                type="submit"
                disabled={!topic.trim() || loadingMeta || !!metaError || submitting}
                className="inline-flex h-11 w-full items-center justify-center rounded-md border border-border bg-background px-4 text-[14px] font-medium transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
              >
                {submitting ? "Starting live analysis..." : "Run Live Analysis"}
              </button>
            </form>
          )}
        </section>
      </main>
    </div>
  );
}

function DatabaseResults({
  records,
  loading,
  onSelect,
}: {
  records: TechnologyRecord[];
  loading: boolean;
  onSelect: (record: TechnologyRecord) => void;
}) {
  if (loading) {
    return <p className="mt-8 text-[14px] text-muted-foreground">Loading database...</p>;
  }

  if (records.length === 0) {
    return (
      <p className="mt-8 text-[14px] text-muted-foreground">
        No matching prepared records. Try another search term or run the offline pipeline to
        populate the database.
      </p>
    );
  }

  return (
    <div className="mt-8 space-y-3">
      {records.map((record) => (
        <button
          key={record.record_id}
          type="button"
          onClick={() => onSelect(record)}
          className="w-full rounded-md border border-border bg-card p-4 text-left transition-colors hover:border-foreground/30 hover:bg-accent/40"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-serif text-[20px] font-semibold">{record.technology_name}</p>
              <p className="mt-1 text-[13px] text-muted-foreground">
                {record.technology_category} · {record.company_or_organization} ·{" "}
                {record.deployment_stage}
              </p>
            </div>
            <span className="rounded-full border border-border px-2.5 py-1 text-[12px] text-muted-foreground">
              {coverageLabel(record)}
            </span>
          </div>
          <p className="mt-3 line-clamp-2 text-[14px] leading-relaxed text-foreground/80">
            {record.technical_description}
          </p>
        </button>
      ))}
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
            {optionLabel(opt)}
          </option>
        ))}
      </select>
    </div>
  );
}
