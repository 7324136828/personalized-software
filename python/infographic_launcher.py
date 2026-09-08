"""Sample GUI application for viewing generated infographics.

Scans a folder of infographic JSON files (the format produced by
``python/ollama_learning/infographic.py`` and defined by
``ollama_learning.schemas.Infographic``) and renders the sections natively:
stat cards, drawn bar charts, numbered flows, comparison pairs, and pull quotes.

Standard library only.

    python python/infographic_launcher.py
    python python/infographic_launcher.py --api-url http://127.0.0.1:8765
"""

import argparse
import re
import tkinter as tk
import webbrowser
from dataclasses import dataclass, field
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Sequence, Tuple

from launcher_common import (
    Chunk,
    ContentAPI,
    ContentAPIError,
    LibraryApp,
    add_api_argument,
    connect_api,
    require,
)

SECTION_TYPES = ("stat", "flow", "chart", "quote", "comparison", "svg")

# Mirrors infographic._CHART_ITEM so the launcher and the generator agree.
_CHART_ITEM = re.compile(r"^(?P<label>.+?)\s*[:|—-]\s*(?P<value>[\d.]+)\s*(?P<unit>%|[A-Za-z]*)$")

INK = "#16293f"
MUTED = "#6b7580"
ACCENT = "#2f6f9f"
ACCENT_SOFT = "#dce9f5"
CARD_BG = "#ffffff"
PAGE_BG = "#f4f6f8"
LINE = "#dbe2ea"


def parse_chart_item(item: str) -> Tuple[str, Optional[float], str]:
    """Split a chart item into (label, numeric value, unit). Value is None if absent."""
    match = _CHART_ITEM.match(item.strip())
    if not match:
        return item.strip(), None, ""
    try:
        return match.group("label").strip(), float(match.group("value")), match.group("unit")
    except ValueError:
        return item.strip(), None, ""


@dataclass
class Section:
    """One infographic section, mirroring schemas.InfographicSection."""

    type: str
    title: Optional[str] = None
    value: Optional[str] = None
    label: Optional[str] = None
    items: List[str] = field(default_factory=list)
    panel: Optional[str] = None
    span: str = "full"

    @classmethod
    def from_dict(cls, data: dict, where: str) -> "Section":
        section_type = require(data, "type", str, where)
        if section_type not in SECTION_TYPES:
            raise ValueError(f"{where}: unknown section type {section_type!r}")
        items = data.get("items") or []
        if not isinstance(items, list):
            raise ValueError(f"{where}: 'items' must be a list")
        return cls(
            type=section_type,
            title=data.get("title"),
            value=data.get("value"),
            label=data.get("label"),
            items=[str(i) for i in items],
            panel=data.get("panel"),
            span=data.get("span", "full"),
        )


@dataclass
class Graphic:
    """An infographic, mirroring schemas.Infographic."""

    title: str
    sections: List[Section]
    subtitle: Optional[str] = None
    file: Optional[str] = None
    sidecars: List[str] = field(default_factory=list)

    @classmethod
    def from_document(cls, data: dict, entry: dict) -> "Graphic":
        where = entry.get("file", "infographic")
        sections = require(data, "sections", list, where)
        if not sections:
            raise ValueError(f"{where}: infographic has no sections")
        return cls(
            title=require(data, "title", str, where),
            sections=[Section.from_dict(s, f"{where} section {i + 1}")
                      for i, s in enumerate(sections)],
            subtitle=data.get("subtitle"),
            file=entry.get("file"),
            sidecars=list(entry.get("sidecars", [])),
        )

    def type_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for section in self.sections:
            counts[section.type] = counts.get(section.type, 0) + 1
        return counts

    def _sidecar(self, suffix: str) -> Optional[str]:
        """Name of the first side-car ending with ``suffix``, served by the backend."""
        return next((name for name in self.sidecars if name.endswith(suffix)), None)

    def html_name(self) -> Optional[str]:
        return self._sidecar(".html")

    def svg_name(self) -> Optional[str]:
        return self._sidecar(".svg")

    def wireframe_name(self) -> Optional[str]:
        """The pre-infographic side-car, <name>.wireframe.txt."""
        return self._sidecar(".wireframe.txt")

    def panel_names(self) -> List[str]:
        names: List[str] = []
        for section in self.sections:
            if section.panel and section.panel not in names:
                names.append(section.panel)
        return names


