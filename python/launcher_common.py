"""Shared tkinter shell and entry point for generated-content launchers.

The flashcard, report, and slide launchers all present the same frame: a folder
of JSON documents on the left, a details pane beneath it, a content area on the
right, and a status bar. ``LibraryApp`` supplies that frame; a subclass supplies
the loading, description, and rendering.

Standard library only.

Run this file directly to open a hub for every desktop viewer::

    python python/launcher_common.py
    python python/launcher_common.py --list
    python python/launcher_common.py --launch qanda
"""

import argparse
import json
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Any, List, Optional, Sequence, Tuple

Chunk = Tuple[str, Optional[str]]  # (text, tag)


@dataclass(frozen=True)
class LauncherSpec:
    """Metadata for one desktop content viewer."""

    key: str
    label: str
    description: str
    script: str
    data_folder: str


LAUNCHERS = (
    LauncherSpec("quizzes", "Quizzes", "Take scored multiple-choice quizzes.", "quiz_launcher.py", "quizzes"),
    LauncherSpec("qanda", "Q&A", "Write, autosave, and export free-text responses.", "qanda_launcher.py", "qandas"),
    LauncherSpec("flashcards", "Flashcards", "Review generated study cards.", "flashcards_launcher.py", "flashcards"),
    LauncherSpec("mindmaps", "Mind maps", "Explore hierarchical concept maps.", "mindmap_viewer.py", "mindmaps"),
    LauncherSpec("reports", "Reports", "Read reports, claims, and citations.", "reports_launcher.py", "reports"),
    LauncherSpec("slides", "Slides", "Browse and present generated slide decks.", "slides_launcher.py", "slides"),
    LauncherSpec("datatables", "Data tables", "Filter and inspect extracted records.", "datatable_launcher.py", "datatables"),
    LauncherSpec("infographics", "Infographics", "Browse generated visual summaries.", "infographic_launcher.py", "infographics"),
    LauncherSpec("podcasts", "Podcasts", "Play, read, and save generated podcast episodes.", "podcast_launcher.py", "podcasts"),
)


def load_documents(folder: Path, loader) -> Tuple[List[Any], List[str]]:
    """Load every *.json file in a folder with `loader`. Returns (docs, errors)."""
    docs, errors = [], []
    for path in sorted(folder.glob("*.json")):
        try:
            docs.append(loader(path))
        except Exception as exc:  # one malformed file shouldn't kill the launcher
            errors.append(f"{path.name}: {exc}")
    return docs, errors


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(data: dict, field: str, kind: type, where: str) -> Any:
    """Fetch a required field, raising a readable error if missing or mistyped."""
    if field not in data:
        raise ValueError(f"{where}: missing required field {field!r}")
    if not isinstance(data[field], kind):
        raise ValueError(f"{where}: field {field!r} must be {kind.__name__}")
    return data[field]


class RichText(tk.Text):
    """A read-only Text widget that renders (text, tag) chunk lists."""

    def __init__(self, master: tk.Misc, **kwargs):
        kwargs.setdefault("wrap", "word")
        kwargs.setdefault("relief", "flat")
        kwargs.setdefault("padx", 8)
        kwargs.setdefault("pady", 6)
        super().__init__(master, **kwargs)
        base = tkfont.nametofont("TkDefaultFont").actual()
        family = base["family"]
        self.tag_configure("h1", font=(family, 15, "bold"), spacing1=4, spacing3=8)
        self.tag_configure("h2", font=(family, 11, "bold"), spacing1=10, spacing3=4)
        self.tag_configure("h3", font=(family, 10, "bold"), spacing1=6, spacing3=2)
        self.tag_configure("body", font=(family, 10), spacing3=6, lmargin1=2, lmargin2=2)
        self.tag_configure("dim", foreground="#6b7580")
        self.tag_configure("accent", foreground="#1f5fa0")
        self.tag_configure("claim", lmargin1=16, lmargin2=16, spacing3=2)
        self.tag_configure("cite", lmargin1=16, lmargin2=16, foreground="#6b7580", spacing3=6)
        self.tag_configure("bullet", lmargin1=14, lmargin2=28, spacing3=4)
        self.tag_configure("hit", background="#ffe9a8")
        self.configure(state="disabled")

    def set_chunks(self, chunks: Sequence[Chunk]) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        for text, tag in chunks:
            self.insert("end", text, tag)
        self.configure(state="disabled")

    def highlight(self, term: str) -> int:
        """Tag every occurrence of `term`. Returns the number of hits."""
        self.tag_remove("hit", "1.0", "end")
        term = term.strip()
        if not term:
            return 0
        hits, index = 0, "1.0"
        while True:
            index = self.search(term, index, nocase=True, stopindex="end")
            if not index:
                break
            end = f"{index}+{len(term)}c"
            self.tag_add("hit", index, end)
            index = end
            hits += 1
        if hits:
            self.see(self.tag_ranges("hit")[0])
        return hits


