"""Sample GUI application for browsing and taking generated quizzes.

Scans a folder of quiz JSON files (the format produced by
``python/ollama_learning/quiz.py`` and defined by ``ollama_learning.schemas.Quiz``),
lists them in a launcher window, and runs the selected quiz in an interactive
viewer with immediate feedback, scoring, and an end-of-quiz review.

Standard library only -- tkinter, random, argparse, urllib.

    python python/quiz_launcher.py
    python python/quiz_launcher.py --api-url http://127.0.0.1:8765
"""

import argparse
import random
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import List, Optional

from launcher_common import ContentAPI, ContentAPIError, add_api_argument, connect_api

DIFFICULTIES = ("recall", "understanding", "application", "analysis", "expert")


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

@dataclass
class Question:
    """One multiple-choice question, mirroring schemas.QuizQuestion."""

    question: str
    options: List[str]
    correct: int
    explanation: str
    difficulty: str = "understanding"
    sources: List[str] = field(default_factory=list)


@dataclass
class Quiz:
    """A loaded quiz, mirroring schemas.Quiz plus its source path."""

    title: str
    description: str
    questions: List[Question]
    file: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict, file: Optional[str] = None) -> "Quiz":
        questions = []
        for i, raw in enumerate(data.get("questions", [])):
            q = Question(
                question=raw["question"],
                options=list(raw["options"]),
                correct=int(raw["correct"]),
                explanation=raw["explanation"],
                difficulty=raw.get("difficulty", "understanding"),
                sources=list(raw.get("sources", [])),
            )
            if not 4 <= len(q.options) <= 6:
                raise ValueError(f"question {i + 1}: expected 4-6 options, got {len(q.options)}")
            if not 0 <= q.correct < len(q.options):
                raise ValueError(f"question {i + 1}: correct index {q.correct} out of range")
            if q.difficulty not in DIFFICULTIES:
                raise ValueError(f"question {i + 1}: unknown difficulty {q.difficulty!r}")
            questions.append(q)
        if not questions:
            raise ValueError("quiz contains no questions")
        return cls(
            title=data["title"],
            description=data.get("description", ""),
            questions=questions,
            file=file,
        )


def load_quizzes(api: ContentAPI) -> tuple:
    """Fetch every quiz from the content backend. Returns (quizzes, errors)."""
    quizzes, errors = [], []
    try:
        entries = api.entries("quizzes")
    except ContentAPIError as exc:
        return [], [str(exc)]
    for entry in entries:
        file = entry.get("file", "?")
        try:
            quizzes.append(Quiz.from_dict(api.document_json("quizzes", file), file))
        except Exception as exc:  # one bad doc shouldn't kill the launcher
            errors.append(f"{file}: {exc}")
    return quizzes, errors


def shuffled_copy(quiz: Quiz, shuffle_questions: bool, shuffle_options: bool) -> Quiz:
    """Return a copy of the quiz with questions and/or options reordered."""
    questions = []
    for q in quiz.questions:
        if shuffle_options:
            order = list(range(len(q.options)))
            random.shuffle(order)
            options = [q.options[i] for i in order]
            correct = order.index(q.correct)
        else:
            options, correct = list(q.options), q.correct
        questions.append(
            Question(q.question, options, correct, q.explanation, q.difficulty, list(q.sources))
        )
    if shuffle_questions:
        random.shuffle(questions)
    return Quiz(quiz.title, quiz.description, questions, quiz.file)


# --------------------------------------------------------------------------
# Quiz viewer
# --------------------------------------------------------------------------

