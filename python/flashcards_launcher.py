"""Sample GUI application for studying generated flashcard sets.

Scans a folder of flashcard JSON files (the format produced by
``python/ollama_learning/flashcards.py`` and defined by
``ollama_learning.schemas.FlashcardSet``) and runs a study session: flip a card,
grade yourself, and track what still needs review.

Standard library only.

    python python/flashcards_launcher.py
    python python/flashcards_launcher.py --api-url http://127.0.0.1:8765
"""

import argparse
import random
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Dict, List, Optional, Sequence

from launcher_common import (
    Chunk,
    ContentAPI,
    LibraryApp,
    RichText,
    add_api_argument,
    connect_api,
    require,
)

CARD_TYPES = ("basic", "cloze", "definition", "concept")

TYPE_COLORS = {
    "basic": "#2f6f9f",
    "cloze": "#7a5aa8",
    "definition": "#1a7f5a",
    "concept": "#b26b1f",
}


@dataclass
class Card:
    """One flashcard, mirroring schemas.Flashcard."""

    type: str
    front: str
    back: str
    tags: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict, where: str) -> "Card":
        card_type = require(data, "type", str, where)
        if card_type not in CARD_TYPES:
            raise ValueError(f"{where}: unknown card type {card_type!r}")
        return cls(
            type=card_type,
            front=require(data, "front", str, where),
            back=require(data, "back", str, where),
            tags=list(data.get("tags", [])),
            source_ids=list(data.get("source_ids", [])),
        )


@dataclass
class CardSet:
    """A flashcard set, mirroring schemas.FlashcardSet."""

    title: str
    description: str
    cards: List[Card]
    file: Optional[str] = None

    @classmethod
    def from_document(cls, data: dict, entry: dict) -> "CardSet":
        where = entry.get("file", "flashcard set")
        cards = require(data, "cards", list, where)
        if not cards:
            raise ValueError(f"{where}: set contains no cards")
        return cls(
            title=require(data, "title", str, where),
            description=data.get("description", ""),
            cards=[Card.from_dict(c, f"{where} card {i + 1}") for i, c in enumerate(cards)],
            file=entry.get("file"),
        )

    def tags(self) -> List[str]:
        seen: List[str] = []
        for card in self.cards:
            for tag in card.tags:
                if tag not in seen:
                    seen.append(tag)
        return sorted(seen)

    def type_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for card in self.cards:
            counts[card.type] = counts.get(card.type, 0) + 1
        return counts


