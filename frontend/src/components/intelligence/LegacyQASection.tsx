import type { Answer } from "@/lib/research-types";
import { AlertTriangle, ExternalLink } from "lucide-react";

export function LegacyQASection({ answers }: { answers: Answer[] }) {
  if (!answers.length) return null;

  return (
    <section>
      <h2 className="mb-2 font-serif text-2xl font-semibold tracking-tight">
        Legacy 26-Question Output
      </h2>
      <p className="mb-6 text-[14px] text-muted-foreground">
        Raw question-and-answer extraction from the previous evaluation framework.
        The structured tabs above are the primary output.
      </p>
      <div className="space-y-4">
        {answers.map((a, i) => {
          const notFound = a.answer.trim() === "Not Found";
          return (
            <article
              key={a.question}
              className="rounded-md border border-border bg-card p-5"
            >
              <p className="mb-2 font-mono text-[11px] tracking-widest text-muted-foreground">
                Q{String(i + 1).padStart(2, "0")} · {a.confidence}
              </p>
              <h3 className="mb-3 font-serif text-[17px] font-semibold">{a.question}</h3>
              {notFound ? (
                <div className="flex gap-2 rounded-md border border-confidence-low/30 bg-confidence-low-bg/50 p-3 text-[13px] text-confidence-low">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  Information Not Available
                </div>
              ) : (
                <p className="text-[15px] leading-relaxed text-foreground/90">{a.answer}</p>
              )}
              {a.sources.length > 0 && (
                <ul className="mt-4 space-y-2 border-t border-border pt-3">
                  {a.sources.map((s, j) => (
                    <li key={j} className="text-[13px]">
                      <span className="font-medium">{s.title}</span>
                      {s.url && (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="ml-2 inline-flex items-center gap-1 text-primary hover:underline"
                        >
                          Open <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
