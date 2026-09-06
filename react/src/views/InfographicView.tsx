/**
 * Port of python/infographic_launcher.py.
 *
 * The tkinter version could only stub SVG sections, because tkinter cannot
 * rasterize SVG without a third-party library. A browser can, so here the
 * diagram is fetched, sanitized with the same rules as
 * infographic.sanitize_svg, and inlined — matching the HTML export.
 */

import { useEffect, useMemo, useState } from "react";
import { LibraryShell, DetailRow } from "../components/LibraryShell";
import { dataUrl, req, ValidationError } from "../lib/content";
import { groupPanels, parseChartItem, percent, sanitizeSvg } from "../lib/format";
import { useLibrary } from "../lib/useLibrary";
import {
  SECTION_TYPES,
  type Infographic,
  type InfographicSection,
  type SectionType,
} from "../types";

function parseInfographic(raw: Record<string, unknown>, where: string): Infographic {
  const sections = req<Record<string, unknown>[]>(raw, "sections", "array", where);
  if (sections.length === 0) throw new ValidationError(`${where}: infographic has no sections`);

  return {
    title: req<string>(raw, "title", "string", where),
    subtitle: (raw.subtitle as string | null) ?? null,
    sections: sections.map((s, i) => {
      const at = `${where} section ${i + 1}`;
      const type = req<SectionType>(s, "type", "string", at);
      if (!SECTION_TYPES.includes(type)) {
        throw new ValidationError(`${at}: unknown section type '${type}'`);
      }
      const items = s.items ?? [];
      if (!Array.isArray(items)) throw new ValidationError(`${at}: 'items' must be a list`);
      return {
        type,
        title: (s.title as string | null) ?? null,
        value: (s.value as string | null) ?? null,
        label: (s.label as string | null) ?? null,
        items: items.map(String),
        panel: (s.panel as string | null) ?? null,
        span: (s.span as "full" | "half") ?? "full",
      };
    }),
  };
}