class QuizWindow(tk.Toplevel):
    """Interactive viewer for a single quiz."""

    def __init__(self, master: tk.Misc, quiz: Quiz):
        super().__init__(master)
        self.quiz = quiz
        self.index = 0
        self.answers: List[Optional[int]] = [None] * len(quiz.questions)

        self.title(f"Quiz: {quiz.title}")
        self.geometry("820x680")
        self.minsize(640, 520)

        self._build_ui()
        self._show_question(0)

    # -- construction ------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header, text=self.quiz.title, font=("Segoe UI", 15, "bold"), wraplength=760
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header, text=self.quiz.description, wraplength=760, foreground="#555555"
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        body = ttk.Frame(self, padding=(20, 8, 20, 8))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        meta = ttk.Frame(body)
        meta.grid(row=0, column=0, sticky="ew")
        meta.columnconfigure(1, weight=1)
        self.counter_label = ttk.Label(meta, text="", font=("Segoe UI", 10, "bold"))
        self.counter_label.grid(row=0, column=0, sticky="w")
        self.difficulty_label = ttk.Label(meta, text="", foreground="#666666")
        self.difficulty_label.grid(row=0, column=2, sticky="e")

        self.question_label = ttk.Label(
            body, text="", font=("Segoe UI", 12), wraplength=740, justify="left"
        )
        self.question_label.grid(row=1, column=0, sticky="ew", pady=(12, 10))

        options_frame = ttk.LabelFrame(body, text="Choose one", padding=12)
        options_frame.grid(row=2, column=0, sticky="nsew")
        options_frame.columnconfigure(0, weight=1)

        self.choice = tk.IntVar(value=-1)
        self.option_buttons: List[ttk.Radiobutton] = []
        for i in range(6):
            rb = ttk.Radiobutton(options_frame, text="", variable=self.choice, value=i)
            rb.grid(row=i, column=0, sticky="w", pady=3)
            self.option_buttons.append(rb)

        self.feedback = tk.Text(
            body, height=7, wrap="word", relief="flat", background=self.cget("background")
        )
        self.feedback.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.feedback.configure(state="disabled")
        base = tkfont.nametofont("TkDefaultFont").actual()
        self.feedback.tag_configure("correct", foreground="#1a7f37", font=(base["family"], 10, "bold"))
        self.feedback.tag_configure("wrong", foreground="#b42318", font=(base["family"], 10, "bold"))
        self.feedback.tag_configure("body", foreground="#333333")
        self.feedback.tag_configure("sources", foreground="#666666")

        footer = ttk.Frame(self, padding=(20, 8, 20, 16))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)

        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=len(self.quiz.questions))
        self.progress.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))

        self.score_label = ttk.Label(footer, text="Score: 0/0", font=("Segoe UI", 10, "bold"))
        self.score_label.grid(row=1, column=0, sticky="w")

        buttons = ttk.Frame(footer)
        buttons.grid(row=1, column=2, sticky="e")
        self.prev_button = ttk.Button(buttons, text="← Previous", command=self.previous_question)
        self.prev_button.grid(row=0, column=0, padx=4)
        self.submit_button = ttk.Button(buttons, text="Submit answer", command=self.submit_answer)
        self.submit_button.grid(row=0, column=1, padx=4)
        self.next_button = ttk.Button(buttons, text="Next →", command=self.next_question)
        self.next_button.grid(row=0, column=2, padx=4)

        self.bind("<Return>", lambda _e: self._enter_pressed())
        self.bind("<Right>", lambda _e: self.next_question())
        self.bind("<Left>", lambda _e: self.previous_question())
        for i in range(6):
            self.bind(str(i + 1), lambda _e, n=i: self._pick(n))

    # -- state -------------------------------------------------------------

    @property
    def score(self) -> int:
        return sum(
            1
            for a, q in zip(self.answers, self.quiz.questions)
            if a is not None and a == q.correct
        )

    @property
    def answered(self) -> int:
        return sum(1 for a in self.answers if a is not None)

    def _pick(self, n: int) -> None:
        question = self.quiz.questions[self.index]
        if self.answers[self.index] is None and n < len(question.options):
            self.choice.set(n)

    def _enter_pressed(self) -> None:
        if str(self.submit_button["state"]) == "disabled":
            self.next_question()
        else:
            self.submit_answer()

    def _set_feedback(self, chunks) -> None:
        self.feedback.configure(state="normal")
        self.feedback.delete("1.0", "end")
        for text, tag in chunks:
            self.feedback.insert("end", text, tag)
        self.feedback.configure(state="disabled")

    # -- navigation --------------------------------------------------------

    def _show_question(self, index: int) -> None:
        self.index = index
        question = self.quiz.questions[index]
        total = len(self.quiz.questions)

        self.counter_label.config(text=f"Question {index + 1} of {total}")
        self.difficulty_label.config(text=f"Difficulty: {question.difficulty}")
        self.question_label.config(text=question.question)

        for i, rb in enumerate(self.option_buttons):
            if i < len(question.options):
                rb.config(text=f"{i + 1}.  {question.options[i]}")
                rb.grid()
            else:
                rb.grid_remove()

        given = self.answers[index]
        self.choice.set(given if given is not None else -1)

        if given is None:
            self._set_feedback([])
            self._set_options_enabled(True)
            self.submit_button.config(state="normal")
        else:
            self._render_result(question, given)
            self._set_options_enabled(False)
            self.submit_button.config(state="disabled")

        self.prev_button.config(state="normal" if index > 0 else "disabled")
        self.next_button.config(text="Finish ✓" if index == total - 1 else "Next →")
        self.progress["value"] = self.answered
        self._update_score()

    def _set_options_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for rb in self.option_buttons:
            rb.config(state=state)

    def _update_score(self) -> None:
        self.score_label.config(text=f"Score: {self.score}/{self.answered}")

    def _render_result(self, question: Question, given: int) -> None:
        chunks = []
        if given == question.correct:
            chunks.append(("Correct.\n\n", "correct"))
        else:
            chunks.append(
                (f"Incorrect. The answer is: {question.options[question.correct]}\n\n", "wrong")
            )
        chunks.append((question.explanation, "body"))
        if question.sources:
            chunks.append(("\n\nSource: " + ", ".join(question.sources), "sources"))
        self._set_feedback(chunks)

    def submit_answer(self) -> None:
        if self.choice.get() < 0:
            messagebox.showwarning("No answer", "Select an option first.", parent=self)
            return
        question = self.quiz.questions[self.index]
        self.answers[self.index] = self.choice.get()
        self._render_result(question, self.choice.get())
        self._set_options_enabled(False)
        self.submit_button.config(state="disabled")
        self.progress["value"] = self.answered
        self._update_score()

    def next_question(self) -> None:
        if self.index < len(self.quiz.questions) - 1:
            self._show_question(self.index + 1)
        else:
            self.show_results()

    def previous_question(self) -> None:
        if self.index > 0:
            self._show_question(self.index - 1)

    # -- results -----------------------------------------------------------

    def show_results(self) -> None:
        unanswered = [i + 1 for i, a in enumerate(self.answers) if a is None]
        if unanswered:
            listed = ", ".join(str(n) for n in unanswered[:10])
            more = "..." if len(unanswered) > 10 else ""
            if not messagebox.askyesno(
                "Unanswered questions",
                f"Questions {listed}{more} are unanswered.\n\nFinish anyway?",
                parent=self,
            ):
                self._show_question(unanswered[0] - 1)
                return
        ResultsWindow(self, self.quiz, self.answers, on_retry=self.restart)

    def restart(self) -> None:
        self.answers = [None] * len(self.quiz.questions)
        self._show_question(0)