class LibraryApp(tk.Tk):
    """Three-pane launcher: document list, details, and a content area.

    Subclasses override ``load_one``, ``title_of``, ``describe``,
    ``build_content`` and ``show``.
    """

    window_title = "Library"
    window_size = "1120x740"
    list_width = 32
    details_height = 12

    def __init__(self, folder: Path):
        super().__init__()
        self.folder = folder
        self.docs: List[Any] = []

        self.title(self.window_title)
        self.geometry(self.window_size)
        self.minsize(860, 560)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_frame()
        self.refresh()

    # -- overridable hooks -------------------------------------------------

    def load_one(self, path: Path) -> Any:
        raise NotImplementedError

    def title_of(self, doc: Any) -> str:
        raise NotImplementedError

    def describe(self, doc: Any) -> Sequence[Chunk]:
        return []

    def build_toolbar(self, toolbar: ttk.Frame) -> None:
        """Add controls to the toolbar. Columns 2+ are free; 1 is a separator."""

    def build_content(self, parent: ttk.Frame) -> None:
        raise NotImplementedError

    def show(self, doc: Any) -> None:
        raise NotImplementedError

    # -- frame -------------------------------------------------------------

    def _build_frame(self) -> None:
        toolbar = ttk.Frame(self, padding=(14, 10, 14, 8))
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(toolbar, text="Reload", command=self.refresh).grid(row=0, column=0)
        ttk.Separator(toolbar, orient="vertical").grid(row=0, column=1, sticky="ns", padx=10)
        self.build_toolbar(toolbar)

        side = ttk.Frame(self, padding=(14, 0, 8, 8))
        side.grid(row=1, column=0, sticky="nsew")
        side.rowconfigure(1, weight=1)

        ttk.Label(side, text="Library", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.listbox = tk.Listbox(
            side, width=self.list_width, activestyle="dotbox", exportselection=False
        )
        self.listbox.grid(row=1, column=0, sticky="nsew", pady=(6, 8))
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._select())

        ttk.Label(side, text="Details", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w")
        self.details = RichText(side, width=self.list_width, height=self.details_height)
        self.details.grid(row=3, column=0, sticky="ew", pady=(6, 0))

        content = ttk.Frame(self)
        content.grid(row=1, column=1, sticky="nsew", padx=(0, 14), pady=(0, 8))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.build_content(content)

        status = ttk.Frame(self, padding=(14, 0, 14, 10))
        status.grid(row=2, column=0, columnspan=2, sticky="ew")
        status.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(status, text="", foreground="#6b7580")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.hint_label = ttk.Label(status, text="", foreground="#8a949e")
        self.hint_label.grid(row=0, column=1, sticky="e")

    # -- data --------------------------------------------------------------

    def refresh(self) -> None:
        self.docs, errors = load_documents(self.folder, self.load_one)
        self.listbox.delete(0, "end")
        for doc in self.docs:
            self.listbox.insert("end", self.title_of(doc))
        if self.docs:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self._select()
        else:
            self.details.set_chunks([(f"No documents found in {self.folder}\n", "dim")])
            self.set_status("")
        if errors:
            messagebox.showwarning("Some documents failed to load", "\n".join(errors), parent=self)

    def selected(self) -> Optional[Any]:
        sel = self.listbox.curselection()
        return self.docs[sel[0]] if sel else None

    def _select(self) -> None:
        doc = self.selected()
        if doc is None:
            return
        self.details.set_chunks(self.describe(doc))
        self.show(doc)

    def set_status(self, text: str) -> None:
        self.status_label.config(text=text)

    def set_hint(self, text: str) -> None:
        self.hint_label.config(text=text)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def launcher_command(spec: LauncherSpec) -> List[str]:
    return [sys.executable, str(Path(__file__).resolve().parent / spec.script)]


def launcher_available(spec: LauncherSpec) -> bool:
    root = project_root()
    return (root / "python" / spec.script).is_file() and (root / "output" / spec.data_folder).is_dir()


def run_launcher(spec: LauncherSpec, wait: bool = False) -> int:
    """Start one viewer using the same interpreter as this process."""
    script = project_root() / "python" / spec.script
    data_folder = project_root() / "output" / spec.data_folder
    if not script.is_file():
        raise FileNotFoundError(f"Launcher script not found: {script}")
    if not data_folder.is_dir():
        raise FileNotFoundError(f"Content folder not found: {data_folder}")
    if wait:
        return subprocess.call(launcher_command(spec), cwd=project_root())
    subprocess.Popen(launcher_command(spec), cwd=project_root())
    return 0


class LauncherHub(tk.Tk):
    """Small home screen for opening any generated-content desktop viewer."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Learning Content Viewers")
        self.geometry("820x610")
        self.minsize(680, 500)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(24, 20, 24, 12))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            header,
            text="Learning Content Viewers",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Choose a viewer for content currently available in output/.",
            foreground="#6b7580",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        grid = ttk.Frame(self, padding=(24, 8, 24, 18))
        grid.grid(row=1, column=0, sticky="nsew")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        for row in range((len(LAUNCHERS) + 1) // 2):
            grid.rowconfigure(row, weight=1)

        for index, spec in enumerate(LAUNCHERS):
            row, column = divmod(index, 2)
            card = ttk.LabelFrame(grid, text=spec.label, padding=(14, 10))
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0, 8) if column == 0 else (8, 0),
                pady=8,
            )
            card.columnconfigure(0, weight=1)
            ttk.Label(card, text=spec.description, wraplength=300).grid(
                row=0, column=0, sticky="nw"
            )
            available = launcher_available(spec)
            button = ttk.Button(
                card,
                text=f"Open {spec.label}",
                command=lambda selected=spec: self._open(selected),
            )
            button.grid(row=1, column=0, sticky="w", pady=(10, 0))
            if not available:
                button.configure(state="disabled")
                ttk.Label(
                    card,
                    text=f"No output/{spec.data_folder} folder",
                    foreground="#8a949e",
                ).grid(row=2, column=0, sticky="w", pady=(5, 0))

        footer = ttk.Frame(self, padding=(24, 0, 24, 18))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status = ttk.Label(footer, text=f"Python: {sys.executable}", foreground="#6b7580")
        self.status.grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Close", command=self.destroy).grid(row=0, column=1, sticky="e")

    def _open(self, spec: LauncherSpec) -> None:
        try:
            run_launcher(spec)
        except (OSError, FileNotFoundError) as error:
            messagebox.showerror(f"Could not open {spec.label}", str(error), parent=self)
            self.status.configure(text=f"Failed to open {spec.label}")
            return
        self.status.configure(text=f"Opened {spec.label}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Open the generated-content desktop viewers")
    parser.add_argument("--list", action="store_true", help="list available viewers and exit")
    parser.add_argument(
        "--launch",
        choices=[spec.key for spec in LAUNCHERS],
        help="open one viewer directly instead of showing the hub",
    )
    args = parser.parse_args(argv)

    if args.list:
        for spec in LAUNCHERS:
            state = "available" if launcher_available(spec) else "missing content folder"
            print(f"{spec.key:14} {state:22} {spec.script}")
        return 0
    if args.launch:
        spec = next(item for item in LAUNCHERS if item.key == args.launch)
        try:
            return run_launcher(spec, wait=True)
        except FileNotFoundError as error:
            parser.error(str(error))

    LauncherHub().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
