/**
 * Port of python/flashcards_launcher.py, merged with python/flashcard_launcher.py.
 *
 * Those two scripts covered the same content type; this view takes the union:
 * tag and type filters, shuffle, and "review missed" from the first, plus the
 * mastered / not-mastered marking and reshuffle-on-completion from the second.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

interface CardAudio {
  front: string;
  back: string;
}

interface FlashcardAudioResponse {
  cards: CardAudio[];
  frontVoice: string;
  backVoice: string;
  error?: string;
}

function cardAudioKey(card: Flashcard): string {
  return JSON.stringify([card.front, card.back]);
}

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
  const [cardAudio, setCardAudio] = useState<Record<string, CardAudio>>({});
  const [narrating, setNarrating] = useState(false);
  const [audioLoading, setAudioLoading] = useState(false);
  const [audioError, setAudioError] = useState("");
  const audioPlayer = useRef<HTMLAudioElement | null>(null);

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
    audioPlayer.current?.pause();
    audioPlayer.current = null;
    setCardAudio({});
    setNarrating(false);
    setAudioLoading(false);
    setAudioError("");
    setTag("(all)");
    setType("(all)");
    rebuild(set, "(all)", "(all)", doShuffle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [set]);

  const card = deck[index] ?? null;
  const known = Object.values(grades).filter((g) => g === "known").length;
  const toReview = Object.values(grades).filter((g) => g === "review").length;

  const stopAudio = useCallback(() => {
    audioPlayer.current?.pause();
    audioPlayer.current = null;
  }, []);

  const playAudio = useCallback(
    (url: string) => {
      stopAudio();
      setAudioError("");
      const player = new Audio(url);
      audioPlayer.current = player;
      void player.play().catch((error: Error) => {
        setAudioError(`Audio playback failed: ${error.message}`);
      });
    },
    [stopAudio],
  );

  useEffect(() => {
    if (!narrating || !card || done) {
      if (done) stopAudio();
      return;
    }
    const audio = cardAudio[cardAudioKey(card)];
    if (audio) playAudio(revealed ? audio.back : audio.front);
  }, [card, cardAudio, done, narrating, playAudio, revealed, stopAudio]);

  useEffect(() => () => stopAudio(), [stopAudio]);

  const toggleNarration = async () => {
    if (narrating) {
      setNarrating(false);
      stopAudio();
      return;
    }
    if (!set) return;
    setAudioLoading(true);
    setAudioError("");
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}api/flashcards/audio`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cards: set.cards.map(({ front, back }) => ({ front, back })),
        }),
      });
      const body = (await response.json()) as FlashcardAudioResponse;
      if (!response.ok) {
        throw new Error(body.error ?? `Narration generation failed (${response.status})`);
      }
      if (body.cards.length !== set.cards.length) {
        throw new Error("Narration response did not match the flashcard set");
      }
      const generated: Record<string, CardAudio> = {};
      set.cards.forEach((item, itemIndex) => {
        generated[cardAudioKey(item)] = body.cards[itemIndex];
      });
      setCardAudio(generated);
      setNarrating(true);
    } catch (error) {
      setAudioError((error as Error).message);
    } finally {
      setAudioLoading(false);
    }
  };

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
      <button
        type="button"
        className={narrating ? "primary" : undefined}
        onClick={() => void toggleNarration()}
        disabled={!set || audioLoading}
        title="Generate Kokoro narration and play the visible side"
      >
        {audioLoading ? "Generating audio..." : narrating ? "Stop audio" : "▶ Play"}
      </button>
      {audioError ? (
        <span className="audio-error" role="alert" title={audioError}>
          {audioError}
        </span>
      ) : null}
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