class FlashcardsApp(LibraryApp):
    """Study session over a folder of flashcard sets."""

    window_title = "Flashcard Study"
    window_size = "1080x700"

    def __init__(self, api: ContentAPI):
        self.deck: List[Card] = []
        self.index = 0
        self.revealed = False
        self.known: Dict[int, bool] = {}
        super().__init__(api, "flashcards")
        self.bind("<space>", lambda _e: self._space())
        self.bind("<Right>", lambda _e: self.next_card())
        self.bind("<Left>", lambda _e: self.prev_card())
        self.bind("j", lambda _e: self.grade(True))
        self.bind("f", lambda _e: self.grade(False))
        self.set_hint("space flip/advance · ← → navigate · j known · f review")

    # -- library hooks -----------------------------------------------------

    def load_one(self, data: dict, entry: dict) -> CardSet:
        return CardSet.from_document(data, entry)

    def title_of(self, doc: CardSet) -> str:
        return doc.title

    def describe(self, doc: CardSet) -> Sequence[Chunk]:
        counts = ", ".join(f"{t}: {n}" for t, n in sorted(doc.type_counts().items()))
        tags = ", ".join(doc.tags()) or "none"
        return [
            (doc.title + "\n\n", "h2"),
            (doc.description + "\n\n", "body"),
            (f"Cards: {len(doc.cards)}\n", "dim"),
            (f"Types: {counts}\n", "dim"),
            (f"Tags: {tags}\n", "dim"),
            (f"File: {doc.file or 'n/a'}\n", "dim"),
        ]

    def build_toolbar(self, toolbar: ttk.Frame) -> None:
        toolbar.columnconfigure(9, weight=1)

        ttk.Label(toolbar, text="Filter tag:").grid(row=0, column=2)
        self.tag_var = tk.StringVar(value="(all)")
        self.tag_combo = ttk.Combobox(
            toolbar, textvariable=self.tag_var, width=20, state="readonly", values=["(all)"]
        )
        self.tag_combo.grid(row=0, column=3, padx=(6, 12))
        self.tag_combo.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_deck())

        ttk.Label(toolbar, text="Type:").grid(row=0, column=4)
        self.type_var = tk.StringVar(value="(all)")
        self.type_combo = ttk.Combobox(
            toolbar, textvariable=self.type_var, width=12, state="readonly",
            values=["(all)", *CARD_TYPES],
        )
        self.type_combo.grid(row=0, column=5, padx=(6, 12))
        self.type_combo.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_deck())

        self.shuffle_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            toolbar, text="Shuffle", variable=self.shuffle_var, command=self._rebuild_deck
        ).grid(row=0, column=6, padx=(0, 12))

        ttk.Button(toolbar, text="Restart", command=self._rebuild_deck).grid(row=0, column=7)
        ttk.Button(toolbar, text="Review missed", command=self._review_missed).grid(
            row=0, column=8, padx=(6, 0)
        )

    def build_content(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(1, weight=1)

        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(1, weight=1)
        self.counter_label = ttk.Label(header, text="", font=("Segoe UI", 10, "bold"))
        self.counter_label.grid(row=0, column=0, sticky="w")
        self.type_label = ttk.Label(header, text="", font=("Segoe UI", 9, "bold"))
        self.type_label.grid(row=0, column=2, sticky="e")

        self.card_frame = ttk.LabelFrame(parent, text="Card", padding=16)
        self.card_frame.grid(row=1, column=0, sticky="nsew")
        self.card_frame.columnconfigure(0, weight=1)
        self.card_frame.rowconfigure(0, weight=1)
        self.card_text = RichText(self.card_frame, height=12)
        self.card_text.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(parent)
        controls.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        controls.columnconfigure(2, weight=1)

        self.progress = ttk.Progressbar(controls, mode="determinate")
        self.progress.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 10))

        ttk.Button(controls, text="← Previous", command=self.prev_card).grid(row=1, column=0)
        self.flip_button = ttk.Button(controls, text="Flip (space)", command=self.flip)
        self.flip_button.grid(row=1, column=1, padx=6)

        grade = ttk.Frame(controls)
        grade.grid(row=1, column=3, sticky="e")
        self.review_button = ttk.Button(grade, text="Needs review (f)", command=lambda: self.grade(False))
        self.review_button.grid(row=0, column=0, padx=4)
        self.known_button = ttk.Button(grade, text="Known (j)", command=lambda: self.grade(True))
        self.known_button.grid(row=0, column=1, padx=4)
        ttk.Button(controls, text="Next →", command=self.next_card).grid(row=1, column=4, padx=(6, 0))

    def show(self, doc: CardSet) -> None:
        self.tag_combo.configure(values=["(all)", *doc.tags()])
        self.tag_var.set("(all)")
        self.type_var.set("(all)")
        self._rebuild_deck()

    # -- deck management ---------------------------------------------------

    def _rebuild_deck(self) -> None:
        doc = self.selected()
        if doc is None:
            return
        tag = self.tag_var.get()
        card_type = self.type_var.get()
        deck = [
            c for c in doc.cards
            if (tag == "(all)" or tag in c.tags) and (card_type == "(all)" or c.type == card_type)
        ]
        if self.shuffle_var.get():
            deck = deck[:]
            random.shuffle(deck)
        self.deck = deck
        self.index = 0
        self.known = {}
        self._render()

    def _review_missed(self) -> None:
        missed = [c for i, c in enumerate(self.deck) if self.known.get(i) is False]
        if not missed:
            self.set_status("Nothing marked for review yet.")
            return
        self.deck = missed
        self.index = 0
        self.known = {}
        self._render()

    # -- rendering ---------------------------------------------------------

    def _render(self) -> None:
        total = len(self.deck)
        if not total:
            self.card_text.set_chunks([("No cards match the current filters.\n", "dim")])
            self.counter_label.config(text="")
            self.type_label.config(text="")
            self.progress.configure(maximum=1, value=0)
            self._set_buttons(False)
            self.set_status("0 cards")
            return

        self.revealed = False
        card = self.deck[self.index]
        self.counter_label.config(text=f"Card {self.index + 1} of {total}")
        self.type_label.config(
            text=card.type.upper(), foreground=TYPE_COLORS.get(card.type, "#333333")
        )
        self.card_frame.configure(text=f"Card  ·  {card.type}")
        self._render_face(card, reveal=False)
        self.progress.configure(maximum=total, value=self.index + 1)
        self._set_buttons(True)
        self._update_status()

    def _render_face(self, card: Card, reveal: bool) -> None:
        chunks: List[Chunk] = [(card.front + "\n", "h2")]
        if reveal:
            chunks.append(("\n" + card.back + "\n", "body"))
            if card.tags:
                chunks.append(("\nTags: " + ", ".join(card.tags) + "\n", "dim"))
            if card.source_ids:
                chunks.append(("Source: " + ", ".join(card.source_ids) + "\n", "dim"))
        else:
            chunks.append(("\n(press space to reveal)\n", "dim"))
        self.card_text.set_chunks(chunks)
        self.flip_button.configure(text="Hide" if reveal else "Flip (space)")

    def _set_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self.flip_button, self.known_button, self.review_button):
            button.configure(state=state)

    def _update_status(self) -> None:
        known = sum(1 for v in self.known.values() if v)
        review = sum(1 for v in self.known.values() if v is False)
        graded = len(self.known)
        self.set_status(
            f"{graded} of {len(self.deck)} graded   ·   {known} known, {review} to review"
        )

    # -- actions -----------------------------------------------------------

    def flip(self) -> None:
        if not self.deck:
            return
        self.revealed = not self.revealed
        self._render_face(self.deck[self.index], self.revealed)

    def _space(self) -> None:
        if not self.revealed:
            self.flip()
        else:
            self.next_card()

    def grade(self, known: bool) -> None:
        if not self.deck:
            return
        self.known[self.index] = known
        self._update_status()
        self.next_card()

    def next_card(self) -> None:
        if not self.deck:
            return
        if self.index < len(self.deck) - 1:
            self.index += 1
            self._render()
        else:
            self._finish()

    def prev_card(self) -> None:
        if self.deck and self.index > 0:
            self.index -= 1
            self._render()

    def _finish(self) -> None:
        known = sum(1 for v in self.known.values() if v)
        total = len(self.deck)
        pct = (known / total * 100) if total else 0
        self.card_text.set_chunks([
            ("Session complete\n", "h1"),
            (f"\n{known} of {total} marked known ({pct:.0f}%)\n\n", "h2"),
            ("Use “Review missed” to study only the cards you flagged, "
             "or “Restart” to run the set again.\n", "body"),
        ])
        self.flip_button.configure(state="disabled")
        self._update_status()


def main() -> None:
    parser = argparse.ArgumentParser(description="Study generated flashcards in a GUI")
    add_api_argument(parser)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for shuffling")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    FlashcardsApp(connect_api(args.api_url)).mainloop()


if __name__ == "__main__":
    main()
