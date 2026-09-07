"""Sample GUI application for presenting generated slide decks.

Scans a folder of presentation JSON files (the format produced by
``python/ollama_learning/slides.py`` and defined by
``ollama_learning.schemas.Presentation``) and shows the selected deck one slide
at a time, with a slide index, speaker notes, and a full-screen present mode.

Standard library only.

    python python/slides_launcher.py
    python python/slides_launcher.py --api-url http://127.0.0.1:8765
"""

import argparse
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk
from typing import List, Optional, Sequence

from launcher_common import (
    Chunk,
    ContentAPI,
    LibraryApp,
    RichText,
    add_api_argument,
    connect_api,
    require,
)


@dataclass
class Slide:
    """One slide, mirroring schemas.Slide."""

    title: str
    subtitle: Optional[str] = None
    bullets: List[str] = field(default_factory=list)
    speaker_notes: str = ""
    image_query: Optional[str] = None
    source_ids: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict, where: str) -> "Slide":
        bullets = data.get("bullets", [])
        if not isinstance(bullets, list):
            raise ValueError(f"{where}: 'bullets' must be a list")
        return cls(
            title=require(data, "title", str, where),
            subtitle=data.get("subtitle"),
            bullets=[str(b) for b in bullets],
            speaker_notes=data.get("speaker_notes", ""),
            image_query=data.get("image_query"),
            source_ids=list(data.get("source_ids", [])),
        )


@dataclass
class Deck:
    """A presentation, mirroring schemas.Presentation."""

    title: str
    slides: List[Slide]
    file: Optional[str] = None

    @classmethod
    def from_document(cls, data: dict, entry: dict) -> "Deck":
        where = entry.get("file", "presentation")
        slides = require(data, "slides", list, where)
        if not slides:
            raise ValueError(f"{where}: presentation has no slides")
        return cls(
            title=require(data, "title", str, where),
            slides=[Slide.from_dict(s, f"{where} slide {i + 1}") for i, s in enumerate(slides)],
            file=entry.get("file"),
        )

    def sources(self) -> List[str]:
        seen: List[str] = []
        for slide in self.slides:
            for src in slide.source_ids:
                if src not in seen:
                    seen.append(src)
        return seen