class ResultsWindow(tk.Toplevel):
    """End-of-quiz summary with a per-question review."""

    def __init__(self, master: QuizWindow, quiz: Quiz, answers: List[Optional[int]], on_retry):
        super().__init__(master)
        self.quiz_window = master
        self.on_retry = on_retry

        total = len(quiz.questions)
        score = sum(1 for a, q in zip(answers, quiz.questions) if a is not None and a == q.correct)
        pct = (score / total * 100) if total else 0.0

        self.title("Quiz results")
        self.geometry("760x600")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = ttk.Frame(self, padding=20)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text=quiz.title, font=("Segoe UI", 14, "bold"), wraplength=700).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            head, text=f"{score} / {total}  ({pct:.0f}%)", font=("Segoe UI", 22, "bold")
        ).grid(row=1, column=0, sticky="w", pady=(6, 2))
        ttk.Label(head, text=self._verdict(pct), foreground="#555555").grid(
            row=2, column=0, sticky="w"
        )

        review = tk.Text(self, wrap="word", padx=20, pady=10, relief="flat")
        scroll = ttk.Scrollbar(self, orient="vertical", command=review.yview)
        review.configure(yscrollcommand=scroll.set)
        review.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")

        base = tkfont.nametofont("TkDefaultFont").actual()
        review.tag_configure("q", font=(base["family"], 10, "bold"))
        review.tag_configure("ok", foreground="#1a7f37")
        review.tag_configure("bad", foreground="#b42318")
        review.tag_configure("dim", foreground="#666666")

        for i, (question, given) in enumerate(zip(quiz.questions, answers), start=1):
            correct = given is not None and given == question.correct
            review.insert("end", f"{i}. {question.question}\n", "q")
            mark = "correct" if correct else "incorrect"
            tag = "ok" if correct else "bad"
            chosen = question.options[given] if given is not None else "(no answer)"
            review.insert("end", f"   Your answer ({mark}): {chosen}\n", tag)
            if not correct:
                review.insert("end", f"   Correct answer: {question.options[question.correct]}\n", "ok")
            review.insert("end", f"   {question.explanation}\n", "dim")
            if question.sources:
                review.insert("end", f"   Source: {', '.join(question.sources)}\n", "dim")
            review.insert("end", "\n")
        review.configure(state="disabled")

        buttons = ttk.Frame(self, padding=(20, 10, 20, 20))
        buttons.grid(row=2, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Retake quiz", command=self._retry).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Close quiz", command=self._close_all).grid(row=0, column=1, padx=4)

    @staticmethod
    def _verdict(pct: float) -> str:
        if pct >= 90:
            return "Excellent - you have mastered this material."
        if pct >= 70:
            return "Good work - a solid understanding of the text."
        if pct >= 50:
            return "A reasonable start; review the explanations below."
        return "Worth another pass through the source text before retrying."

    def _retry(self) -> None:
        self.destroy()
        self.on_retry()

    def _close_all(self) -> None:
        self.destroy()
        self.quiz_window.destroy()


