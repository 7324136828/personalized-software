"""Shared tkinter shell and entry point for generated-content launchers.

The flashcard, report, and slide launchers all present the same frame: a list
of JSON documents on the left, a details pane beneath it, a content area on the
right, and a status bar. ``LibraryApp`` supplies that frame; a subclass supplies
the loading, description, and rendering.

Documents are fetched from the local content backend (``python/backend/server.py``)
over HTTP rather than read from the output folder, so every launcher needs that
server running. Start it with ``python run_app.py serve`` (or ``dev``).

Standard library only.

Run this file directly to open a hub for every desktop viewer::

    python python/launcher_common.py
    python python/launcher_common.py --list
    python python/launcher_common.py --launch qanda
    python python/launcher_common.py --api-url http://127.0.0.1:8765
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
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


def require(data: dict, field: str, kind: type, where: str) -> Any:
    """Fetch a required field, raising a readable error if missing or mistyped."""
    if field not in data:
        raise ValueError(f"{where}: missing required field {field!r}")
    if not isinstance(data[field], kind):
        raise ValueError(f"{where}: field {field!r} must be {kind.__name__}")
    return data[field]


# --------------------------------------------------------------------------
# Content backend client
# --------------------------------------------------------------------------

DEFAULT_API_URL = os.environ.get("CONTENT_API_URL") or "http://127.0.0.1:4173"


class ContentAPIError(RuntimeError):
    """The content backend could not be reached or returned an error status."""


class ContentAPI:
    """Minimal read-only client for ``python/backend/server.py``.

    Launchers pull their documents (and any side-car files) from the running
    backend instead of reading the output folder directly. The backend merges
    every subject under ``new_output/<subject>/<kind>/`` into one list per kind.
    """

    def __init__(self, base_url: str = DEFAULT_API_URL, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._cache_dir: Optional[Path] = None

    def _get(self, path: str) -> bytes:
        url = self.base_url + path
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise ContentAPIError(f"{url} returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ContentAPIError(
                f"Cannot reach the content backend at {self.base_url} ({reason}).\n"
                f"Start it first:  python run_app.py serve"
            ) from exc

    def post(self, path: str, payload: Optional[dict] = None) -> Tuple[int, dict]:
        """POST JSON to ``path`` and return ``(status_code, parsed_body)``.

        An HTTP error status is returned rather than raised so callers can show
        the backend's own message (the ``/api/generate_podcast`` placeholder, for
        example, replies 501).
        """
        url = self.base_url + path
        body = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ContentAPIError(
                f"Cannot reach the content backend at {self.base_url} ({reason}).\n"
                f"Start it first:  python run_app.py serve"
            ) from exc
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {}
        return status, parsed

    def check(self) -> None:
        """Confirm the backend is reachable; raise ContentAPIError otherwise."""
        self._get("/api/health")

    def manifest(self) -> dict:
        return json.loads(self._get("/api/content/manifest").decode("utf-8"))

    def entries(self, kind: str) -> List[dict]:
        """Manifest rows for one kind (``quizzes``, ``reports`` …).

        Each row has ``file``, ``stem``, ``title``, ``sidecars`` and ``subject``.
        """
        return list(self.manifest().get("kinds", {}).get(kind, []))

    @staticmethod
    def _encode(file: str) -> str:
        return "/".join(urllib.parse.quote(part) for part in file.split("/"))

    def document_bytes(self, kind: str, file: str) -> bytes:
        return self._get(f"/api/content/{kind}/{self._encode(file)}")

    def document_json(self, kind: str, file: str) -> dict:
        return json.loads(self.document_bytes(kind, file).decode("utf-8"))

    def download(self, kind: str, file: str) -> Path:
        """Fetch a file into a private temp cache and return its local path.

        For side-cars the OS needs as real files: podcast audio and the
        infographic HTML/SVG exports and their referenced assets.
        """
        if self._cache_dir is None:
            self._cache_dir = Path(tempfile.mkdtemp(prefix="content-cache-"))
        target = self._cache_dir / kind / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.document_bytes(kind, file))
        return target


def add_api_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``--api-url`` option to a launcher's argument parser."""
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        metavar="URL",
        help=f"Base URL of the content backend (default: {DEFAULT_API_URL})",
    )


