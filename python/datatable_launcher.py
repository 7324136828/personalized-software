"""Sample GUI application for browsing generated data tables.

Scans a folder of data table JSON files (the format produced by
``python/ollama_learning/datatable.py`` and defined by
``ollama_learning.schemas.DataTable``) and shows the selected table as a sortable
grid with a full-record pane beneath it, text filtering, and CSV export of
whatever is currently visible.

Standard library only -- no pandas required to read or export.

    python python/datatable_launcher.py
    python python/datatable_launcher.py --table-dir output/datatables
"""

import argparse
import csv
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Sequence

from launcher_common import Chunk, LibraryApp, RichText, read_json, require

MAX_COL_WIDTH = 240
MIN_COL_WIDTH = 70
CHAR_PX = 7


@dataclass
class Field:
    """A column definition, mirroring schemas.StudyField."""

    name: str
    description: str = ""
    example: Optional[str] = None


@dataclass
class Table:
    """A data table, mirroring schemas.DataTable."""

    title: str
    fields: List[Field]
    rows: List[Dict[str, str]] = field(default_factory=list)
    path: Optional[Path] = None

    @classmethod
    def load(cls, path: Path) -> "Table":
        data = read_json(path)
        where = path.name
        raw_fields = require(data, "fields", list, where)
        raw_rows = require(data, "data", list, where)
        if not raw_rows:
            raise ValueError(f"{where}: table has no rows")

        fields = [
            Field(
                name=require(f, "name", str, f"{where} field {i + 1}"),
                description=f.get("description", ""),
                example=f.get("example"),
            )
            for i, f in enumerate(raw_fields)
        ]
        rows = []
        for i, row in enumerate(raw_rows):
            if not isinstance(row, dict):
                raise ValueError(f"{where} row {i + 1}: expected an object")
            rows.append({k: "" if v is None else str(v) for k, v in row.items()})

        missing = [f.name for f in fields if any(f.name not in r for r in rows)]
        if missing:
            raise ValueError(f"{where}: rows are missing declared field(s) {', '.join(missing)}")

        return cls(title=require(data, "title", str, where), fields=fields, rows=rows, path=path)

    def columns(self) -> List[str]:
        """Declared fields first, then any extras the rows carry (source_id, page)."""
        names = [f.name for f in self.fields]
        for row in self.rows:
            for key in row:
                if key not in names:
                    names.append(key)
        return names

    def describe_field(self, name: str) -> str:
        for f in self.fields:
            if f.name == name:
                return f.description
        return ""