# --------------------------------------------------------------------------
# Launcher
# --------------------------------------------------------------------------

class LauncherApp(tk.Tk):
    """Main window: pick a quiz served by the backend and start it."""

    def __init__(self, api: ContentAPI):
        super().__init__()
        self.api = api
        self.quizzes: List[Quiz] = []

        self.title("Quiz Launcher")
        self.geometry("900x560")
        self.minsize(720, 460)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        head = ttk.Frame(self, padding=(20, 16, 20, 6))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Quiz Launcher", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.dir_label = ttk.Label(head, text="", foreground="#666666")
        self.dir_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(head, text="Reload", command=self.refresh).grid(row=0, column=1, rowspan=2, sticky="e")

        body = ttk.Frame(self, padding=(20, 6, 20, 6))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1, minsize=300)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        list_frame = ttk.LabelFrame(body, text="Available quizzes", padding=8)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame, activestyle="dotbox", exportselection=False)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=list_scroll.set)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._show_details())
        self.listbox.bind("<Double-Button-1>", lambda _e: self.start_quiz())

        detail_frame = ttk.LabelFrame(body, text="Details", padding=8)
        detail_frame.grid(row=0, column=1, sticky="nsew")
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)
        self.details = tk.Text(detail_frame, wrap="word", relief="flat", padx=8, pady=6)
        self.details.grid(row=0, column=0, sticky="nsew")
        self.details.configure(state="disabled")
        base = tkfont.nametofont("TkDefaultFont").actual()
        self.details.tag_configure("h", font=(base["family"], 11, "bold"))
        self.details.tag_configure("dim", foreground="#666666")

        footer = ttk.Frame(self, padding=(20, 6, 20, 16))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(2, weight=1)

        self.shuffle_options = tk.BooleanVar(value=True)
        self.shuffle_questions = tk.BooleanVar(value=False)
        ttk.Checkbutton(footer, text="Shuffle answer options", variable=self.shuffle_options).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Checkbutton(footer, text="Shuffle question order", variable=self.shuffle_questions).grid(
            row=0, column=1, sticky="w", padx=(16, 0)
        )
        ttk.Button(footer, text="Start quiz", command=self.start_quiz).grid(row=0, column=3, sticky="e")

    def refresh(self) -> None:
        self.dir_label.config(text=self.api.base_url)
        self.quizzes, errors = load_quizzes(self.api)
        self.listbox.delete(0, "end")
        for quiz in self.quizzes:
            self.listbox.insert("end", f"{quiz.title}  ({len(quiz.questions)} q)")
        if self.quizzes:
            self.listbox.selection_set(0)
            self._show_details()
        else:
            self._set_details(
                [(f"No quizzes available from {self.api.base_url}\n", "dim")]
            )
        if errors:
            messagebox.showwarning("Some quizzes failed to load", "\n".join(errors), parent=self)

    def _selected(self) -> Optional[Quiz]:
        selection = self.listbox.curselection()
        return self.quizzes[selection[0]] if selection else None

    def _set_details(self, chunks) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        for text, tag in chunks:
            self.details.insert("end", text, tag)
        self.details.configure(state="disabled")

    def _show_details(self) -> None:
        quiz = self._selected()
        if quiz is None:
            return
        counts = {}
        sources = []
        for q in quiz.questions:
            counts[q.difficulty] = counts.get(q.difficulty, 0) + 1
            for s in q.sources:
                if s not in sources:
                    sources.append(s)
        breakdown = ", ".join(f"{d}: {counts[d]}" for d in DIFFICULTIES if d in counts)
        self._set_details([
            (quiz.title + "\n\n", "h"),
            (quiz.description + "\n\n", None),
            (f"Questions: {len(quiz.questions)}\n", "dim"),
            (f"Difficulty mix: {breakdown}\n", "dim"),
            (f"Sources: {', '.join(sources) if sources else 'n/a'}\n", "dim"),
            (f"File: {quiz.file or 'n/a'}\n", "dim"),
        ])

    def start_quiz(self) -> None:
        quiz = self._selected()
        if quiz is None:
            messagebox.showinfo("No quiz selected", "Select a quiz from the list first.", parent=self)
            return
        prepared = shuffled_copy(quiz, self.shuffle_questions.get(), self.shuffle_options.get())
        QuizWindow(self, prepared).focus_set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch generated quizzes in a GUI")
    add_api_argument(parser)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for shuffling")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    LauncherApp(connect_api(args.api_url)).mainloop()


if __name__ == "__main__":
    main()