/** Fetch and inline an svg section's diagram, or report why it could not load. */
function SvgSection({ section }: { section: InfographicSection }) {
  const [markup, setMarkup] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const value = (section.value ?? "").trim();

  useEffect(() => {
    let cancelled = false;
    setMarkup(null);
    setError(null);

    if (!value) {
      setError("svg section has no value");
      return;
    }
    if (value.toLowerCase().includes("<svg")) {
      setMarkup(sanitizeSvg(value));
      return;
    }

    (async () => {
      try {
        const response = await fetch(dataUrl("infographics", value));
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const text = await response.text();
        if (!cancelled) setMarkup(sanitizeSvg(text));
      } catch (err) {
        if (!cancelled) setError(`SVG file not found: ${value}`);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [value]);

  if (error) return <p className="muted">Diagram unavailable: {error}</p>;
  if (markup === null) return <p className="muted small">Loading diagram…</p>;
  return (
    <figure>
      {/* Markup is sanitized above with the same rules as the Python exporter. */}
      <div className="svg-holder" dangerouslySetInnerHTML={{ __html: markup }} />
      {section.label && <figcaption>{section.label}</figcaption>}
    </figure>
  );
}

function SectionCard({ section }: { section: InfographicSection }) {
  const className = section.span === "half" ? "info-card half" : "info-card";

  let body: React.ReactNode = null;
  if (section.type === "stat") {
    body = (
      <>
        <div className="stat-value">{section.value}</div>
        <div className="stat-label">{section.label}</div>
      </>
    );
  } else if (section.type === "quote") {
    body = (
      <blockquote>
        {section.value}
        {section.label && <footer>— {section.label}</footer>}
      </blockquote>
    );
  } else if (section.type === "flow") {
    body = (
      <ol className="flow">
        {section.items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ol>
    );
  } else if (section.type === "chart") {
    const parsed = section.items.map(parseChartItem);
    const peak = Math.max(0, ...parsed.map((p) => p.value ?? 0));
    body = (
      <>
        {parsed.map((item, i) => (
          <div key={i} className="bar-row">
            <span>{item.label}</span>
            <span className="bar-track">
              <span
                className="bar-fill"
                style={{ width: `${item.value === null ? 0 : percent(item.value, peak)}%` }}
              />
            </span>
            <span className="bar-value">
              {item.value === null ? "" : `${item.value}${item.unit}`}
            </span>
          </div>
        ))}
      </>
    );
  } else if (section.type === "svg") {
    body = <SvgSection section={section} />;
  } else {
    body = (
      <>
        {section.items.map((item, i) =>
          item.includes(" vs ") ? (
            <div key={i} className="pair">
              <span>{item.split(" vs ")[0].trim()}</span>
              <span className="vs">vs</span>
              <span>{item.split(" vs ").slice(1).join(" vs ").trim()}</span>
            </div>
          ) : (
            <div key={i} className="pair">
              <span>{item}</span>
            </div>
          ),
        )}
      </>
    );
  }

  return (
    <section className={className}>
      {section.title && <div className="kicker">{section.title}</div>}
      {body}
    </section>
  );
}

export function InfographicView() {
  const lib = useLibrary<Infographic>("infographics", parseInfographic);
  const [typeFilter, setTypeFilter] = useState<"(all)" | SectionType>("(all)");
  const [showWireframe, setShowWireframe] = useState(false);
  const [wireframe, setWireframe] = useState<string | null>(null);

  const info = lib.selected?.doc ?? null;
  const entry = lib.selected?.entry ?? null;

  useEffect(() => {
    setTypeFilter("(all)");
    setShowWireframe(false);
    setWireframe(null);
  }, [lib.selectedIndex, lib.documents.length]);

  const sidecar = (suffix: string) =>
    entry?.sidecars.find((name) => name.endsWith(suffix)) ?? null;
  const wireframeFile = sidecar(".wireframe.txt");
  const htmlFile = sidecar(".html");
  const svgFile = sidecar(".svg");

  const visible = useMemo(
    () =>
      info
        ? info.sections.filter((s) => typeFilter === "(all)" || s.type === typeFilter)
        : [],
    [info, typeFilter],
  );

  // Panel numbering follows the full spec, so a type filter does not renumber.
  const allPanels = useMemo(() => (info ? groupPanels(info.sections) : []), [info]);
  const shownPanels = useMemo(() => {
    const bucket = groupPanels(visible);
    return allPanels
      .map((panel, i) => ({
        number: i + 1,
        name: panel.name,
        sections: bucket.find((b) => b.name === panel.name)?.sections ?? [],
      }))
      .filter((panel) => panel.sections.length > 0);
  }, [allPanels, visible]);

  const openWireframe = async () => {
    if (!wireframeFile) return;
    if (wireframe === null) {
      const response = await fetch(dataUrl("infographics", wireframeFile));
      setWireframe(response.ok ? await response.text() : "Could not load the wireframe.");
    }
    setShowWireframe(true);
  };

  const typeCounts = useMemo(() => {
    const counts: Partial<Record<SectionType, number>> = {};
    for (const section of info?.sections ?? []) {
      counts[section.type] = (counts[section.type] ?? 0) + 1;
    }
    return counts;
  }, [info]);

  const panelNames = allPanels.map((p) => p.name).filter(Boolean) as string[];

  const details = info ? (
    <>
      <p className="details-title">{info.title}</p>
      {info.subtitle && <p className="muted small">{info.subtitle}</p>}
      <DetailRow label="Panels" value={panelNames.length || 1} />
      <DetailRow label="Sections" value={info.sections.length} />
      <DetailRow
        label="Types"
        value={Object.entries(typeCounts)
          .map(([t, n]) => `${t}: ${n}`)
          .join(", ")}
      />
      <DetailRow label="File" value={entry?.file ?? "n/a"} />
      <DetailRow label="Pre-infographic" value={wireframeFile ? "yes" : "not written"} />
      <DetailRow
        label="Exports"
        value={[htmlFile && "html", svgFile && "svg"].filter(Boolean).join(", ") || "none"}
      />
      {panelNames.length > 0 && (
        <>
          <p className="details-subheading">Panels</p>
          <ol className="bullets">
            {panelNames.map((name) => (
              <li key={name}>
                {name}{" "}
                <span className="muted">
                  ({info.sections.filter((s) => s.panel === name).length})
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
    </>
  ) : null;

  const toolbar = (
    <>
      <button type="button" onClick={lib.reload}>
        Reload
      </button>
      <span className="divider" />
      <label className="field">
        Show type
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as "(all)" | SectionType)}
        >
          <option>(all)</option>
          {SECTION_TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </label>
      <span className="spacer" />
      <button type="button" onClick={openWireframe} disabled={!wireframeFile}>
        Pre-infographic
      </button>
      {htmlFile && (
        <a className="button" href={dataUrl("infographics", htmlFile)} target="_blank" rel="noreferrer">
          Open HTML export
        </a>
      )}
      {svgFile && (
        <a className="button" href={dataUrl("infographics", svgFile)} target="_blank" rel="noreferrer">
          SVG
        </a>
      )}
    </>
  );

  return (
    <LibraryShell
      documents={lib.documents}
      errors={lib.errors}
      loading={lib.loading}
      selectedIndex={lib.selectedIndex}
      onSelect={lib.select}
      titleOf={(g) => g.title}
      details={details}
      toolbar={toolbar}
      status={
        info
          ? `${panelNames.length || 1} panel(s) · ${visible.length} of ${info.sections.length} sections shown`
          : ""
      }
      hint="Scroll to read · filter by section type · open the pre-infographic wireframe"
      emptyMessage="No infographics found in output/infographics."
    >
      {info ? (
        <div className="scroll pad infographic">
          <h1>{info.title}</h1>
          {info.subtitle && <p className="muted">{info.subtitle}</p>}

          {shownPanels.map((panel) => (
            <section key={panel.name ?? "unnamed"} className="panel">
              {panel.name && (
                <h2 className="panel-title">
                  <span className="panel-num">{panel.number}</span>
                  {panel.name}
                </h2>
              )}
              <div className="panel-grid">
                {panel.sections.map((section, i) => (
                  <SectionCard key={i} section={section} />
                ))}
              </div>
            </section>
          ))}

          {visible.length === 0 && <p className="muted">No sections of that type.</p>}

          {showWireframe && (
            <div className="present-overlay" role="dialog" aria-label="Pre-infographic wireframe">
              <div className="wireframe-panel">
                <div className="row between">
                  <strong>Pre-infographic — review before the final render</strong>
                  <button type="button" onClick={() => setShowWireframe(false)}>
                    Close
                  </button>
                </div>
                <pre>{wireframe}</pre>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="placeholder">Select an infographic.</div>
      )}
    </LibraryShell>
  );
}
