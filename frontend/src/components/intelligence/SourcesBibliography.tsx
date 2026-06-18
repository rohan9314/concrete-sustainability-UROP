import { useMemo, useState } from "react";
import type { RegisteredSource } from "@/lib/source-registry";
import { formatSourceLine, sourceMap, splitSourcesByType } from "@/lib/source-registry";
import { ExternalLink } from "lucide-react";

export function SourcesBibliography({
  sources,
  sourcesUsed,
  sourcesConsidered,
  citationWarnings,
}: {
  sources?: RegisteredSource[];
  sourcesUsed?: RegisteredSource[];
  sourcesConsidered?: RegisteredSource[];
  citationWarnings?: string[];
}) {
  const registry = useMemo(() => sourceMap(sources), [sources]);
  const used = sourcesUsed ?? sources ?? [];
  const considered = sourcesConsidered ?? [];
  const { papers: usedPapers, web: usedWeb } = splitSourcesByType(used);
  const { papers: consideredPapers, web: consideredWeb } = splitSourcesByType(considered);

  return (
    <section className="space-y-8">
      <div>
        <h2 className="mb-4 font-serif text-2xl font-semibold tracking-tight">Sources Used</h2>
        {used.length === 0 ? (
          <p className="text-[14px] text-muted-foreground">No cited sources were linked to this report.</p>
        ) : (
          <div className="space-y-6">
            <SourceGroup title="Papers" sources={usedPapers} registry={registry} />
            <SourceGroup title="Internet Sources" sources={usedWeb} registry={registry} />
          </div>
        )}
      </div>

      {considered.length > 0 && (
        <div>
          <h2 className="mb-4 font-serif text-2xl font-semibold tracking-tight">
            Sources Considered
          </h2>
          <p className="mb-4 text-[13px] text-muted-foreground">
            Retrieved or searched sources that were not ultimately cited in the final answer.
          </p>
          <div className="space-y-6">
            <SourceGroup title="Papers" sources={consideredPapers} registry={registry} />
            <SourceGroup title="Internet Sources" sources={consideredWeb} registry={registry} />
          </div>
        </div>
      )}

      {citationWarnings && citationWarnings.length > 0 && (
        <div className="rounded-md border border-confidence-medium/30 bg-confidence-medium-bg/40 p-4">
          <p className="text-[13px] font-semibold text-confidence-medium">Citation warnings</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-foreground/80">
            {citationWarnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function SourceGroup({
  title,
  sources,
  registry,
}: {
  title: string;
  sources: RegisteredSource[];
  registry: Map<string, RegisteredSource>;
}) {
  if (sources.length === 0) return null;

  return (
    <div>
      <h3 className="mb-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        {title}
      </h3>
      <ol className="space-y-3">
        {sources.map((source, index) => (
          <li key={source.source_id} className="rounded-md border border-border bg-card p-4">
            <SourceCard source={source} index={index + 1} registry={registry} />
          </li>
        ))}
      </ol>
    </div>
  );
}

export function SourceCard({
  source,
  index,
  registry,
}: {
  source: RegisteredSource;
  index?: number;
  registry?: Map<string, RegisteredSource>;
}) {
  const [expanded, setExpanded] = useState(false);
  const resolved = registry?.get(source.source_id) ?? source;

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="w-full text-left"
      >
        <p className="text-[14px] font-medium leading-relaxed">
          {index ? `${index}. ` : ""}
          <span className="font-mono text-[12px] text-muted-foreground">[{resolved.source_id}]</span>{" "}
          {resolved.title || "Source metadata unavailable"}
        </p>
        <p className="mt-1 text-[12px] text-muted-foreground">
          {expanded ? "Hide details" : "Show details"}
        </p>
      </button>
      {expanded && (
        <div className="mt-3 space-y-2 border-t border-border pt-3 text-[13px] leading-relaxed text-foreground/85">
          <p>{formatSourceLine(resolved)}</p>
          {resolved.authors && resolved.authors.length > 0 && (
            <p>
              <span className="text-muted-foreground">Authors: </span>
              {resolved.authors.join(", ")}
            </p>
          )}
          {resolved.abstract_or_snippet && (
            <p>
              <span className="text-muted-foreground">Snippet: </span>
              {resolved.abstract_or_snippet}
            </p>
          )}
          {resolved.url && (
            <a
              href={resolved.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              {resolved.url}
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export function CitationText({
  text,
  registry,
}: {
  text: string;
  registry: Map<string, RegisteredSource>;
}) {
  const parts = text.split(/(\[(?:paper|web)_\d{3}\])/gi);
  return (
    <span>
      {parts.map((part, index) => {
        const match = part.match(/^\[((?:paper|web)_\d{3})\]$/i);
        if (!match) return <span key={index}>{part}</span>;
        const source = registry.get(match[1]);
        if (!source) {
          return (
            <span key={index} className="text-confidence-low">
              Unmatched source reference
            </span>
          );
        }
        return (
          <button
            key={index}
            type="button"
            title={source.title}
            className="mx-0.5 font-mono text-[12px] text-primary underline-offset-2 hover:underline"
          >
            [{source.source_id}]
          </button>
        );
      })}
    </span>
  );
}