class ScrollFrame(ttk.Frame):
    """A vertically scrolling container whose inner frame tracks the canvas width."""

    def __init__(self, master: tk.Misc, background: str = PAGE_BG):
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, background=background, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=bar.set)

        self.inner = tk.Frame(self.canvas, background=background)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

    def _on_inner(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_wheel(self, event) -> None:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()

    def to_top(self) -> None:
        self.canvas.yview_moveto(0.0)


class InfographicApp(LibraryApp):
    """Native renderer for a folder of infographic specifications."""

    window_title = "Infographic Viewer"
    window_size = "1180x800"

    def __init__(self, api: ContentAPI):
        self.cards: List[tk.Widget] = []
        super().__init__(api, "infographics")
        self.set_hint("scroll to read · filter by section type · open the HTML export in a browser")

    # -- library hooks -----------------------------------------------------

    def load_one(self, data: dict, entry: dict) -> Graphic:
        return Graphic.from_document(data, entry)

    def title_of(self, doc: Graphic) -> str:
        return doc.title

    def describe(self, doc: Graphic) -> Sequence[Chunk]:
        counts = ", ".join(f"{t}: {n}" for t, n in sorted(doc.type_counts().items()))
        html = doc.html_name()
        panels = doc.panel_names()
        wire, svg = doc.wireframe_name(), doc.svg_name()
        exports = ", ".join(n for n in ("html" if html else "", "svg" if svg else "") if n)
        chunks: List[Chunk] = [(doc.title + "\n", "h2")]
        if doc.subtitle:
            chunks.append((doc.subtitle + "\n", "dim"))
        chunks += [
            ("\n", None),
            (f"Panels: {len(panels) or 1}\n", "dim"),
            (f"Sections: {len(doc.sections)}\n", "dim"),
            (f"Types: {counts}\n", "dim"),
            (f"File: {doc.file or 'n/a'}\n", "dim"),
            (f"Pre-infographic: {'yes' if wire else 'not written'}\n", "dim"),
            (f"Exports: {exports or 'none'}\n\n", "dim"),
        ]
        if panels:
            chunks.append(("Panels\n", "h3"))
            for i, name in enumerate(panels, start=1):
                count = sum(1 for s in doc.sections if s.panel == name)
                chunks.append((f"  {i}. {name}", None))
                chunks.append((f"  ({count})\n", "dim"))
            chunks.append(("\n", None))
        chunks.append(("Sections\n", "h3"))
        for i, section in enumerate(doc.sections, start=1):
            chunks.append((f"  {i}. {section.title or section.type.title()}", None))
            chunks.append((f"  [{section.type}]\n", "dim"))
        return chunks

    def build_toolbar(self, toolbar: ttk.Frame) -> None:
        toolbar.columnconfigure(4, weight=1)
        ttk.Label(toolbar, text="Show type:").grid(row=0, column=2)
        self.type_var = tk.StringVar(value="(all)")
        self.type_combo = ttk.Combobox(
            toolbar, textvariable=self.type_var, width=14, state="readonly",
            values=["(all)", *SECTION_TYPES],
        )
        self.type_combo.grid(row=0, column=3, padx=(6, 0))
        self.type_combo.bind("<<ComboboxSelected>>", lambda _e: self._render())

        self.wire_button = ttk.Button(
            toolbar, text="Pre-infographic", command=self.show_wireframe
        )
        self.wire_button.grid(row=0, column=5, sticky="e", padx=(0, 6))
        self.open_button = ttk.Button(toolbar, text="Open HTML export", command=self.open_html)
        self.open_button.grid(row=0, column=6, sticky="e")

    def build_content(self, parent: ttk.Frame) -> None:
        self.scroll = ScrollFrame(parent)
        self.scroll.grid(row=0, column=0, sticky="nsew")

    def show(self, doc: Graphic) -> None:
        self.type_var.set("(all)")
        self._render()
        self.scroll.to_top()

    # -- rendering ---------------------------------------------------------

    def _render(self) -> None:
        doc = self.selected()
        if doc is None:
            return
        self.scroll.clear()
        self.cards = []

        wanted = self.type_var.get()
        sections = [s for s in doc.sections if wanted == "(all)" or s.type == wanted]

        header = tk.Label(
            self.scroll.inner, text=doc.title, font=("Segoe UI", 19, "bold"),
            background=PAGE_BG, foreground=INK, anchor="w", justify="left", wraplength=820,
        )
        header.pack(fill="x", padx=22, pady=(20, 2))
        if doc.subtitle:
            tk.Label(
                self.scroll.inner, text=doc.subtitle, font=("Segoe UI", 10), background=PAGE_BG,
                foreground=MUTED, anchor="w", justify="left", wraplength=820,
            ).pack(fill="x", padx=22, pady=(0, 10))

        for number, name, panel_sections in self._panels(sections):
            if name:
                self._panel_heading(number, name)
            for section in panel_sections:
                self.cards.append(self._render_section(section))

        if not sections:
            tk.Label(
                self.scroll.inner, text="No sections of that type.", background=PAGE_BG,
                foreground=MUTED, anchor="w",
            ).pack(fill="x", padx=22, pady=10)

        tk.Frame(self.scroll.inner, background=PAGE_BG, height=18).pack(fill="x")
        self.scroll._on_inner()

        html = doc.html_name()
        self.open_button.configure(state="normal" if html else "disabled")
        self.wire_button.configure(state="normal" if doc.wireframe_name() else "disabled")
        panel_count = len(doc.panel_names()) or 1
        self.set_status(
            f"{panel_count} panel(s) · {len(sections)} of {len(doc.sections)} sections shown"
            + (f"   ·   exports: {html}" if html else "   ·   no HTML export yet")
        )

    def _panels(self, sections: List[Section]):
        """Group sections into (number, panel name, sections), preserving order.

        Numbering follows the full spec so a type filter does not renumber panels.
        """
        doc = self.selected()
        order: List[Optional[str]] = []
        for section in (doc.sections if doc else sections):
            key = section.panel or None
            if key not in order:
                order.append(key)
        buckets: Dict[Optional[str], List[Section]] = {}
        for section in sections:
            buckets.setdefault(section.panel or None, []).append(section)
        return [
            (i, name, buckets[name])
            for i, name in enumerate(order, start=1)
            if name in buckets
        ]

    def _panel_heading(self, number: int, name: str) -> None:
        bar = tk.Frame(self.scroll.inner, background=PAGE_BG)
        bar.pack(fill="x", padx=22, pady=(14, 2))
        tk.Label(
            bar, text=str(number), width=3, font=("Segoe UI", 9, "bold"),
            background=ACCENT, foreground="#ffffff",
        ).pack(side="left")
        tk.Label(
            bar, text=name, font=("Segoe UI", 11, "bold"), background=PAGE_BG,
            foreground=INK, anchor="w", justify="left", wraplength=740,
        ).pack(side="left", padx=(10, 0), fill="x", expand=True)

    def _card(self) -> tk.Frame:
        card = tk.Frame(
            self.scroll.inner, background=CARD_BG, highlightthickness=1,
            highlightbackground=LINE, bd=0,
        )
        card.pack(fill="x", padx=22, pady=7)
        return card

    def _kicker(self, card: tk.Frame, section: Section) -> None:
        if section.title:
            tk.Label(
                card, text=section.title.upper(), font=("Segoe UI", 8, "bold"),
                background=CARD_BG, foreground=MUTED, anchor="w",
            ).pack(fill="x", padx=20, pady=(16, 6))

    def _render_section(self, section: Section) -> tk.Widget:
        card = self._card()
        self._kicker(card, section)

        if section.type == "stat":
            tk.Label(
                card, text=section.value or "", font=("Segoe UI", 30, "bold"),
                background=CARD_BG, foreground=ACCENT, anchor="w",
            ).pack(fill="x", padx=20)
            tk.Label(
                card, text=section.label or "", font=("Segoe UI", 10), background=CARD_BG,
                foreground=MUTED, anchor="w", justify="left", wraplength=760,
            ).pack(fill="x", padx=20, pady=(2, 18))

        elif section.type == "quote":
            tk.Label(
                card, text=f"“{section.value or ''}”", font=("Segoe UI", 14),
                background=CARD_BG, foreground=INK, anchor="w", justify="left", wraplength=760,
            ).pack(fill="x", padx=20)
            tk.Label(
                card, text=f"— {section.label}" if section.label else "", font=("Segoe UI", 9),
                background=CARD_BG, foreground=MUTED, anchor="w",
            ).pack(fill="x", padx=20, pady=(8, 18))

        elif section.type == "flow":
            for i, item in enumerate(section.items, start=1):
                row = tk.Frame(card, background=CARD_BG)
                row.pack(fill="x", padx=20, pady=3)
                tk.Label(
                    row, text=str(i), width=2, font=("Segoe UI", 9, "bold"),
                    background=ACCENT_SOFT, foreground=ACCENT,
                ).pack(side="left")
                tk.Label(
                    row, text=item, font=("Segoe UI", 10), background=CARD_BG, foreground=INK,
                    anchor="w", justify="left", wraplength=700,
                ).pack(side="left", padx=(10, 0), fill="x", expand=True)
            tk.Frame(card, background=CARD_BG, height=12).pack()

        elif section.type == "chart":
            self._render_chart(card, section)

        elif section.type == "svg":
            self._render_svg_placeholder(card, section)

        else:  # comparison
            for item in section.items:
                row = tk.Frame(card, background=CARD_BG)
                row.pack(fill="x", padx=20, pady=5)
                if " vs " in item:
                    left, right = item.split(" vs ", 1)
                    tk.Label(row, text=left.strip(), font=("Segoe UI", 10), background=CARD_BG,
                             foreground=INK, anchor="w", justify="left", wraplength=330,
                             ).pack(side="left", fill="x", expand=True)
                    tk.Label(row, text="vs", font=("Segoe UI", 8, "bold"), background=CARD_BG,
                             foreground=MUTED).pack(side="left", padx=10)
                    tk.Label(row, text=right.strip(), font=("Segoe UI", 10), background=CARD_BG,
                             foreground=INK, anchor="w", justify="left", wraplength=330,
                             ).pack(side="left", fill="x", expand=True)
                else:
                    tk.Label(row, text=item, font=("Segoe UI", 10), background=CARD_BG,
                             foreground=INK, anchor="w", justify="left", wraplength=700,
                             ).pack(side="left", fill="x", expand=True)
            tk.Frame(card, background=CARD_BG, height=12).pack()

        return card

    def _render_svg_placeholder(self, card: tk.Frame, section: Section) -> None:
        """Show an SVG section as a stub.

        Tkinter cannot rasterize SVG without a third-party library, and this
        launcher is stdlib-only — so the card reports the diagram's source and
        size and offers to open the file itself.
        """
        value = (section.value or "").strip()
        inline = "<svg" in value.lower()
        # Non-inline sections name a file the backend serves under
        # /api/content/infographics/<value> (e.g. "assets/foo.svg").
        target = None
        if value and not inline:
            try:
                target = self.api.download("infographics", value)
            except ContentAPIError:
                target = None
        exists = bool(inline) or target is not None

        box = tk.Frame(card, background="#f7f9fb", highlightthickness=1, highlightbackground=LINE)
        box.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(
            box, text="◨  SVG diagram", font=("Segoe UI", 11, "bold"),
            background="#f7f9fb", foreground=ACCENT, anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 2))

        if inline:
            detail = f"inline markup, {len(value):,} characters"
        elif exists:
            detail = f"{value}  ·  {target.stat().st_size:,} bytes"
        else:
            detail = f"{value}  ·  not served by the backend"
        tk.Label(
            box, text=detail, font=("Segoe UI", 9), background="#f7f9fb",
            foreground=MUTED if exists else "#b42318", anchor="w", justify="left", wraplength=700,
        ).pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(
            box, text="Rendered in the HTML and SVG exports.", font=("Segoe UI", 9),
            background="#f7f9fb", foreground=MUTED, anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 10))

        if target is not None and exists:
            ttk.Button(
                box, text="Open diagram", width=16,
                command=lambda t=target: webbrowser.open(t.resolve().as_uri()),
            ).pack(anchor="w", padx=14, pady=(0, 12))

        if section.label:
            tk.Label(
                card, text=section.label, font=("Segoe UI", 9), background=CARD_BG,
                foreground=MUTED, anchor="w", justify="left", wraplength=740,
            ).pack(fill="x", padx=20, pady=(0, 14))

    def _render_chart(self, card: tk.Frame, section: Section) -> None:
        parsed = [parse_chart_item(item) for item in section.items]
        values = [v for _, v, _ in parsed if v is not None]
        peak = max(values) if values else 0

        row_h, gap = 22, 6
        height = len(parsed) * (row_h + gap) + gap
        canvas = tk.Canvas(card, height=height, background=CARD_BG, highlightthickness=0)
        canvas.pack(fill="x", padx=20, pady=(0, 16))
        canvas.bind(
            "<Configure>",
            lambda e, c=canvas, p=parsed, pk=peak, rh=row_h, g=gap: self._draw_bars(c, p, pk, rh, g),
        )

    @staticmethod
    def _draw_bars(canvas: tk.Canvas, parsed, peak: float, row_h: int, gap: int) -> None:
        canvas.delete("all")
        width = canvas.winfo_width()
        label_w = min(240, max(110, int(width * 0.3)))
        value_w = 62
        track_x0 = label_w + 12
        track_x1 = max(track_x0 + 20, width - value_w)

        for i, (label, value, unit) in enumerate(parsed):
            y = gap + i * (row_h + gap) + row_h / 2
            canvas.create_text(label_w, y, text=label, anchor="e", fill=INK, font=("Segoe UI", 9))
            canvas.create_rectangle(
                track_x0, y - 6, track_x1, y + 6, fill=ACCENT_SOFT, outline="",
            )
            if value is not None and peak:
                fill_x = track_x0 + (track_x1 - track_x0) * (value / peak)
                canvas.create_rectangle(track_x0, y - 6, fill_x, y + 6, fill=ACCENT, outline="")
                shown = f"{value:g}{unit}"
                canvas.create_text(
                    width - 6, y, text=shown, anchor="e", fill=MUTED, font=("Segoe UI", 9)
                )

    # -- actions -----------------------------------------------------------

    def show_wireframe(self) -> None:
        """Open the pre-infographic — the wireframe written before finalizing."""
        doc = self.selected()
        wire = doc.wireframe_name() if doc else None
        if wire is None:
            messagebox.showinfo(
                "No pre-infographic",
                "This infographic has no wireframe alongside it.\n\n"
                "Generate one with:\n"
                "  python python/ollama_learning/infographic.py "
                "--pre-infographic out.wireframe.txt …",
                parent=self,
            )
            return
        try:
            wireframe_text = self.api.document_bytes("infographics", wire).decode("utf-8")
        except ContentAPIError as error:
            messagebox.showerror("Could not load the wireframe", str(error), parent=self)
            return
        win = tk.Toplevel(self)
        win.title(f"Pre-infographic: {doc.title}")
        win.geometry("760x720")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        ttk.Label(
            win, text="Wireframe stage — review this layout before the final render",
            padding=(14, 10), foreground=MUTED,
        ).grid(row=0, column=0, sticky="w")
        text = tk.Text(win, wrap="none", font=("Consolas", 10), relief="flat", padx=12, pady=8)
        text.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        bar.grid(row=1, column=1, sticky="ns")
        text.configure(yscrollcommand=bar.set)
        text.insert("1.0", wireframe_text)
        text.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).grid(
            row=2, column=0, columnspan=2, sticky="e", padx=14, pady=10
        )
        win.focus_set()

    def open_html(self) -> None:
        doc = self.selected()
        html = doc.html_name() if doc else None
        if html is None:
            messagebox.showinfo(
                "No HTML export",
                "This infographic has no sibling .html file.\n\n"
                "Generate one with:\n"
                "  python python/ollama_learning/infographic.py --format html …",
                parent=self,
            )
            return
        try:
            local = self.api.download("infographics", html)
        except ContentAPIError as error:
            messagebox.showerror("Could not load the HTML export", str(error), parent=self)
            return
        webbrowser.open(local.resolve().as_uri())
        self.set_status(f"Opened {html} in your browser")


def main() -> None:
    parser = argparse.ArgumentParser(description="View generated infographics in a GUI")
    add_api_argument(parser)
    args = parser.parse_args()

    InfographicApp(connect_api(args.api_url)).mainloop()


if __name__ == "__main__":
    main()