class DataTableApp(LibraryApp):
    """Grid browser for a folder of data tables."""

    window_title = "Data Table Browser"
    window_size = "1260x780"

    def __init__(self, folder: Path):
        self.visible: List[Dict[str, str]] = []
        self.sort_column: Optional[str] = None
        self.sort_reverse = False
        super().__init__(folder)
        self.set_hint("click a header to sort · select a row to see the full record")

    # -- library hooks -----------------------------------------------------

    def load_one(self, path: Path) -> Table:
        return Table.load(path)

    def title_of(self, doc: Table) -> str:
        return doc.title

    def describe(self, doc: Table) -> Sequence[Chunk]:
        chunks: List[Chunk] = [
            (doc.title + "\n\n", "h2"),
            (f"Rows: {len(doc.rows)}\n", "dim"),
            (f"Columns: {len(doc.columns())}\n", "dim"),
            (f"Declared fields: {len(doc.fields)}\n", "dim"),
            (f"File: {doc.path.name if doc.path else 'n/a'}\n\n", "dim"),
            ("Fields\n", "h3"),
        ]
        for f in doc.fields:
            chunks.append((f"  {f.name}\n", None))
            if f.description:
                chunks.append((f"    {f.description}\n", "dim"))
        return chunks

    def build_toolbar(self, toolbar: ttk.Frame) -> None:
        toolbar.columnconfigure(4, weight=1)

        search = ttk.Frame(toolbar)
        search.grid(row=0, column=2, sticky="w")
        ttk.Label(search, text="Filter:").grid(row=0, column=0, padx=(0, 6))
        self.filter_var = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.filter_var, width=28)
        entry.grid(row=0, column=1)
        entry.bind("<KeyRelease>", lambda _e: self._apply_filter())
        ttk.Button(search, text="Clear", width=6,
                   command=lambda: (self.filter_var.set(""), self._apply_filter())).grid(
            row=0, column=2, padx=(6, 0)
        )

        ttk.Button(toolbar, text="Export visible rows to CSV…", command=self.export_csv).grid(
            row=0, column=5, sticky="e"
        )

    def build_content(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(0, weight=3)
        parent.rowconfigure(1, weight=2)

        grid_frame = ttk.Frame(parent)
        grid_frame.grid(row=0, column=0, sticky="nsew")
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(grid_frame, show="headings", selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vbar = ttk.Scrollbar(grid_frame, orient="vertical", command=self.tree.yview)
        hbar = ttk.Scrollbar(grid_frame, orient="horizontal", command=self.tree.xview)
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.tree.tag_configure("odd", background="#f5f8fa")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_record())

        record = ttk.LabelFrame(parent, text="Record", padding=8)
        record.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        record.columnconfigure(0, weight=1)
        record.rowconfigure(0, weight=1)
        self.record = RichText(record, height=10)
        self.record.grid(row=0, column=0, sticky="nsew")
        rbar = ttk.Scrollbar(record, orient="vertical", command=self.record.yview)
        rbar.grid(row=0, column=1, sticky="ns")
        self.record.configure(yscrollcommand=rbar.set)

    def show(self, doc: Table) -> None:
        self.sort_column = None
        self.sort_reverse = False
        self.filter_var.set("")
        self._configure_columns(doc)
        self._apply_filter()

    # -- grid --------------------------------------------------------------

    def _configure_columns(self, doc: Table) -> None:
        columns = doc.columns()
        self.tree.configure(columns=columns)
        for name in columns:
            self.tree.heading(name, text=name, command=lambda c=name: self._sort_by(c))
            longest = max([len(name)] + [len(row.get(name, "")) for row in doc.rows])
            width = min(MAX_COL_WIDTH, max(MIN_COL_WIDTH, longest * CHAR_PX))
            self.tree.column(name, width=width, minwidth=MIN_COL_WIDTH, stretch=False, anchor="w")

    def _apply_filter(self) -> None:
        doc = self.selected()
        if doc is None:
            return
        term = self.filter_var.get().strip().lower()
        rows = [r for r in doc.rows if not term or any(term in v.lower() for v in r.values())]
        if self.sort_column:
            rows = self._sorted(rows, self.sort_column, self.sort_reverse)
        self.visible = rows
        self._fill(doc, rows)

    def _fill(self, doc: Table, rows: List[Dict[str, str]]) -> None:
        self.tree.delete(*self.tree.get_children())
        columns = doc.columns()
        for i, row in enumerate(rows):
            values = [row.get(c, "") for c in columns]
            self.tree.insert("", "end", iid=str(i), values=values, tags=("odd",) if i % 2 else ())
        self.set_status(
            f"{len(rows)} of {len(doc.rows)} rows   ·   {len(columns)} columns"
            + (f"   ·   sorted by {self.sort_column}"
               f" {'descending' if self.sort_reverse else 'ascending'}" if self.sort_column else "")
        )
        if rows:
            self.tree.selection_set("0")
            self.tree.focus("0")
        else:
            self.record.set_chunks([("No rows match the current filter.\n", "dim")])

    @staticmethod
    def _sorted(rows, column: str, reverse: bool) -> List[Dict[str, str]]:
        values = [r.get(column, "") for r in rows]

        def numeric(v: str):
            return float(v.replace(",", ""))

        try:
            for v in values:
                numeric(v)
            key = lambda r: numeric(r.get(column, ""))  # noqa: E731
        except ValueError:
            key = lambda r: r.get(column, "").lower()  # noqa: E731
        return sorted(rows, key=key, reverse=reverse)

    def _sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self._apply_filter()

    def _show_record(self) -> None:
        doc = self.selected()
        selection = self.tree.selection()
        if doc is None or not selection:
            return
        row = self.visible[int(selection[0])]
        chunks: List[Chunk] = []
        for name in doc.columns():
            chunks.append((f"{name}\n", "h3"))
            description = doc.describe_field(name)
            if description:
                chunks.append((f"  {description}\n", "dim"))
            chunks.append((f"  {row.get(name, '')}\n\n", "body"))
        self.record.set_chunks(chunks)

    # -- export ------------------------------------------------------------

    def export_csv(self) -> None:
        doc = self.selected()
        if doc is None or not self.visible:
            messagebox.showinfo("Nothing to export", "No rows are currently visible.", parent=self)
            return
        default = f"{doc.path.stem}_filtered.csv" if doc.path else "table.csv"
        target = filedialog.asksaveasfilename(
            parent=self, title="Export visible rows",
            defaultextension=".csv", initialfile=default,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not target:
            return
        self.write_csv(Path(target), doc.columns(), self.visible)
        self.set_status(f"Exported {len(self.visible)} rows to {Path(target).name}")

    @staticmethod
    def write_csv(target: Path, columns: List[str], rows: List[Dict[str, str]]) -> None:
        """Write rows as UTF-8 CSV — the stdlib equivalent of DataTableExtractor._save_csv."""
        with target.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows([{c: row.get(c, "") for c in columns} for row in rows])


def main() -> None:
    default_dir = Path(__file__).resolve().parent.parent / "output" / "datatables"
    parser = argparse.ArgumentParser(description="Browse generated data tables in a GUI")
    parser.add_argument("--table-dir", type=Path, default=default_dir,
                        help=f"Folder containing data table JSON files (default: {default_dir})")
    args = parser.parse_args()

    if not args.table_dir.is_dir():
        raise SystemExit(f"Data table folder not found: {args.table_dir}")

    DataTableApp(args.table_dir).mainloop()


if __name__ == "__main__":
    main()
