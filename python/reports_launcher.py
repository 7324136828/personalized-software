"""Sample GUI application for reading generated reports.

Scans a folder of report JSON files (the format produced by
``python/ollama_learning/reports.py`` and defined by ``ollama_learning.schemas.Report``)
and renders the selected report with a section outline, inline claims and
citations, and in-document search.

Standard library only.

    python python/reports_launcher.py
    python python/reports_launcher.py --api-url http://127.0.0.1:8765
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
class Citation:
    source_id: str
    page: Optional[int] = None
    chunk_id: Optional[str] = None

    def render(self) -> str:
        parts = [self.source_id]
        if self.page is not None:
            parts.append(f"p.{self.page}")
        if self.chunk_id:
            parts.append(self.chunk_id)
        return ":".join(parts)


@dataclass
class Claim:
    claim: str
    citations: List[Citation] = field(default_factory=list)


@dataclass
class Section:
    title: str
    content: str
    claims: List[Claim] = field(default_factory=list)


@dataclass
class Report:
    """A report, mirroring schemas.Report."""

    title: str
    executive_summary: str
    sections: List[Section]
    conclusions: str
    file: Optional[str] = None

    @classmethod
    def from_document(cls, data: dict, entry: dict) -> "Report":
        where = entry.get("file", "report")
        sections = []
        for i, raw in enumerate(data.get("sections", [])):
            loc = f"{where} section {i + 1}"
            claims = []
            for claim in raw.get("claims", []):
                citations = [
                    Citation(
                        source_id=require(c, "source_id", str, loc),
                        page=c.get("page"),
                        chunk_id=c.get("chunk_id"),
                    )
                    for c in claim.get("citations", [])
                ]
                claims.append(Claim(require(claim, "claim", str, loc), citations))
            sections.append(
                Section(
                    title=require(raw, "title", str, loc),
                    content=require(raw, "content", str, loc),
                    claims=claims,
                )
            )
        if not sections:
            raise ValueError(f"{where}: report has no sections")
        return cls(
            title=require(data, "title", str, where),
            executive_summary=require(data, "executive_summary", str, where),
            sections=sections,
            conclusions=require(data, "conclusions", str, where),
            file=entry.get("file"),
        )

    def claim_count(self) -> int:
        return sum(len(s.claims) for s in self.sections)

    def citation_count(self) -> int:
        return sum(len(c.citations) for s in self.sections for c in s.claims)

    def sources(self) -> List[str]:
        seen: List[str] = []
        for section in self.sections:
            for claim in section.claims:
                for cite in claim.citations:
                    if cite.source_id not in seen:
                        seen.append(cite.source_id)
        return seen

    def word_count(self) -> int:
        words = len(self.executive_summary.split()) + len(self.conclusions.split())
        for section in self.sections:
            words += len(section.content.split())
            words += sum(len(c.claim.split()) for c in section.claims)
        return words


class ReportsApp(LibraryApp):
    """Reader for a folder of generated reports."""

    window_title = "Report Reader"
    window_size = "1180x780"

    def __init__(self, api: ContentAPI):
        self._marks: List[str] = []
        super().__init__(api, "reports")
        self.set_hint("select a section to jump · type to search within the report")

    # -- library hooks -----------------------------------------------------

    def load_one(self, data: dict, entry: dict) -> Report:
        return Report.from_document(data, entry)

    def title_of(self, doc: Report) -> str:
        return doc.title

    def describe(self, doc: Report) -> Sequence[Chunk]:
        sources = ", ".join(doc.sources()) or "none"
        return [
            (doc.title + "\n\n", "h2"),
            (f"Sections: {len(doc.sections)}\n", "dim"),
            (f"Claims: {doc.claim_count()}\n", "dim"),
            (f"Citations: {doc.citation_count()}\n", "dim"),
            (f"Words: {doc.word_count():,}\n", "dim"),
            (f"Sources: {sources}\n", "dim"),
            (f"File: {doc.file or 'n/a'}\n\n", "dim"),
            ("Outline\n", "h3"),
            ("".join(f"  {i + 1}. {s.title}\n" for i, s in enumerate(doc.sections)), None),
        ]

    def build_toolbar(self, toolbar: ttk.Frame) -> None:
        toolbar.columnconfigure(4, weight=1)

        ttk.Label(toolbar, text="Jump to:").grid(row=0, column=2)
        self.jump_var = tk.StringVar()
        self.jump_combo = ttk.Combobox(
            toolbar, textvariable=self.jump_var, width=42, state="readonly"
        )
        self.jump_combo.grid(row=0, column=3, padx=(6, 12))
        self.jump_combo.bind("<<ComboboxSelected>>", lambda _e: self._jump())

        search = ttk.Frame(toolbar)
        search.grid(row=0, column=5, sticky="e")
        ttk.Label(search, text="Find:").grid(row=0, column=0, padx=(0, 6))
        self.search_var = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.search_var, width=24)
        entry.grid(row=0, column=1)
        entry.bind("<KeyRelease>", lambda _e: self._search())
        self.hits_label = ttk.Label(search, text="", foreground="#6b7580", width=10)
        self.hits_label.grid(row=0, column=2, padx=(8, 0))

        self.claims_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toolbar, text="Show claims", variable=self.claims_var, command=self._rerender
        ).grid(row=0, column=6, padx=(12, 0))

    def build_content(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.body = RichText(frame, padx=18, pady=14)
        self.body.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.body.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.body.configure(yscrollcommand=scroll.set)

    def show(self, doc: Report) -> None:
        labels = ["Executive Summary", *[s.title for s in doc.sections], "Conclusions"]
        self.jump_combo.configure(values=labels)
        self.jump_var.set(labels[0])
        self._rerender()
        self.body.yview_moveto(0.0)

    # -- rendering ---------------------------------------------------------

    def _rerender(self) -> None:
        doc = self.selected()
        if doc is None:
            return
        chunks: List[Chunk] = [(doc.title + "\n", "h1")]
        offsets: List[int] = []

        def mark() -> None:
            offsets.append(sum(text.count("\n") for text, _ in chunks))

        mark()
        chunks.append(("Executive Summary\n", "h2"))
        chunks.append((doc.executive_summary + "\n", "body"))

        for section in doc.sections:
            mark()
            chunks.append((section.title + "\n", "h2"))
            chunks.append((section.content + "\n", "body"))
            if section.claims and self.claims_var.get():
                chunks.append(("Key claims\n", "h3"))
                for claim in section.claims:
                    chunks.append((f"• {claim.claim}\n", "claim"))
                    if claim.citations:
                        rendered = ", ".join(c.render() for c in claim.citations)
                        chunks.append((f"  {rendered}\n", "cite"))

        mark()
        chunks.append(("Conclusions\n", "h2"))
        chunks.append((doc.conclusions + "\n", "body"))

        self.body.set_chunks(chunks)
        self._marks = [f"{line + 1}.0" for line in offsets]
        self.set_status(
            f"{len(doc.sections)} sections · {doc.claim_count()} claims · "
            f"{doc.citation_count()} citations · {doc.word_count():,} words"
        )
        self._search()

    def _jump(self) -> None:
        values = list(self.jump_combo.cget("values"))
        try:
            idx = values.index(self.jump_var.get())
        except ValueError:
            return
        if idx < len(self._marks):
            self.body.see(self._marks[idx])
            self.body.yview(self._marks[idx])

    def _search(self) -> None:
        term = self.search_var.get()
        hits = self.body.highlight(term)
        self.hits_label.config(text=f"{hits} hit{'s' if hits != 1 else ''}" if term else "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read generated reports in a GUI")
    add_api_argument(parser)
    args = parser.parse_args()

    ReportsApp(connect_api(args.api_url)).mainloop()


if __name__ == "__main__":
    main()
