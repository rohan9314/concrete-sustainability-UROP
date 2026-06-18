export type RegistrySourceType = "paper" | "web";

export interface RegisteredSource {
  source_id: string;
  source_type: RegistrySourceType;
  title: string;
  authors?: string[];
  year?: string;
  doi?: string;
  journal_or_venue?: string;
  url?: string;
  abstract_or_snippet?: string;
  website_or_publisher?: string;
  publication_date?: string;
  retrieval_date?: string;
  original_search_rank?: number | null;
}

export interface SourceBibliography {
  sources?: RegisteredSource[];
  sources_used?: RegisteredSource[];
  sources_considered?: RegisteredSource[];
  citation_warnings?: string[];
}

export function sourceMap(sources: RegisteredSource[] | undefined): Map<string, RegisteredSource> {
  const map = new Map<string, RegisteredSource>();
  for (const source of sources ?? []) {
    map.set(source.source_id, source);
  }
  return map;
}

export function formatSourceLine(source: RegisteredSource): string {
  if (source.source_type === "paper") {
    const authors = source.authors?.length ? source.authors.join(", ") : "Authors not reported";
    const venue = source.journal_or_venue || "Venue not reported";
    const link = source.doi || source.url || "DOI/URL not reported";
    return `[${source.source_id}] ${source.title}. ${authors}. ${source.year || "Year not reported"}. ${venue}. ${link}.`;
  }
  const publisher = source.website_or_publisher || "Publisher not reported";
  const link = source.url || "URL not reported";
  const retrieved = source.retrieval_date || "Retrieval date not reported";
  return `[${source.source_id}] ${source.title}. ${publisher}. ${link}. Retrieved ${retrieved}.`;
}

export function splitSourcesByType(sources: RegisteredSource[] | undefined) {
  const papers: RegisteredSource[] = [];
  const web: RegisteredSource[] = [];
  for (const source of sources ?? []) {
    if (source.source_type === "web") web.push(source);
    else papers.push(source);
  }
  return { papers, web };
}
