"""Sample GUI application for visualizing generated mind maps.

Scans a folder of mind map JSON files (the format produced by
``python/ollama_learning/mindmap.py`` and defined by ``ollama_learning.schemas.MindMap``)
and renders the selected map as an interactive tidy tree on a tkinter canvas:
collapsible branches, pan and zoom, depth filtering, and search highlighting.

Standard library only -- tkinter, json, pathlib, argparse.

    python python/mindmap_viewer.py
    python python/mindmap_viewer.py --mindmap-dir output/mindmaps
"""

import argparse
import json
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Tuple

# Layout constants (unscaled canvas units)
H_GAP = 46          # horizontal gap between a node box and its children
V_GAP = 12          # vertical gap between sibling subtrees
BOX_PAD_X = 10
BOX_PAD_Y = 6
LINE_HEIGHT = 15
MAX_LABEL_CHARS = 34

# Fill / outline per depth; deeper levels reuse the last entry
DEPTH_COLORS = [
    ("#1f3a5f", "#16293f", "#ffffff"),   # root: fill, outline, text
    ("#2f6f9f", "#1f4a6b", "#ffffff"),
    ("#dce9f5", "#9ab8d4", "#16293f"),
    ("#f2f5f8", "#c3d0dc", "#33414d"),
]
HIGHLIGHT = ("#ffe9a8", "#d9a300", "#4a3800")


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

@dataclass
class Node:
    """A mind map node, mirroring schemas.MindMapNode."""

    name: str
    children: List["Node"] = field(default_factory=list)
    depth: int = 0
    collapsed: bool = False
    # populated during layout
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    lines: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict, depth: int = 0) -> "Node":
        if "name" not in data:
            raise ValueError("node is missing required field 'name'")
        if not isinstance(data["name"], str):
            raise ValueError("node field 'name' must be a string")
        children = data.get("children", [])
        if not isinstance(children, list):
            raise ValueError(f"node {data['name']!r}: 'children' must be a list")
        return cls(
            name=data["name"],
            children=[cls.from_dict(c, depth + 1) for c in children],
            depth=depth,
        )

    def visible_children(self) -> List["Node"]:
        return [] if self.collapsed else self.children

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def max_depth(self) -> int:
        return self.depth if not self.children else max(c.max_depth() for c in self.children)


@dataclass
class MindMapDoc:
    root: Node
    path: Optional[Path] = None

    @classmethod
    def load(cls, path: Path) -> "MindMapDoc":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(Node.from_dict(data), path)

    @property
    def title(self) -> str:
        return self.root.name

    def node_count(self) -> int:
        return sum(1 for _ in self.root.walk())


def load_mindmap_dir(folder: Path) -> Tuple[List[MindMapDoc], List[str]]:
    """Load every *.json mind map in a folder. Returns (docs, errors)."""
    docs, errors = [], []
    for path in sorted(folder.glob("*.json")):
        try:
            docs.append(MindMapDoc.load(path))
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    return docs, errors


# --------------------------------------------------------------------------
# Text wrapping and layout
# --------------------------------------------------------------------------

def wrap_label(text: str, width: int = MAX_LABEL_CHARS) -> List[str]:
    """Wrap a label into short lines, splitting long unbroken words."""
    lines: List[str] = []
    current = ""
    for word in text.split():
        while len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:width])
            word = word[width:]
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class TreeLayout:
    """Left-to-right tidy tree layout over the visible portion of a mind map."""

    def __init__(self, char_w: float):
        self.char_w = char_w

    def measure(self, node: Node) -> None:
        node.lines = wrap_label(node.name)
        longest = max(len(line) for line in node.lines)
        node.w = longest * self.char_w + 2 * BOX_PAD_X
        node.h = len(node.lines) * LINE_HEIGHT + 2 * BOX_PAD_Y

    def layout(self, root: Node) -> Tuple[float, float]:
        """Assign x/y to every visible node. Returns (width, height) of the tree."""
        for node in root.walk():
            self.measure(node)
        self._assign_x(root, 0.0)
        height = self._assign_y(root, 0.0)
        width = max(n.x + n.w for n in self._visible(root))
        return width, height

    def _visible(self, root: Node):
        yield root
        for child in root.visible_children():
            yield from self._visible(child)

    def _assign_x(self, node: Node, x: float) -> None:
        node.x = x
        for child in node.visible_children():
            self._assign_x(child, x + node.w + H_GAP)

    def _assign_y(self, node: Node, top: float) -> float:
        """Place a subtree starting at `top`; returns the bottom edge."""
        children = node.visible_children()
        if not children:
            node.y = top + node.h / 2
            return top + node.h
        cursor = top
        for i, child in enumerate(children):
            if i:
                cursor += V_GAP
            cursor = self._assign_y(child, cursor)
        first, last = children[0], children[-1]
        node.y = (first.y + last.y) / 2
        # a tall parent box may overflow the span of its children
        return max(cursor, node.y + node.h / 2)


