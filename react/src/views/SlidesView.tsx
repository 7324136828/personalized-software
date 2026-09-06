/** Port of python/slides_launcher.py. */

import { useCallback, useEffect, useState } from "react";
import { LibraryShell, DetailRow } from "../components/LibraryShell";
import { req, ValidationError } from "../lib/content";
import { useLibrary } from "../lib/useLibrary";
import type { Presentation } from "../types";

function parseDeck(raw: Record<string, unknown>, where: string): Presentation {
  const slides = req<unknown[]>(raw, "slides", "array", where);
  if (slides.length === 0) throw new ValidationError(`${where}: presentation has no slides`);

  return {
    title: req<string>(raw, "title", "string", where),
    slides: slides.map((entry, i) => {
      const s = entry as Record<string, unknown>;
      const at = `${where} slide ${i + 1}`;
      const bullets = s.bullets ?? [];
      if (!Array.isArray(bullets)) throw new ValidationError(`${at}: 'bullets' must be a list`);
      return {
        title: req<string>(s, "title", "string", at),
        subtitle: (s.subtitle as string | null) ?? null,
        bullets: bullets.map(String),
        speaker_notes: (s.speaker_notes as string) ?? "",
        image_query: (s.image_query as string | null) ?? null,
        source_ids: (s.source_ids as string[]) ?? [],
      };
    }),
  };
}

export function SlidesView() {
  const lib = useLibrary<Presentation>("slides", parseDeck);
  const [index, setIndex] = useState(0);
  const [showNotes, setShowNotes] = useState(true);
  const [presenting, setPresenting] = useState(false);

  const deck = lib.selected?.doc ?? null;

  useEffect(() => {
    setIndex(0);
  }, [lib.selectedIndex, lib.documents.length]);

  const next = useCallback(() => {
    if (deck) setIndex((i) => Math.min(deck.slides.length - 1, i + 1));
  }, [deck]);
  const prev = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) {
        return;
      }
      if (event.key === "ArrowRight" || event.code === "Space") {
        event.preventDefault();
        next();
      } else if (event.key === "ArrowLeft") prev();
      else if (event.key === "F5") {
        event.preventDefault();
        setPresenting(true);
      } else if (event.key === "Escape") setPresenting(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, prev]);

  const slide = deck?.slides[index] ?? null;

  const details = deck ? (
    <>
      <p className="details-title">{deck.title}</p>
      <DetailRow label="Slides" value={deck.slides.length} />
      <DetailRow
        label="Bullets"
        value={deck.slides.reduce((n, s) => n + s.bullets.length, 0)}
      />
      <DetailRow
        label="With speaker notes"
        value={deck.slides.filter((s) => s.speaker_notes).length}
      />
      <DetailRow
        label="Sources"
        value={[...new Set(deck.slides.flatMap((s) => s.source_ids))].join(", ") || "none"}
      />
      <DetailRow label="File" value={lib.selected?.entry.file ?? "n/a"} />
      <p className="details-subheading">Slides</p>
      <ol className="bullets">
        {deck.slides.map((s, i) => (
          <li key={i}>
            <button
              type="button"
              className={i === index ? "link active" : "link"}
              onClick={() => setIndex(i)}
            >
              {s.title}
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
      <button type="button" onClick={prev} disabled={index === 0}>
        ◀ Previous
      </button>
      <button
        type="button"
        onClick={next}
        disabled={!deck || index === deck.slides.length - 1}
      >
        Next ▶
      </button>
      <label className="check">
        <input
          type="checkbox"
          checked={showNotes}
          onChange={(e) => setShowNotes(e.target.checked)}
        />
        Speaker notes
      </label>
      <span className="spacer" />
      <button type="button" className="primary" disabled={!deck} onClick={() => setPresenting(true)}>
        Present (F5)
      </button>
    </>
  );

  return (
    <LibraryShell
      documents={lib.documents}
      errors={lib.errors}
      loading={lib.loading}
      selectedIndex={lib.selectedIndex}
      onSelect={lib.select}
      titleOf={(d) => d.title}
      details={details}
      toolbar={toolbar}
      status={deck && slide ? `${deck.title} · ${slide.bullets.length} bullets` : ""}
      hint="← → or space to move · F5 to present · Esc exits present mode"
      emptyMessage="No presentations found in output/slides."
    >
      {deck && slide ? (
        <div className="slides-pane">
          <div className="slide-face">
            <h2>{slide.title}</h2>
            {slide.subtitle && <p className="slide-subtitle">{slide.subtitle}</p>}
            <ul className="slide-bullets">
              {slide.bullets.map((bullet, i) => (
                <li key={i}>{bullet}</li>
              ))}
            </ul>
            <p className="slide-footer">
              {slide.source_ids.length > 0 && <>Sources: {slide.source_ids.join(", ")}</>}
              {slide.image_query && <span> Image cue: {slide.image_query}</span>}
            </p>
          </div>

          <div className="row between slide-nav">
            <strong>
              Slide {index + 1} of {deck.slides.length}
            </strong>
            <progress value={index + 1} max={deck.slides.length} />
          </div>

          {showNotes && (
            <div className="notes">
              <h3>Speaker notes</h3>
              <p className={slide.speaker_notes ? "" : "muted"}>
                {slide.speaker_notes || "(no speaker notes for this slide)"}
              </p>
            </div>
          )}

          {presenting && (
            <div
              className="present-overlay"
              role="dialog"
              aria-label="Presenting"
              onClick={next}
            >
              <div className="present-inner">
                <h2>{slide.title}</h2>
                {slide.subtitle && <p className="present-subtitle">{slide.subtitle}</p>}
                <ul>
                  {slide.bullets.map((bullet, i) => (
                    <li key={i}>{bullet}</li>
                  ))}
                </ul>
                <p className="present-counter">
                  {index + 1} / {deck.slides.length}
                </p>
              </div>
              <button
                type="button"
                className="present-close"
                onClick={(e) => {
                  e.stopPropagation();
                  setPresenting(false);
                }}
              >
                Exit (Esc)
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="placeholder">Select a presentation.</div>
      )}
    </LibraryShell>
  );
}
