/** Port of python/reports_launcher.py. */

import { useEffect, useMemo, useRef, useState } from "react";
import { LibraryShell, DetailRow } from "../components/LibraryShell";
import { req, ValidationError } from "../lib/content";
import { formatCitation } from "../lib/format";
import { useLibrary } from "../lib/useLibrary";
import type { Report } from "../types";

function parseReport(raw: Record<string, unknown>, where: string): Report {
  const sections = req<unknown[]>(raw, "sections", "array", where);
  if (sections.length === 0) throw new ValidationError(`${where}: report has no sections`);

  return {
    title: req<string>(raw, "title", "string", where),
    executive_summary: req<string>(raw, "executive_summary", "string", where),
    conclusions: req<string>(raw, "conclusions", "string", where),
    sections: sections.map((entry, i) => {
      const s = entry as Record<string, unknown>;
      const at = `${where} section ${i + 1}`;
      return {
        title: req<string>(s, "title", "string", at),
        content: req<string>(s, "content", "string", at),
        claims: ((s.claims as Record<string, unknown>[]) ?? []).map((claim) => ({
          claim: req<string>(claim, "claim", "string", at),
          citations: ((claim.citations as Record<string, unknown>[]) ?? []).map((c) => ({
            source_id: req<string>(c, "source_id", "string", at),
            page: (c.page as number | null) ?? null,
            chunk_id: (c.chunk_id as string | null) ?? null,
          })),
        })),
      };
    }),
  };
}

/** Wrap every case-insensitive occurrence of `term` in a <mark>. */
function highlight(text: string, term: string): React.ReactNode {
  if (!term) return text;
  const parts = text.split(new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
  return parts.map((part, i) =>
    part.toLowerCase() === term.toLowerCase() ? <mark key={i}>{part}</mark> : part,
  );
}

export function ReportsView() {
  const lib = useLibrary<Report>("reports", parseReport);
  const [search, setSearch] = useState("");
  const [showClaims, setShowClaims] = useState(true);
  const body = useRef<HTMLDivElement>(null);

  const report = lib.selected?.doc ?? null;

  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
  }, [lib.selectedIndex]);

  const stats = useMemo(() => {
    if (!report) return { claims: 0, citations: 0, words: 0, sources: [] as string[] };
    const claims = report.sections.flatMap((s) => s.claims);
    const words =
      report.executive_summary.split(/\s+/).length +
      report.conclusions.split(/\s+/).length +
      report.sections.reduce(
        (total, s) =>
          total +
          s.content.split(/\s+/).length +
          s.claims.reduce((n, c) => n + c.claim.split(/\s+/).length, 0),
        0,
      );
    return {
      claims: claims.length,
      citations: claims.reduce((n, c) => n + c.citations.length, 0),
      words,
      sources: [...new Set(claims.flatMap((c) => c.citations.map((x) => x.source_id)))],
    };
  }, [report]);

  const term = search.trim();
  const hits = useMemo(() => {
    if (!report || !term) return 0;
    const haystack = [
      report.title,
      report.executive_summary,
      report.conclusions,
      ...report.sections.flatMap((s) => [s.title, s.content, ...s.claims.map((c) => c.claim)]),
    ].join("\n");
    return haystack.toLowerCase().split(term.toLowerCase()).length - 1;
  }, [report, term]);

  const jumpTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const details = report ? (
    <>
      <p className="details-title">{report.title}</p>
      <DetailRow label="Sections" value={report.sections.length} />
      <DetailRow label="Claims" value={stats.claims} />
      <DetailRow label="Citations" value={stats.citations} />
      <DetailRow label="Words" value={stats.words.toLocaleString()} />
      <DetailRow label="Sources" value={stats.sources.join(", ") || "none"} />
      <DetailRow label="File" value={lib.selected?.entry.file ?? "n/a"} />
      <p className="details-subheading">Outline</p>
      <ol className="bullets">
        {report.sections.map((section, i) => (
          <li key={section.title}>
            <button type="button" className="link" onClick={() => jumpTo(`section-${i}`)}>
              {section.title}
            </button>
          </li>
        ))}
      </ol>
    </>
  ) : null;

  const toolbar = (
    <>
      <button type="button" onClick={lib.reload}>
        Reload
      </button>
      <span className="divider" />
      <label className="field">
        Jump to
        <select
          value=""
          onChange={(e) => {
            if (e.target.value) jumpTo(e.target.value);
          }}
        >
          <option value="">Choose a section…</option>
          <option value="summary">Executive Summary</option>
          {report?.sections.map((section, i) => (
            <option key={section.title} value={`section-${i}`}>
              {section.title}
            </option>
          ))}
          <option value="conclusions">Conclusions</option>
        </select>
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={showClaims}
          onChange={(e) => setShowClaims(e.target.checked)}
        />
        Show claims
      </label>
      <span className="spacer" />
      <label className="field">
        Find
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="term" />
      </label>
      {term && <span className="muted small">{hits} hits</span>}
    </>
  );

  return (
    <LibraryShell
      documents={lib.documents}
      errors={lib.errors}
      loading={lib.loading}
      selectedIndex={lib.selectedIndex}
      onSelect={lib.select}
      titleOf={(r) => r.title}
      details={details}
      toolbar={toolbar}
      status={
        report
          ? `${report.sections.length} sections · ${stats.claims} claims · ${stats.citations} citations · ${stats.words.toLocaleString()} words`
          : ""
      }
      hint="Select a section to jump · type to search within the report"
      emptyMessage="No reports found in new_output/*/reports."
    >
      {report ? (
        <article className="scroll pad prose" ref={body}>
          <h1>{highlight(report.title, term)}</h1>

          <h2 id="summary">Executive Summary</h2>
          <p>{highlight(report.executive_summary, term)}</p>

          {report.sections.map((section, i) => (
            <section key={section.title} id={`section-${i}`}>
              <h2>{highlight(section.title, term)}</h2>
              <p>{highlight(section.content, term)}</p>
              {showClaims && section.claims.length > 0 && (
                <>
                  <h3>Key claims</h3>
                  {section.claims.map((claim, j) => (
                    <div key={j} className="claim">
                      <p>• {highlight(claim.claim, term)}</p>
                      {claim.citations.length > 0 && (
                        <p className="cite">
                          {claim.citations.map((c) => formatCitation(c)).join(", ")}
                        </p>
                      )}
                    </div>
                  ))}
                </>
              )}
            </section>
          ))}

          <h2 id="conclusions">Conclusions</h2>
          <p>{highlight(report.conclusions, term)}</p>
        </article>
      ) : (
        <div className="placeholder">Select a report.</div>
      )}
    </LibraryShell>
  );
}
