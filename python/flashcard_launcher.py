"""GUI application for browsing and studying generated flashcards.

Scans a folder of flashcard JSON files (the format produced by
``python/ollama_learning/flashcards.py`` and defined by ``ollama_learning.schemas.FlashcardSet``)
and provides an interactive study session with progress tracking and spaced repetition.

Standard library only -- tkinter, json, pathlib, random, argparse.

    python python/flashcard_launcher.py
    python python/flashcard_launcher.py --flashcard-dir output/flashcards
"""

import argparse
import json
import random
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import List, Optional


CARD_TYPES = ("basic", "cloze", "definition", "concept")


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

@dataclass
class Flashcard:
    """One flashcard, mirroring schemas.Flashcard."""
    type: str
    front: str
    back: str
    tags: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)


@dataclass
class FlashcardSet:
    """A loaded flashcard set, mirroring schemas.FlashcardSet plus its source path."""
    title: str
    description: str
    cards: List[Flashcard]
    path: Optional[Path] = None

    @classmethod
    def from_dict(cls, data: dict, path: Optional[Path] = None) -> "FlashcardSet":
        cards = []
        for i, raw in enumerate(data.get("cards", [])):
            if "type" not in raw or "front" not in raw or "back" not in raw:
                raise ValueError(f"card {i + 1}: missing required field")
            if raw["type"] not in CARD_TYPES:
                raise ValueError(f"card {i + 1}: unknown type {raw['type']!r}")
            cards.append(Flashcard(
                type=raw["type"],
                front=raw["front"],
                back=raw["back"],
                tags=list(raw.get("tags", [])),
                source_ids=list(raw.get("source_ids", [])),
            ))
        if not cards:
            raise ValueError("flashcard set contains no cards")
        return cls(
            title=data["title"],
            description=data.get("description", ""),
            cards=cards,
            path=path,
        )

    @classmethod
    def load(cls, path: Path) -> "FlashcardSet":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data, path)


def load_flashcard_dir(flashcard_dir: Path) -> tuple:
    """Load every *.json flashcard set in a folder. Returns (sets, errors)."""
    sets, errors = [], []
    for path in sorted(flashcard_dir.glob("*.json")):
        try:
            sets.append(FlashcardSet.load(path))
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    return sets, errors


def shuffled_copy(flashcard_set: FlashcardSet) -> FlashcardSet:
    """Return a copy of the flashcard set with cards reordered."""
    cards = list(flashcard_set.cards)
    random.shuffle(cards)
    return FlashcardSet(flashcard_set.title, flashcard_set.description, cards, flashcard_set.path)


# --------------------------------------------------------------------------
# Flashcard viewer
# --------------------------------------------------------------------------

