"""Browse and answer generated free-text Q&A sets.

The launcher fetches Q&A sets from the content backend (the same JSON the React
view uses). Answers are autosaved in the same temporary session directory used
by that backend, so either UI can retrieve and export them.

Standard library only.

    python python/qanda_launcher.py
    python python/qanda_launcher.py --api-url http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import tkinter as tk
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Sequence

from launcher_common import (
    Chunk,
    ContentAPI,
    LibraryApp,
    add_api_argument,
    connect_api,
    require,
)


DEFAULT_RESPONSE_DIR = Path(tempfile.gettempdir()) / "personalized-software" / "qa-sessions"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class QAPrompt:
    id: str
    question: str
    placeholder: str = "Type your response…"
    required: bool = False


@dataclass
class QASet:
    title: str
    description: str
    questions: List[QAPrompt]
    file: str

    @classmethod
    def from_document(cls, data: dict, entry: dict) -> "QASet":
        where = entry.get("file", "Q&A set")
        raw_questions = require(data, "questions", list, where)
        if not raw_questions:
            raise ValueError(f"{where}: Q&A set contains no questions")

        questions: List[QAPrompt] = []
        for index, raw in enumerate(raw_questions, start=1):
            if isinstance(raw, str):
                questions.append(QAPrompt(f"question-{index}", raw))
                continue
            if not isinstance(raw, dict):
                raise ValueError(f"{where} question {index}: expected a string or object")
            question_id = raw.get("id", f"question-{index}")
            placeholder = raw.get("placeholder", "Type your response…")
            required = raw.get("required", False)
            if not isinstance(question_id, str) or not question_id:
                raise ValueError(f"{where} question {index}: id must be a non-empty string")
            if not isinstance(placeholder, str):
                raise ValueError(f"{where} question {index}: placeholder must be a string")
            if not isinstance(required, bool):
                raise ValueError(f"{where} question {index}: required must be a boolean")
            questions.append(
                QAPrompt(
                    id=question_id,
                    question=require(raw, "question", str, f"{where} question {index}"),
                    placeholder=placeholder,
                    required=required,
                )
            )

        ids = [question.id for question in questions]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{where}: question ids must be unique")
        description = data.get("description", "")
        if not isinstance(description, str):
            raise ValueError(f"{where}: description must be a string")
        return cls(
            title=require(data, "title", str, where),
            description=description,
            questions=questions,
            file=entry.get("file", where),
        )


class QandaApp(LibraryApp):
    """Free-text Q&A editor with temporary autosave and JSON export."""

    window_title = "Free-text Q&A"
    window_size = "1160x760"

    def __init__(self, api: ContentAPI, response_dir: Path):
        self.response_dir = response_dir
        self.current_doc: Optional[QASet] = None
        self.session: Optional[dict] = None
        self.question_index = 0
        self._loading_text = False
        self._dirty = False
        self._autosave_job: Optional[str] = None
        super().__init__(api, "qandas")
        self.set_hint("responses autosave temporarily · export JSON to keep a copy")
        self.protocol("WM_DELETE_WINDOW", self._close)

    def load_one(self, data: dict, entry: dict) -> QASet:
        return QASet.from_document(data, entry)

    def title_of(self, doc: QASet) -> str:
        return doc.title

    def describe(self, doc: QASet) -> Sequence[Chunk]:
        return [
            (doc.title + "\n\n", "h2"),
            (doc.description + "\n\n", None),
            (f"Questions: {len(doc.questions)}\n", "dim"),
            (f"Required: {sum(question.required for question in doc.questions)}\n", "dim"),
            (f"File: {doc.file}\n", "dim"),
            (f"Temporary responses: {self.response_dir}\n", "dim"),
        ]

    def build_toolbar(self, toolbar: ttk.Frame) -> None:
        toolbar.columnconfigure(2, weight=1)
        ttk.Button(toolbar, text="New response", command=self.new_response).grid(
            row=0, column=3, padx=(0, 8)
        )
        ttk.Button(toolbar, text="Save JSON copy…", command=self.export_response).grid(
            row=0, column=4, padx=(0, 8)
        )
        ttk.Button(toolbar, text="Finish", command=self.finish).grid(row=0, column=5)

    def build_content(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, padding=(22, 18))
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)

        header = ttk.Frame(panel)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.counter = ttk.Label(header, text="")
        self.counter.grid(row=0, column=0, sticky="w")
        self.requirement = ttk.Label(header, text="", foreground="#6b7580")
        self.requirement.grid(row=0, column=1, sticky="e")

        self.progress = ttk.Progressbar(panel, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(10, 16))

        self.prompt_label = ttk.Label(
            panel, text="Select a Q&A set.", font=("Segoe UI", 13, "bold"), wraplength=780
        )
        self.prompt_label.grid(row=2, column=0, sticky="w", pady=(0, 12))

        answer_frame = ttk.Frame(panel)
        answer_frame.grid(row=3, column=0, sticky="nsew")
        answer_frame.columnconfigure(0, weight=1)
        answer_frame.rowconfigure(0, weight=1)
        self.answer = tk.Text(answer_frame, wrap="word", padx=12, pady=10, undo=True)
        self.answer.grid(row=0, column=0, sticky="nsew")
        answer_scroll = ttk.Scrollbar(answer_frame, orient="vertical", command=self.answer.yview)
        answer_scroll.grid(row=0, column=1, sticky="ns")
        self.answer.configure(yscrollcommand=answer_scroll.set)
        self.answer.bind("<<Modified>>", self._answer_changed)

        navigation = ttk.Frame(panel)
        navigation.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        navigation.columnconfigure(1, weight=1)
        self.previous_button = ttk.Button(navigation, text="← Previous", command=self.previous)
        self.previous_button.grid(row=0, column=0)
        self.next_button = ttk.Button(navigation, text="Next →", command=self.next)
        self.next_button.grid(row=0, column=2)

    def show(self, doc: QASet) -> None:
        self._flush_autosave()
        self.current_doc = doc
        self.session = self._latest_session(doc) or self._create_session(doc)
        self.question_index = min(
            max(int(self.session.get("currentQuestion", 0)), 0), len(doc.questions) - 1
        )
        self._render_question()

    def _create_session(self, doc: QASet) -> dict:
        now = utc_now()
        session = {
            "id": uuid.uuid4().hex,
            "qaFile": doc.file,
            "title": doc.title,
            "status": "in_progress",
            "currentQuestion": 0,
            "createdAt": now,
            "updatedAt": now,
            "completedAt": None,
            "responses": [
                {"id": prompt.id, "question": prompt.question, "answer": ""}
                for prompt in doc.questions
            ],
        }
        self._write_session(session)
        return session

    def _latest_session(self, doc: QASet) -> Optional[dict]:
        if not self.response_dir.is_dir():
            return None
        expected_ids = [prompt.id for prompt in doc.questions]
        matches = []
        for path in self.response_dir.glob("*.json"):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
                response_ids = [response["id"] for response in session["responses"]]
                if session.get("qaFile") == doc.file and response_ids == expected_ids:
                    matches.append(session)
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue
        return max(matches, key=lambda item: item.get("updatedAt", ""), default=None)

    def _write_session(self, session: dict) -> None:
        self.response_dir.mkdir(parents=True, exist_ok=True)
        destination = self.response_dir / f"{session['id']}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temporary, destination)

    def _capture_answer(self, completed: bool = False) -> None:
        if self.session is None or self.current_doc is None:
            return
        response = self.session["responses"][self.question_index]
        response["answer"] = self.answer.get("1.0", "end-1c")
        now = utc_now()
        self.session["currentQuestion"] = self.question_index
        self.session["updatedAt"] = now
        if completed:
            self.session["status"] = "completed"
            self.session["completedAt"] = self.session.get("completedAt") or now
        elif self._dirty and self.session.get("status") == "completed":
            self.session["status"] = "in_progress"
            self.session["completedAt"] = None
        self._write_session(self.session)
        self._dirty = False
        self._update_status()

    def _render_question(self) -> None:
        if self.current_doc is None or self.session is None:
            return
        prompt = self.current_doc.questions[self.question_index]
        response = self.session["responses"][self.question_index]
        total = len(self.current_doc.questions)
        self.counter.config(text=f"Question {self.question_index + 1} of {total}")
        self.requirement.config(text="Required" if prompt.required else "Optional")
        self.progress.configure(maximum=total, value=self._answered_count())
        self.prompt_label.config(text=prompt.question)
        self._loading_text = True
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", response.get("answer", ""))
        self.answer.edit_modified(False)
        self._loading_text = False
        self._dirty = False
        self.previous_button.configure(state="disabled" if self.question_index == 0 else "normal")
        self.next_button.configure(
            text="Finish ✓" if self.question_index == total - 1 else "Next →"
        )
        self.answer.focus_set()
        self._update_status()

    def _answered_count(self) -> int:
        if self.session is None:
            return 0
        return sum(bool(response.get("answer", "").strip()) for response in self.session["responses"])

    def _update_status(self, note: str = "Saved temporarily") -> None:
        if self.session is None or self.current_doc is None:
            self.set_status("")
            return
        self.progress.configure(value=self._answered_count())
        self.set_status(
            f"{self._answered_count()}/{len(self.current_doc.questions)} answered · {note}"
        )

    def _answer_changed(self, _event=None) -> None:
        if not self.answer.edit_modified():
            return
        self.answer.edit_modified(False)
        if self._loading_text:
            return
        self._dirty = True
        if self._autosave_job is not None:
            self.after_cancel(self._autosave_job)
        self._update_status("Saving…")
        self._autosave_job = self.after(450, self._autosave)

    def _autosave(self) -> None:
        self._autosave_job = None
        try:
            self._capture_answer()
        except OSError as error:
            self.set_status(f"Save failed: {error}")

    def _flush_autosave(self) -> None:
        if self._autosave_job is not None:
            self.after_cancel(self._autosave_job)
            self._autosave_job = None
        if self.session is not None and self.current_doc is not None:
            self._capture_answer()

    def previous(self) -> None:
        if self.current_doc is None or self.question_index == 0:
            return
        self._flush_autosave()
        self.question_index -= 1
        self.session["currentQuestion"] = self.question_index
        self._render_question()

    def next(self) -> None:
        if self.current_doc is None:
            return
        if self.question_index == len(self.current_doc.questions) - 1:
            self.finish()
            return
        self._flush_autosave()
        self.question_index += 1
        self.session["currentQuestion"] = self.question_index
        self._render_question()

    def finish(self) -> None:
        if self.current_doc is None or self.session is None:
            return
        self._flush_autosave()
        for index, prompt in enumerate(self.current_doc.questions):
            if prompt.required and not self.session["responses"][index]["answer"].strip():
                self.question_index = index
                self._render_question()
                messagebox.showwarning(
                    "Required response",
                    "Please answer this required question before finishing.",
                    parent=self,
                )
                return
        self._capture_answer(completed=True)
        messagebox.showinfo(
            "Q&A complete",
            "Your responses are saved temporarily. Use Save JSON copy to keep them.",
            parent=self,
        )

    def new_response(self) -> None:
        doc = self.selected()
        if doc is None:
            return
        self._flush_autosave()
        self.current_doc = doc
        self.session = self._create_session(doc)
        self.question_index = 0
        self._render_question()

    def export_response(self) -> None:
        if self.session is None:
            messagebox.showinfo("No response", "Select a Q&A set first.", parent=self)
            return
        self._flush_autosave()
        suggested = f"qa-{self.session['id']}.json"
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Save Q&A responses",
            defaultextension=".json",
            initialfile=suggested,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not destination:
            return
        try:
            Path(destination).write_text(
                json.dumps(self.session, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as error:
            messagebox.showerror("Export failed", str(error), parent=self)
            return
        self._update_status(f"Exported to {destination}")

    def _close(self) -> None:
        try:
            self._flush_autosave()
        except OSError as error:
            if not messagebox.askyesno(
                "Save failed", f"The temporary response could not be saved:\n{error}\n\nClose anyway?", parent=self
            ):
                return
        self.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch generated free-text Q&A sets")
    add_api_argument(parser)
    parser.add_argument(
        "--response-dir",
        type=Path,
        default=DEFAULT_RESPONSE_DIR,
        help="Temporary session folder shared with the Python backend",
    )
    args = parser.parse_args()
    QandaApp(connect_api(args.api_url), args.response_dir).mainloop()


if __name__ == "__main__":
    main()