# --------------------------------------------------------------------------
# Canvas view
# --------------------------------------------------------------------------

class MindMapCanvas(ttk.Frame):
    """Scrollable, zoomable canvas that draws a mind map."""

    def __init__(self, master: tk.Misc, on_status=None):
        super().__init__(master)
        self.doc: Optional[MindMapDoc] = None
        self.scale = 1.0
        self.max_depth_shown: Optional[int] = None
        self.search_term = ""
        self.on_status = on_status
        self._items: Dict[int, Node] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, background="#fbfcfd", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self.canvas.bind("<ButtonPress-1>", self._on_click)
        self.canvas.bind("<ButtonPress-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<ButtonPress-3>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B3-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_wheel)

    # -- public API --------------------------------------------------------

    def show(self, doc: MindMapDoc) -> None:
        self.doc = doc
        self.max_depth_shown = None
        for node in doc.root.walk():
            node.collapsed = False
        self.redraw()
        self.canvas.xview_moveto(0.0)
        self.canvas.yview_moveto(0.0)

    def set_zoom(self, scale: float) -> None:
        self.scale = max(0.35, min(2.5, scale))
        self.redraw()

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self.scale * factor)

    def set_search(self, term: str) -> None:
        self.search_term = term.strip().lower()
        self.redraw()

    def expand_all(self) -> None:
        if not self.doc:
            return
        for node in self.doc.root.walk():
            node.collapsed = False
        self.max_depth_shown = None
        self.redraw()

    def collapse_to_depth(self, depth: int) -> None:
        """Collapse every node at or beyond `depth` (root is depth 0)."""
        if not self.doc:
            return
        for node in self.doc.root.walk():
            node.collapsed = node.depth >= depth and bool(node.children)
        self.max_depth_shown = depth
        self.redraw()

    # -- drawing -----------------------------------------------------------

    def redraw(self) -> None:
        self.canvas.delete("all")
        self._items.clear()
        if not self.doc:
            return

        char_w = tkfont.Font(family="Segoe UI", size=self._font_size()).measure("n")
        layout = TreeLayout(char_w=char_w)
        width, height = layout.layout(self.doc.root)

        pad = 30
        self._draw_node(self.doc.root, pad)
        self.canvas.configure(scrollregion=(0, 0, width + 2 * pad, height + 2 * pad))

        if self.on_status:
            visible = sum(1 for _ in self._walk_visible(self.doc.root))
            self.on_status(
                f"{visible} of {self.doc.node_count()} nodes shown   ·   zoom {self.scale:.0%}"
            )

    def _font_size(self) -> int:
        return max(6, int(round(9 * self.scale)))

    def _walk_visible(self, node: Node):
        yield node
        for child in node.visible_children():
            yield from self._walk_visible(child)

    def _draw_node(self, node: Node, pad: float) -> None:
        s = self.scale
        x0, y0 = node.x * s + pad, (node.y - node.h / 2) * s + pad
        x1, y1 = (node.x + node.w) * s + pad, (node.y + node.h / 2) * s + pad

        for child in node.visible_children():
            cx = child.x * s + pad
            cy = child.y * s + pad
            mid = (x1 + cx) / 2
            self.canvas.create_line(
                x1, (node.y * s + pad), mid, (node.y * s + pad), mid, cy, cx, cy,
                fill="#a8b6c4", width=max(1, int(1.4 * s)), smooth=True,
            )

        fill, outline, text_color = self._colors(node)
        box = self.canvas.create_rectangle(
            x0, y0, x1, y1, fill=fill, outline=outline, width=max(1, int(1.2 * s))
        )
        label = self.canvas.create_text(
            (x0 + x1) / 2,
            (y0 + y1) / 2,
            text="\n".join(node.lines),
            fill=text_color,
            font=("Segoe UI", self._font_size(), "bold" if node.depth <= 1 else "normal"),
            justify="center",
            width=(node.w - 2 * BOX_PAD_X) * s + 4,
        )
        self._items[box] = node
        self._items[label] = node

        if node.children:
            marker = "+" if node.collapsed else "−"
            dot = self.canvas.create_oval(
                x1 - 5 * s, (node.y * s + pad) - 6 * s,
                x1 + 7 * s, (node.y * s + pad) + 6 * s,
                fill="#ffffff", outline=outline, width=max(1, int(s)),
            )
            txt = self.canvas.create_text(
                x1 + 1 * s, node.y * s + pad, text=marker,
                font=("Segoe UI", max(5, int(8 * s)), "bold"), fill=outline,
            )
            self._items[dot] = node
            self._items[txt] = node

        for child in node.visible_children():
            self._draw_node(child, pad)

    def _colors(self, node: Node):
        if self.search_term and self.search_term in node.name.lower():
            return HIGHLIGHT
        idx = min(node.depth, len(DEPTH_COLORS) - 1)
        return DEPTH_COLORS[idx]

    # -- interaction -------------------------------------------------------

    def _on_click(self, event) -> None:
        self.canvas.scan_mark(event.x, event.y)
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x - 1, y - 1, x + 1, y + 1)):
            node = self._items.get(item)
            if node is not None:
                if node.children:
                    node.collapsed = not node.collapsed
                    self.redraw()
                return
        # empty space: begin a pan drag
        self.canvas.bind("<B1-Motion>", self._on_drag)

    def _on_drag(self, event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_wheel(self, event) -> None:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_shift_wheel(self, event) -> None:
        self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_ctrl_wheel(self, event) -> None:
        self.zoom_by(1.1 if event.delta > 0 else 1 / 1.1)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class MindMapViewerApp(tk.Tk):
    """Launcher plus canvas: pick a mind map on the left, visualize on the right."""

    def __init__(self, folder: Path):
        super().__init__()
        self.folder = folder
        self.docs: List[MindMapDoc] = []

        self.title("Mind Map Viewer")
        self.geometry("1180x760")
        self.minsize(880, 560)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(14, 10, 14, 8))
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        toolbar.columnconfigure(6, weight=1)

        ttk.Button(toolbar, text="Reload", command=self.refresh).grid(row=0, column=0)
        ttk.Separator(toolbar, orient="vertical").grid(row=0, column=1, sticky="ns", padx=10)

        ttk.Button(toolbar, text="Expand all", command=lambda: self.canvas.expand_all()).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Label(toolbar, text="Collapse to depth:").grid(row=0, column=3)
        self.depth_var = tk.IntVar(value=3)
        self.depth_spin = ttk.Spinbox(
            toolbar, from_=1, to=6, width=4, textvariable=self.depth_var,
            command=self._apply_depth,
        )
        self.depth_spin.grid(row=0, column=4, padx=(6, 6))
        ttk.Button(toolbar, text="Apply", command=self._apply_depth).grid(row=0, column=5)

        search_box = ttk.Frame(toolbar)
        search_box.grid(row=0, column=7, sticky="e", padx=(0, 10))
        ttk.Label(search_box, text="Highlight:").grid(row=0, column=0, padx=(0, 6))
        self.search_var = tk.StringVar()
        entry = ttk.Entry(search_box, textvariable=self.search_var, width=22)
        entry.grid(row=0, column=1)
        entry.bind("<KeyRelease>", lambda _e: self.canvas.set_search(self.search_var.get()))

        zoom_box = ttk.Frame(toolbar)
        zoom_box.grid(row=0, column=8, sticky="e")
        ttk.Button(zoom_box, text="−", width=3, command=lambda: self.canvas.zoom_by(1 / 1.15)).grid(
            row=0, column=0
        )
        ttk.Button(zoom_box, text="100%", width=6, command=lambda: self.canvas.set_zoom(1.0)).grid(
            row=0, column=1, padx=4
        )
        ttk.Button(zoom_box, text="+", width=3, command=lambda: self.canvas.zoom_by(1.15)).grid(
            row=0, column=2
        )

        side = ttk.Frame(self, padding=(14, 0, 8, 8))
        side.grid(row=1, column=0, sticky="nsew")
        side.rowconfigure(1, weight=1)
        side.rowconfigure(3, weight=0)

        ttk.Label(side, text="Mind maps", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.listbox = tk.Listbox(side, width=34, activestyle="dotbox", exportselection=False)
        self.listbox.grid(row=1, column=0, sticky="nsew", pady=(6, 8))
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._select())

        ttk.Label(side, text="Details", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w")
        self.details = tk.Text(side, width=34, height=11, wrap="word", relief="flat", padx=6, pady=6)
        self.details.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.details.configure(state="disabled")
        base = tkfont.nametofont("TkDefaultFont").actual()
        self.details.tag_configure("h", font=(base["family"], 10, "bold"))
        self.details.tag_configure("dim", foreground="#666666")

        self.canvas = MindMapCanvas(self, on_status=self._set_status)
        self.canvas.grid(row=1, column=1, sticky="nsew", padx=(0, 14), pady=(0, 8))

        status = ttk.Frame(self, padding=(14, 0, 14, 10))
        status.grid(row=2, column=0, columnspan=2, sticky="ew")
        status.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(status, text="", foreground="#666666")
        self.status_label.grid(row=0, column=0, sticky="w")
        ttk.Label(
            status,
            text="Click a node to collapse/expand  ·  drag to pan  ·  Ctrl+wheel to zoom",
            foreground="#8a949e",
        ).grid(row=0, column=1, sticky="e")

    # -- data --------------------------------------------------------------

    def refresh(self) -> None:
        self.docs, errors = load_mindmap_dir(self.folder)
        self.listbox.delete(0, "end")
        for doc in self.docs:
            self.listbox.insert("end", doc.title)
        if self.docs:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self._select()
        else:
            self._set_details([(f"No mind maps found in {self.folder}\n", "dim")])
            self._set_status("")
        if errors:
            messagebox.showwarning("Some mind maps failed to load", "\n".join(errors), parent=self)

    def _selected(self) -> Optional[MindMapDoc]:
        sel = self.listbox.curselection()
        return self.docs[sel[0]] if sel else None

    def _select(self) -> None:
        doc = self._selected()
        if doc is None:
            return
        self.canvas.show(doc)
        branches = doc.root.children
        self._set_details([
            (doc.title + "\n\n", "h"),
            (f"Main branches: {len(branches)}\n", "dim"),
            (f"Total nodes: {doc.node_count()}\n", "dim"),
            (f"Depth: {doc.root.max_depth()}\n", "dim"),
            (f"File: {doc.path.name if doc.path else 'n/a'}\n\n", "dim"),
            ("Branches\n", "h"),
            ("".join(f"  • {b.name}\n" for b in branches), None),
        ])

    def _set_details(self, chunks) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        for text, tag in chunks:
            self.details.insert("end", text, tag)
        self.details.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_label.config(text=text)

    def _apply_depth(self) -> None:
        try:
            depth = int(self.depth_var.get())
        except (tk.TclError, ValueError):
            return
        self.canvas.collapse_to_depth(depth)


def main() -> None:
    default_dir = Path(__file__).resolve().parent.parent / "output" / "mindmaps"
    parser = argparse.ArgumentParser(description="Visualize generated mind maps in a GUI")
    parser.add_argument(
        "--mindmap-dir",
        type=Path,
        default=default_dir,
        help=f"Folder containing mind map JSON files (default: {default_dir})",
    )
    args = parser.parse_args()

    if not args.mindmap_dir.is_dir():
        raise SystemExit(f"Mind map folder not found: {args.mindmap_dir}")

    MindMapViewerApp(args.mindmap_dir).mainloop()


if __name__ == "__main__":
    main()