class FlashcardWindow(tk.Toplevel):
    """Interactive viewer for a single flashcard set."""

    def __init__(self, master: tk.Misc, flashcard_set: FlashcardSet):
        super().__init__(master)
        self.set = shuffled_copy(flashcard_set)
        self.index = 0
        self.showing_answer = False
        self.mastery: List[bool] = [False] * len(self.set.cards)

        self.title(f"Flashcards: {self.set.title}")
        self.geometry("700x500")
        self.minsize(500, 400)

        self._build_ui()
        self._show_card(0)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header, text=self.set.title, font=("Segoe UI", 15, "bold"), wraplength=600
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header, text=self.set.description, wraplength=600, foreground="#555555"
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        body = ttk.Frame(self, padding=(20, 8, 20, 8))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        meta = ttk.Frame(body)
        meta.grid(row=0, column=0, sticky="ew")
        meta.columnconfigure(1, weight=1)
        self.counter_label = ttk.Label(meta, text="", font=("Segoe UI", 10, "bold"))
        self.counter_label.grid(row=0, column=0, sticky="w")
        self.type_label = ttk.Label(meta, text="", foreground="#666666")
        self.type_label.grid(row=0, column=2, sticky="e")

        card_frame = ttk.LabelFrame(body, text="Card", padding=20)
        card_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        card_frame.columnconfigure(0, weight=1)
        card_frame.rowconfigure(0, weight=1)

        self.front_label = ttk.Label(
            card_frame, text="", font=("Segoe UI", 14), wraplength=550, justify="center"
        )
        self.front_label.grid(row=0, column=0, sticky="nsew")

        self.back_label = ttk.Label(
            card_frame, text="", font=("Segoe UI", 12), wraplength=550, 
            justify="center", foreground="#1a5f7a"
        )
        self.back_label.grid(row=1, column=0, sticky="nsew", pady=(20, 0))

        self.tags_label = ttk.Label(card_frame, text="", foreground="#666666")
        self.tags_label.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        footer = ttk.Frame(self, padding=(20, 8, 20, 16))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)

        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=len(self.set.cards))
        self.progress.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))

        self.mastery_label = ttk.Label(footer, text="Mastered: 0/0", font=("Segoe UI", 10, "bold"))
        self.mastery_label.grid(row=1, column=0, sticky="w")

        buttons = ttk.Frame(footer)
        buttons.grid(row=1, column=2, sticky="e")
        self.prev_button = ttk.Button(buttons, text="← Previous", command=self.previous_card)
        self.prev_button.grid(row=0, column=0, padx=4)
        self.flip_button = ttk.Button(buttons, text="Show answer", command=self.flip_card)
        self.flip_button.grid(row=0, column=1, padx=4)
        self.next_button = ttk.Button(buttons, text="Next →", command=self.next_card)
        self.next_button.grid(row=0, column=2, padx=4)

        self.bind("<space>", lambda _e: self.flip_card())
        self.bind("<Right>", lambda _e: self.next_card())
        self.bind("<Left>", lambda _e: self.previous_card())
        self.bind("<y>", lambda _e: self.mark_mastered())
        self.bind("<n>", lambda _e: self.mark_not_mastered())

    def _show_card(self, index: int) -> None:
        self.index = index
        card = self.set.cards[index]
        total = len(self.set.cards)

        self.counter_label.config(text=f"Card {index + 1} of {total}")
        self.type_label.config(text=f"Type: {card.type}")
        
        self.front_label.config(text=card.front)
        self.back_label.config(text="")
        self.showing_answer = False
        self.flip_button.config(text="Show answer")
        
        if card.tags:
            self.tags_label.config(text=f"Tags: {', '.join(card.tags)}")
        else:
            self.tags_label.config(text="")

        self.prev_button.config(state="normal" if index > 0 else "disabled")
        self.next_button.config(text="Finish ✓" if index == total - 1 else "Next →")
        self.progress["value"] = index + 1
        self._update_mastery()

    def flip_card(self) -> None:
        if not self.showing_answer:
            card = self.set.cards[self.index]
            self.back_label.config(text=card.back)
            self.showing_answer = True
            self.flip_button.config(text="Hide answer")
        else:
            self.back_label.config(text="")
            self.showing_answer = False
            self.flip_button.config(text="Show answer")

    def next_card(self) -> None:
        if self.index < len(self.set.cards) - 1:
            self._show_card(self.index + 1)
        else:
            self.show_results()

    def previous_card(self) -> None:
        if self.index > 0:
            self._show_card(self.index - 1)

    def mark_mastered(self) -> None:
        self.mastery[self.index] = True
        self._update_mastery()
        self.next_card()

    def mark_not_mastered(self) -> None:
        self.mastery[self.index] = False
        self._update_mastery()
        self.next_card()

    def _update_mastery(self) -> None:
        mastered = sum(self.mastery)
        total = len(self.set.cards)
        self.mastery_label.config(text=f"Mastered: {mastered}/{total}")

    def show_results(self) -> None:
        mastered = sum(self.mastery)
        total = len(self.set.cards)
        pct = (mastered / total * 100) if total else 0.0

        message = f"Study session complete!\n\n"
        message += f"Mastered: {mastered} / {total} ({pct:.0f}%)\n\n"
        
        if pct >= 80:
            message += "Excellent work! You've mastered this material."
        elif pct >= 60:
            message += "Good progress! Review the cards you missed."
        elif pct >= 40:
            message += "Keep practicing. Focus on the difficult cards."
        else:
            message += "Worth another pass through the material."

        message += "\n\nPress OK to reshuffle and study again."

        if messagebox.askyesno("Session Complete", message, parent=self):
            self.set = shuffled_copy(self.set)
            self.mastery = [False] * len(self.set.cards)
            self._show_card(0)