class SlidesApp(LibraryApp):
    """Presenter for a folder of generated decks."""

    window_title = "Slide Presenter"
    window_size = "1200x780"

    def __init__(self, api: ContentAPI):
        self.deck: Optional[Deck] = None
        self.index = 0
        self._fullscreen: Optional[tk.Toplevel] = None
        super().__init__(api, "slides")
        self.bind("<Right>", lambda _e: self.next_slide())
        self.bind("<Left>", lambda _e: self.prev_slide())
        self.bind("<space>", lambda _e: self.next_slide())
        self.bind("<F5>", lambda _e: self.present())
        self.set_hint("← → or space to move · F5 to present · Esc exits present mode")

    # -- library hooks -----------------------------------------------------

    def load_one(self, data: dict, entry: dict) -> Deck:
        return Deck.from_document(data, entry)

    def title_of(self, doc: Deck) -> str:
        return doc.title

    def describe(self, doc: Deck) -> Sequence[Chunk]:
        bullets = sum(len(s.bullets) for s in doc.slides)
        noted = sum(1 for s in doc.slides if s.speaker_notes)
        return [
            (doc.title + "\n\n", "h2"),
            (f"Slides: {len(doc.slides)}\n", "dim"),
            (f"Bullets: {bullets}\n", "dim"),
            (f"With speaker notes: {noted}\n", "dim"),
            (f"Sources: {', '.join(doc.sources()) or 'none'}\n", "dim"),
            (f"File: {doc.file or 'n/a'}\n\n", "dim"),
            ("Slides\n", "h3"),
            ("".join(f"  {i + 1}. {s.title}\n" for i, s in enumerate(doc.slides)), None),
        ]

    def build_toolbar(self, toolbar: ttk.Frame) -> None:
        toolbar.columnconfigure(6, weight=1)
        ttk.Button(toolbar, text="◀ Previous", command=self.prev_slide).grid(row=0, column=2)
        ttk.Button(toolbar, text="Next ▶", command=self.next_slide).grid(row=0, column=3, padx=6)

        self.notes_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toolbar, text="Speaker notes", variable=self.notes_var, command=self._toggle_notes
        ).grid(row=0, column=4, padx=(12, 0))

        ttk.Button(toolbar, text="Present (F5)", command=self.present).grid(
            row=0, column=7, sticky="e"
        )

    def build_content(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(0, weight=3)
        parent.rowconfigure(2, weight=1)

        self.slide_frame = tk.Frame(parent, background="#ffffff", highlightthickness=1,
                                    highlightbackground="#d6dde4")
        self.slide_frame.grid(row=0, column=0, sticky="nsew")
        self.slide_frame.columnconfigure(0, weight=1)
        self.slide_frame.rowconfigure(2, weight=1)

        self.slide_title = tk.Label(
            self.slide_frame, text="", font=("Segoe UI", 22, "bold"), background="#ffffff",
            foreground="#16293f", anchor="w", justify="left", wraplength=760,
        )
        self.slide_title.grid(row=0, column=0, sticky="ew", padx=32, pady=(28, 2))

        self.slide_subtitle = tk.Label(
            self.slide_frame, text="", font=("Segoe UI", 13), background="#ffffff",
            foreground="#5a6b7d", anchor="w", justify="left", wraplength=760,
        )
        self.slide_subtitle.grid(row=1, column=0, sticky="ew", padx=32, pady=(0, 14))

        self.slide_body = tk.Label(
            self.slide_frame, text="", font=("Segoe UI", 13), background="#ffffff",
            foreground="#22303c", anchor="nw", justify="left", wraplength=760,
        )
        self.slide_body.grid(row=2, column=0, sticky="nsew", padx=32)

        self.slide_footer = tk.Label(
            self.slide_frame, text="", font=("Segoe UI", 9), background="#ffffff",
            foreground="#8a949e", anchor="w",
        )
        self.slide_footer.grid(row=3, column=0, sticky="ew", padx=32, pady=(8, 16))

        nav = ttk.Frame(parent)
        nav.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        nav.columnconfigure(1, weight=1)
        self.counter_label = ttk.Label(nav, text="", font=("Segoe UI", 10, "bold"))
        self.counter_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(nav, mode="determinate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=12)

        self.notes_frame = ttk.LabelFrame(parent, text="Speaker notes", padding=8)
        self.notes_frame.grid(row=2, column=0, sticky="nsew")
        self.notes_frame.columnconfigure(0, weight=1)
        self.notes_frame.rowconfigure(0, weight=1)
        self.notes_text = RichText(self.notes_frame, height=5)
        self.notes_text.grid(row=0, column=0, sticky="nsew")

    def show(self, doc: Deck) -> None:
        self.deck = doc
        self.index = 0
        self._render()

    # -- rendering ---------------------------------------------------------

    def _render(self) -> None:
        if not self.deck:
            return
        slide = self.deck.slides[self.index]
        total = len(self.deck.slides)

        self.slide_title.config(text=slide.title)
        self.slide_subtitle.config(text=slide.subtitle or "")
        self.slide_body.config(text="\n\n".join(f"•  {b}" for b in slide.bullets))

        footer = []
        if slide.source_ids:
            footer.append("Sources: " + ", ".join(slide.source_ids))
        if slide.image_query:
            footer.append(f"Image cue: {slide.image_query}")
        self.slide_footer.config(text="     ".join(footer))

        self.counter_label.config(text=f"Slide {self.index + 1} of {total}")
        self.progress.configure(maximum=total, value=self.index + 1)

        self.notes_text.set_chunks(
            [(slide.speaker_notes or "(no speaker notes for this slide)",
              "body" if slide.speaker_notes else "dim")]
        )
        self.set_status(f"{self.deck.title}  ·  {len(slide.bullets)} bullets")
        if self._fullscreen is not None:
            self._render_fullscreen()

    def _toggle_notes(self) -> None:
        if self.notes_var.get():
            self.notes_frame.grid()
        else:
            self.notes_frame.grid_remove()

    # -- navigation --------------------------------------------------------

    def next_slide(self) -> None:
        if self.deck and self.index < len(self.deck.slides) - 1:
            self.index += 1
            self._render()

    def prev_slide(self) -> None:
        if self.deck and self.index > 0:
            self.index -= 1
            self._render()

    # -- present mode ------------------------------------------------------

    def present(self) -> None:
        if not self.deck or self._fullscreen is not None:
            return
        win = tk.Toplevel(self)
        win.title(f"Presenting: {self.deck.title}")
        win.configure(background="#0f1b28")
        try:
            win.attributes("-fullscreen", True)
        except tk.TclError:
            win.geometry("1280x800")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)

        self._fs_title = tk.Label(
            win, text="", font=("Segoe UI", 40, "bold"), background="#0f1b28",
            foreground="#ffffff", anchor="w", justify="left", wraplength=1500,
        )
        self._fs_title.grid(row=0, column=0, sticky="ew", padx=80, pady=(80, 6))
        self._fs_subtitle = tk.Label(
            win, text="", font=("Segoe UI", 20), background="#0f1b28",
            foreground="#8fb4d4", anchor="w", justify="left", wraplength=1500,
        )
        self._fs_subtitle.grid(row=1, column=0, sticky="ew", padx=80, pady=(0, 30))
        self._fs_body = tk.Label(
            win, text="", font=("Segoe UI", 22), background="#0f1b28",
            foreground="#e8eef4", anchor="nw", justify="left", wraplength=1500,
        )
        self._fs_body.grid(row=2, column=0, sticky="nsew", padx=80)
        self._fs_counter = tk.Label(
            win, text="", font=("Segoe UI", 12), background="#0f1b28", foreground="#5f7a94",
        )
        self._fs_counter.grid(row=3, column=0, sticky="e", padx=80, pady=(0, 40))

        win.bind("<Escape>", lambda _e: self._end_present())
        win.bind("<Right>", lambda _e: self.next_slide())
        win.bind("<space>", lambda _e: self.next_slide())
        win.bind("<Left>", lambda _e: self.prev_slide())
        win.protocol("WM_DELETE_WINDOW", self._end_present)

        self._fullscreen = win
        self._render_fullscreen()
        win.focus_set()

    def _render_fullscreen(self) -> None:
        if not self.deck or self._fullscreen is None:
            return
        slide = self.deck.slides[self.index]
        self._fs_title.config(text=slide.title)
        self._fs_subtitle.config(text=slide.subtitle or "")
        self._fs_body.config(text="\n\n".join(f"•  {b}" for b in slide.bullets))
        self._fs_counter.config(text=f"{self.index + 1} / {len(self.deck.slides)}")

    def _end_present(self) -> None:
        if self._fullscreen is not None:
            self._fullscreen.destroy()
            self._fullscreen = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Present generated slide decks in a GUI")
    add_api_argument(parser)
    args = parser.parse_args()

    SlidesApp(connect_api(args.api_url)).mainloop()


if __name__ == "__main__":
    main()