def connect_api(api_url: str) -> ContentAPI:
    """Return a ready :class:`ContentAPI`, or exit with a readable message."""
    api = ContentAPI(api_url)
    try:
        api.check()
    except ContentAPIError as exc:
        raise SystemExit(str(exc))
    return api


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

    def __init__(self, api: ContentAPI, kind: str):
        super().__init__()
        self.api = api
        self.kind = kind
        self.docs: List[Any] = []

        self.title(self.window_title)
        self.geometry(self.window_size)
        self.minsize(860, 560)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_frame()
        self.refresh()

    # -- overridable hooks -------------------------------------------------

    def load_one(self, data: dict, entry: dict) -> Any:
        """Build one document from its parsed JSON and its manifest row.

        ``entry`` carries ``file``, ``stem``, ``title``, ``sidecars`` and
        ``subject``.
        """
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
        self.docs, errors = [], []
        try:
            entries = self.api.entries(self.kind)
        except ContentAPIError as exc:
            self.listbox.delete(0, "end")
            self.details.set_chunks([(f"{exc}\n", "dim")])
            self.set_status("Backend unavailable")
            messagebox.showerror("Content backend unavailable", str(exc), parent=self)
            return
        for entry in entries:
            file = entry.get("file", "?")
            try:
                data = self.api.document_json(self.kind, file)
                self.docs.append(self.load_one(data, entry))
            except (ContentAPIError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{file}: {exc}")
        self.listbox.delete(0, "end")
        for doc in self.docs:
            self.listbox.insert("end", self.title_of(doc))
        if self.docs:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self._select()
        else:
            self.details.set_chunks(
                [(f"No {self.kind} available from {self.api.base_url}\n", "dim")]
            )
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


def launcher_command(spec: LauncherSpec, api_url: str) -> List[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve().parent / spec.script),
        "--api-url",
        api_url,
    ]


def available_kinds(api_url: str) -> Tuple[set, Optional[str]]:
    """Kinds the backend currently has content for, plus an error string if down."""
    try:
        manifest = ContentAPI(api_url).manifest()
    except ContentAPIError as exc:
        return set(), str(exc)
    kinds = manifest.get("kinds", {})
    return {name for name, rows in kinds.items() if rows}, None


def run_launcher(spec: LauncherSpec, api_url: str, wait: bool = False) -> int:
    """Start one viewer using the same interpreter as this process."""
    script = project_root() / "python" / spec.script
    if not script.is_file():
        raise FileNotFoundError(f"Launcher script not found: {script}")
    if wait:
        return subprocess.call(launcher_command(spec, api_url), cwd=project_root())
    subprocess.Popen(launcher_command(spec, api_url), cwd=project_root())
    return 0


class LauncherHub(tk.Tk):
    """Small home screen for opening any generated-content desktop viewer."""

    def __init__(self, api_url: str = DEFAULT_API_URL) -> None:
        super().__init__()
        self.api_url = api_url
        self.available, self.error = available_kinds(api_url)

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
        subtitle = (
            self.error
            if self.error
            else f"Content served by the backend at {api_url}."
        )
        ttk.Label(
            header,
            text=subtitle,
            foreground="#b42318" if self.error else "#6b7580",
            wraplength=760,
            justify="left",
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
            available = (not self.error) and spec.data_folder in self.available
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
                    text="Backend offline" if self.error else f"No {spec.label.lower()} on the server",
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
            run_launcher(spec, self.api_url)
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
    add_api_argument(parser)
    args = parser.parse_args(argv)

    if args.list:
        available, error = available_kinds(args.api_url)
        if error:
            print(error, file=sys.stderr)
        for spec in LAUNCHERS:
            state = "available" if spec.data_folder in available else "no content"
            print(f"{spec.key:14} {state:16} {spec.script}")
        return 0
    if args.launch:
        spec = next(item for item in LAUNCHERS if item.key == args.launch)
        try:
            return run_launcher(spec, args.api_url, wait=True)
        except FileNotFoundError as error:
            parser.error(str(error))

    LauncherHub(args.api_url).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
