/** Free-text Q&A with server-backed temporary autosave and JSON export. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DetailRow, LibraryShell } from "../components/LibraryShell";
import {
  createQASession,
  getQASession,
  qaDownloadUrl,
  updateQASession,
} from "../lib/api";
import { req, ValidationError } from "../lib/content";
import { useLibrary } from "../lib/useLibrary";
import type { QAPrompt, QASet } from "../types";

function parseQanda(raw: Record<string, unknown>, where: string): QASet {
  const entries = req<unknown[]>(raw, "questions", "array", where);
  if (entries.length === 0) throw new ValidationError(`${where}: Q&A set contains no questions`);

  const questions = entries.map<QAPrompt>((entry, index) => {
    if (typeof entry === "string") {
      return { id: `question-${index + 1}`, question: entry, placeholder: "Type your response…", required: false };
    }
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new ValidationError(`${where} question ${index + 1}: expected a string or object`);
    }
    const item = entry as Record<string, unknown>;
    const at = `${where} question ${index + 1}`;
    return {
      id: typeof item.id === "string" && item.id ? item.id : `question-${index + 1}`,
      question: req<string>(item, "question", "string", at),
      placeholder: typeof item.placeholder === "string" ? item.placeholder : "Type your response…",
      required: typeof item.required === "boolean" ? item.required : false,
    };
  });

  if (new Set(questions.map((question) => question.id)).size !== questions.length) {
    throw new ValidationError(`${where}: question ids must be unique`);
  }
  return {
    title: req<string>(raw, "title", "string", where),
    description: typeof raw.description === "string" ? raw.description : "",
    questions,
  };
}

type SaveState = "idle" | "saving" | "saved" | "error";

export function QandaView() {
  const lib = useLibrary<QASet>("qandas", parseQanda);
  const selectedFile = lib.selected?.entry.file ?? null;
  const qa = lib.selected?.doc ?? null;
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [answers, setAnswers] = useState<string[]>([]);
  const [index, setIndex] = useState(0);
  const [finished, setFinished] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const autosaveTimer = useRef<number | null>(null);

  const storageKey = selectedFile ? `qanda-session:${selectedFile}` : null;

  useEffect(() => {
    let cancelled = false;
    setSessionId(null);
    setAnswers([]);
    setIndex(0);
    setFinished(false);
    setSaveState("idle");
    setSessionError(null);
    if (!storageKey || !qa || !selectedFile) return () => { cancelled = true; };

    const savedId = localStorage.getItem(storageKey);
    if (!savedId) return () => { cancelled = true; };
    void getQASession(savedId)
      .then((session) => {
        if (cancelled || session.qaFile !== selectedFile || session.responses.length !== qa.questions.length) return;
        setSessionId(session.id);
        setAnswers(session.responses.map((response) => response.answer));
        setIndex(session.currentQuestion);
        setFinished(session.status === "completed");
        setSaveState("saved");
      })
      .catch(() => localStorage.removeItem(storageKey));
    return () => { cancelled = true; };
  }, [qa, selectedFile, storageKey]);

  const answered = useMemo(() => answers.filter((answer) => answer.trim()).length, [answers]);

  const begin = useCallback(async () => {
    if (!qa || !selectedFile || !storageKey) return;
    setStarting(true);
    setSessionError(null);
    try {
      const session = await createQASession(
        selectedFile,
        qa.title,
        qa.questions.map(({ id, question }) => ({ id, question })),
      );
      setSessionId(session.id);
      setAnswers(session.responses.map((response) => response.answer));
      setIndex(0);
      setFinished(false);
      setSaveState("saved");
      saveQueue.current = Promise.resolve();
      localStorage.setItem(storageKey, session.id);
    } catch (error) {
      setSessionError((error as Error).message);
    } finally {
      setStarting(false);
    }
  }, [qa, selectedFile, storageKey]);

  const persist = useCallback(
    (nextAnswers: string[], nextIndex: number, completed: boolean) => {
      if (!sessionId) return Promise.resolve();
      setSaveState("saving");
      setSessionError(null);
      const operation = saveQueue.current
        .catch(() => undefined)
        .then(async () => {
          try {
            await updateQASession(sessionId, nextAnswers, nextIndex, completed);
            setSaveState("saved");
          } catch (error) {
            setSaveState("error");
            setSessionError((error as Error).message);
            throw error;
          }
        });
      saveQueue.current = operation;
      return operation;
    },
    [sessionId],
  );

  useEffect(() => {
    if (!sessionId || answers.length === 0 || finished) return;
    setSaveState("saving");
    autosaveTimer.current = window.setTimeout(() => {
      autosaveTimer.current = null;
      void persist(answers, index, false).catch(() => undefined);
    }, 400);
    return () => {
      if (autosaveTimer.current !== null) window.clearTimeout(autosaveTimer.current);
      autosaveTimer.current = null;
    };
  }, [answers, finished, index, persist, sessionId]);

  const download = async () => {
    if (!sessionId) return;
    try {
      await persist(answers, index, finished);
      const anchor = document.createElement("a");
      anchor.href = qaDownloadUrl(sessionId);
      anchor.download = "";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch {
      // The persistent error banner explains why no download was started.
    }
  };

  const complete = async () => {
    if (!qa) return;
    const missing = qa.questions.findIndex((question, i) => question.required && !answers[i]?.trim());
    if (missing >= 0) {
      setIndex(missing);
      setSessionError("Please answer this required question before finishing.");
      return;
    }
    if (autosaveTimer.current !== null) {
      window.clearTimeout(autosaveTimer.current);
      autosaveTimer.current = null;
    }
    try {
      await persist(answers, index, true);
      setFinished(true);
    } catch {
      // Remain in the editor so the user can retry without losing text.
    }
  };

  const newResponse = () => {
    if (storageKey) localStorage.removeItem(storageKey);
    setSessionId(null);
    setAnswers([]);
    setIndex(0);
    setFinished(false);
    setSaveState("idle");
    setSessionError(null);
    saveQueue.current = Promise.resolve();
    if (autosaveTimer.current !== null) window.clearTimeout(autosaveTimer.current);
    autosaveTimer.current = null;
  };

  const details = qa ? (
    <>
      <p className="details-title">{qa.title}</p>
      <p className="muted small">{qa.description}</p>
      <DetailRow label="Questions" value={qa.questions.length} />
      <DetailRow label="Required" value={qa.questions.filter((question) => question.required).length} />
      <DetailRow label="File" value={selectedFile ?? "n/a"} />
      {sessionId ? <DetailRow label="Session" value={sessionId} /> : null}
    </>
  ) : null;

  const toolbar = (
    <>
      <button type="button" onClick={lib.reload}>Reload content</button>
      <span className="spacer" />
      {sessionId ? <button type="button" onClick={() => void download()}>Download JSON</button> : null}
      {sessionId ? <button type="button" onClick={newResponse}>New response</button> : null}
    </>
  );

  let body: React.ReactNode;
  if (!qa) {
    body = <div className="placeholder">Select a Q&A set.</div>;
  } else if (!sessionId) {
    body = (
      <div className="placeholder">
        <h2>{qa.title}</h2>
        <p className="muted">{qa.description}</p>
        <p>Your responses are stored temporarily by the local Python backend.</p>
        <button type="button" className="primary big" disabled={starting} onClick={() => void begin()}>
          {starting ? "Starting…" : "Start Q&A"}
        </button>
        {sessionError ? <p className="bad" role="alert">{sessionError}</p> : null}
      </div>
    );
  } else if (finished) {
    body = (
      <div className="scroll pad qa-review">
        <h2>Q&A complete</h2>
        <p className="muted">All responses are saved temporarily. Download a copy to keep them.</p>
        <div className="row gap">
          <button type="button" className="primary" onClick={() => void download()}>Download JSON</button>
          <button type="button" onClick={() => setFinished(false)}>Continue editing</button>
          <button type="button" onClick={newResponse}>Start a new response</button>
        </div>
        {sessionError ? <p className="bad" role="alert">{sessionError}</p> : null}
        {qa.questions.map((question, questionIndex) => (
          <section className="review" key={question.id}>
            <h3>{questionIndex + 1}. {question.question}</h3>
            <p className="qa-answer">{answers[questionIndex] || <span className="muted">No response</span>}</p>
          </section>
        ))}
      </div>
    );
  } else {
    const prompt = qa.questions[index];
    body = (
      <div className="scroll pad qa-editor">
        <div className="row between">
          <strong>Question {index + 1} of {qa.questions.length}</strong>
          <span className="muted">{prompt.required ? "Required" : "Optional"}</span>
        </div>
        <progress value={answered} max={qa.questions.length} />
        <label className="qa-prompt" htmlFor={`qa-${prompt.id}`}>{prompt.question}</label>
        <textarea
          id={`qa-${prompt.id}`}
          value={answers[index] ?? ""}
          placeholder={prompt.placeholder}
          rows={10}
          onChange={(event) => {
            const next = [...answers];
            next[index] = event.target.value;
            setAnswers(next);
          }}
        />
        {sessionError ? <p className="bad" role="alert">{sessionError}</p> : null}
        <div className="row gap">
          <button type="button" disabled={index === 0} onClick={() => setIndex((value) => value - 1)}>← Previous</button>
          <button type="button" onClick={() => void download()}>Save a JSON copy</button>
          <span className="spacer" />
          {index < qa.questions.length - 1 ? (
            <button type="button" className="primary" onClick={() => setIndex((value) => value + 1)}>Next →</button>
          ) : (
            <button type="button" className="primary" onClick={() => void complete()}>Finish ✓</button>
          )}
        </div>
      </div>
    );
  }

  const status = sessionId
    ? `${answered}/${qa?.questions.length ?? 0} answered · ${saveState === "saving" ? "Saving…" : saveState === "error" ? "Save failed" : "Saved temporarily"}`
    : `${lib.documents.length} Q&A sets`;

  return (
    <LibraryShell
      documents={lib.documents}
      errors={lib.errors}
      loading={lib.loading}
      selectedIndex={lib.selectedIndex}
      onSelect={lib.select}
      titleOf={(set) => set.title}
      details={details}
      toolbar={toolbar}
      status={status}
      hint="Answers autosave; download JSON to keep a permanent copy"
      emptyMessage="No Q&A sets found in new_output/*/qandas."
    >
      {body}
    </LibraryShell>
  );
}