# --------------------------------------------------------------------------
# Launcher
# --------------------------------------------------------------------------

class LauncherApp(tk.Tk):
    """Main window: pick a flashcard set from a folder and start studying."""

    def __init__(self, flashcard_dir: Path):
        super().__init__()
        self.flashcard_dir = flashcard_dir
        self.sets: List[FlashcardSet] = []

        self.title("Flashcard Launcher")
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
        ttk.Label(head, text="Flashcard Launcher", font=("Segoe UI", 16, "bold")).grid(
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

        list_frame = ttk.LabelFrame(body, text="Available flashcard sets", padding=8)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame, activestyle="dotbox", exportselection=False)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=list_scroll.set)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._show_details())
        self.listbox.bind("<Double-Button-1>", lambda _e: self.start_study())

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

        self.study_button = ttk.Button(footer, text="Start studying", command=self.start_study, state="disabled")
        self.study_button.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(footer, text="Quit", command=self.quit).grid(row=0, column=1)

    def refresh(self) -> None:
        self.sets, errors = load_flashcard_dir(self.flashcard_dir)
        self.listbox.delete(0, "end")
        for flashcard_set in self.sets:
            self.listbox.insert("end", flashcard_set.title)
        self.dir_label.config(text=str(self.flashcard_dir))
        
        if self.sets:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self._show_details()
        else:
            self._set_details([(f"No flashcard sets found in {self.flashcard_dir}\n", "dim")])
        
        if errors:
            messagebox.showwarning("Some flashcard sets failed to load", "\n".join(errors), parent=self)

    def _selected(self) -> Optional[FlashcardSet]:
        sel = self.listbox.curselection()
        return self.sets[sel[0]] if sel else None

    def _show_details(self) -> None:
        flashcard_set = self._selected()
        if flashcard_set is None:
            self.study_button.config(state="disabled")
            return
        
        self.study_button.config(state="normal")
        
        # Count card types
        type_counts = {}
        for card in flashcard_set.cards:
            type_counts[card.type] = type_counts.get(card.type, 0) + 1
        
        self._set_details([
            (flashcard_set.title + "\n\n", "h"),
            (f"Total cards: {len(flashcard_set.cards)}\n", "dim"),
            (f"File: {flashcard_set.path.name if flashcard_set.path else 'n/a'}\n\n", "dim"),
            ("Card types\n", "h"),
            ("".join(f"  • {card_type}: {count}\n" for card_type, count in type_counts.items()), None),
        ])

    def _set_details(self, chunks) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        for text, tag in chunks:
            self.details.insert("end", text, tag)
        self.details.configure(state="disabled")

    def start_study(self) -> None:
        flashcard_set = self._selected()
        if flashcard_set:
            FlashcardWindow(self, flashcard_set)


def main() -> None:
    default_dir = Path(__file__).resolve().parent.parent / "output" / "flashcards"
    parser = argparse.ArgumentParser(description="Study generated flashcards in a GUI")
    parser.add_argument(
        "--flashcard-dir",
        type=Path,
        default=default_dir,
        help="Folder containing flashcard JSON files (default: output/flashcards)",
    )
    args = parser.parse_args()

    if not args.flashcard_dir.exists():
        print(f"Creating directory: {args.flashcard_dir}")
        args.flashcard_dir.mkdir(parents=True, exist_ok=True)

    app = LauncherApp(args.flashcard_dir)
    app.mainloop()


if __name__ == "__main__":
    main()