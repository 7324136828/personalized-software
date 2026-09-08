/**
 * Port of python/flashcards_launcher.py, merged with python/flashcard_launcher.py.
 *
 * Those two scripts covered the same content type; this view takes the union:
 * tag and type filters, shuffle, and "review missed" from the first, plus the
 * mastered / not-mastered marking and reshuffle-on-completion from the second.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { LibraryShell, DetailRow } from "../components/LibraryShell";
import { req, ValidationError } from "../lib/content";
import { shuffle } from "../lib/format";
import { useLibrary } from "../lib/useLibrary";
import { CARD_TYPES, type CardType, type Flashcard, type FlashcardSet } from "../types";

function parseSet(raw: Record<string, unknown>, where: string): FlashcardSet {
  const cards = req<unknown[]>(raw, "cards", "array", where);
  if (cards.length === 0) throw new ValidationError(`${where}: set contains no cards`);

  return {
    title: req<string>(raw, "title", "string", where),
    description: (raw.description as string) ?? "",
    cards: cards.map((entry, i) => {
      const c = entry as Record<string, unknown>;
      const at = `${where} card ${i + 1}`;
      const type = req<CardType>(c, "type", "string", at);
      if (!CARD_TYPES.includes(type)) {
        throw new ValidationError(`${at}: unknown card type '${type}'`);
      }
      return {
        type,
        front: req<string>(c, "front", "string", at),
        back: req<string>(c, "back", "string", at),
        tags: (c.tags as string[]) ?? [],
        source_ids: (c.source_ids as string[]) ?? [],
      };
    }),
  };
}

type Grade = "known" | "review";

export function FlashcardsView() {
  const lib = useLibrary<FlashcardSet>("flashcards", parseSet);
  const [tag, setTag] = useState("(all)");
  const [type, setType] = useState<"(all)" | CardType>("(all)");
  const [doShuffle, setDoShuffle] = useState(false);
  const [deck, setDeck] = useState<Flashcard[]>([]);
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [grades, setGrades] = useState<Record<number, Grade>>({});
  const [done, setDone] = useState(false);

  const set = lib.selected?.doc ?? null;

  const tags = useMemo(() => {
    if (!set) return [];
    return [...new Set(set.cards.flatMap((c) => c.tags))].sort();
  }, [set]);

  const rebuild = useCallback(
    (source: FlashcardSet | null, nextTag: string, nextType: string, mix: boolean) => {
      if (!source) return;
      let cards = source.cards.filter(
        (c) =>
          (nextTag === "(all)" || c.tags.includes(nextTag)) &&
          (nextType === "(all)" || c.type === nextType),
      );
      if (mix) cards = shuffle(cards);
      setDeck(cards);
      setIndex(0);
      setRevealed(false);
      setGrades({});
      setDone(false);
    },
    [],
  );

  useEffect(() => {
    setTag("(all)");
    setType("(all)");
    rebuild(set, "(all)", "(all)", doShuffle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [set]);

  const card = deck[index] ?? null;
  const known = Object.values(grades).filter((g) => g === "known").length;
  const toReview = Object.values(grades).filter((g) => g === "review").length;

  const advance = useCallback(() => {
    if (index < deck.length - 1) {
      setIndex(index + 1);
      setRevealed(false);
    } else {
      setDone(true);
    }
  }, [deck.length, index]);

  const grade = useCallback(
    (value: Grade) => {
      setGrades((prev) => ({ ...prev, [index]: value }));
      advance();
    },
    [advance, index],
  );

  const reviewMissed = () => {
    const missed = deck.filter((_, i) => grades[i] === "review");
    if (missed.length === 0) return;
    setDeck(missed);
    setIndex(0);
    setRevealed(false);
    setGrades({});
    setDone(false);
  };

  // Keyboard: space flips then advances, j/f grade, arrows navigate.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) {
        return;
      }
      if (!card || done) return;
      if (event.code === "Space") {
        event.preventDefault();
        if (revealed) advance();
        else setRevealed(true);
      } else if (event.key === "ArrowRight") advance();
      else if (event.key === "ArrowLeft" && index > 0) {
        setIndex(index - 1);
        setRevealed(false);
      } else if (event.key === "j") grade("known");
      else if (event.key === "f") grade("review");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [advance, card, done, grade, index, revealed]);

  const details = set ? (
    <>
      <p className="details-title">{set.title}</p>
      <p className="muted small">{set.description}</p>
      <DetailRow label="Cards" value={set.cards.length} />
      <DetailRow
        label="Types"
        value={CARD_TYPES.filter((t) => set.cards.some((c) => c.type === t))
          .map((t) => `${t}: ${set.cards.filter((c) => c.type === t).length}`)
          .join(", ")}
      />
      <DetailRow label="Tags" value={tags.join(", ") || "none"} />
      <DetailRow label="File" value={lib.selected?.entry.file ?? "n/a"} />
    </>
  ) : null;

  const toolbar = (
    <>
      <button type="button" onClick={lib.reload}>
        Reload
      </button>
      <span className="divider" />
      <label className="field">
        Tag
        <select
          value={tag}
          onChange={(e) => {
            setTag(e.target.value);
            rebuild(set, e.target.value, type, doShuffle);
          }}
        >
          <option>(all)</option>
          {tags.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </label>
      <label className="field">
        Type
        <select
          value={type}
          onChange={(e) => {
            const value = e.target.value as "(all)" | CardType;
            setType(value);
            rebuild(set, tag, value, doShuffle);
          }}
        >
          <option>(all)</option>
          {CARD_TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={doShuffle}
          onChange={(e) => {
            setDoShuffle(e.target.checked);
            rebuild(set, tag, type, e.target.checked);
          }}
        />
        Shuffle
      </label>
      <span className="spacer" />
      <button type="button" onClick={() => rebuild(set, tag, type, doShuffle)}>
        Restart
      </button>
      <button type="button" onClick={reviewMissed} disabled={toReview === 0}>
        Review missed ({toReview})
      </button>
    </>
  );

  let body: React.ReactNode;
  if (!set) {
    body = <div className="placeholder">Select a flashcard set.</div>;
  } else if (deck.length === 0) {
    body = <div className="placeholder muted">No cards match the current filters.</div>;
  } else if (done) {
    const pct = Math.round((known / deck.length) * 100);
    body = (
      <div className="placeholder">
        <h2>Session complete</h2>
        <p className="big-score">
          {known} / {deck.length} <span className="muted">marked known ({pct}%)</span>
        </p>
        <p className="muted">
          Use “Review missed” to study only the cards you flagged, or “Restart” to run the set again.
        </p>
        <div className="row gap">
          <button type="button" className="primary" onClick={() => rebuild(set, tag, type, true)}>
            Reshuffle and study again
          </button>
          <button type="button" onClick={reviewMissed} disabled={toReview === 0}>
            Review missed ({toReview})
          </button>
        </div>
      </div>
    );
  } else if (card) {
    body = (
      <div className="scroll pad">
        <div className="row between">
          <strong>
            Card {index + 1} of {deck.length}
          </strong>
          <span className={`badge type-${card.type}`}>{card.type.toUpperCase()}</span>
        </div>
        <progress value={Object.keys(grades).length} max={deck.length} />

        <button
          type="button"
          className={revealed ? "flashcard revealed" : "flashcard"}
          onClick={() => setRevealed(!revealed)}
        >
          <span className="card-front">{card.front}</span>
          {revealed ? (
            <>
              <span className="card-back">{card.back}</span>
              {card.tags.length > 0 && (
                <span className="muted small">Tags: {card.tags.join(", ")}</span>
              )}
              {card.source_ids.length > 0 && (
                <span className="muted small">Source: {card.source_ids.join(", ")}</span>
              )}
            </>
          ) : (
            <span className="muted small">(press space or click to reveal)</span>
          )}
        </button>

        <div className="row gap">
          <button
            type="button"
            onClick={() => {
              setIndex(Math.max(0, index - 1));
              setRevealed(false);
            }}
            disabled={index === 0}
          >
            ← Previous
          </button>
          <button type="button" onClick={() => setRevealed(!revealed)}>
            {revealed ? "Hide" : "Flip (space)"}
          </button>
          <span className="spacer" />
          <button type="button" className="bad-btn" onClick={() => grade("review")}>
            Needs review (f)
          </button>
          <button type="button" className="ok-btn" onClick={() => grade("known")}>
            Known (j)
          </button>
          <button type="button" onClick={advance}>
            Next →
          </button>
        </div>
      </div>
    );
  }

  return (
    <LibraryShell
      documents={lib.documents}
      errors={lib.errors}
      loading={lib.loading}
      selectedIndex={lib.selectedIndex}
      onSelect={lib.select}
      titleOf={(s) => s.title}
      details={details}
      toolbar={toolbar}
      status={`${Object.keys(grades).length} of ${deck.length} graded · ${known} known, ${toReview} to review`}
      hint="space flip/advance · ← → navigate · j known · f review"
      emptyMessage="No flashcard sets found in new_output/*/flashcards."
    >
      {body}
    </LibraryShell>
  );
}
