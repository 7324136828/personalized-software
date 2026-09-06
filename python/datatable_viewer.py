"""GUI application for browsing and viewing generated data tables.

Scans a folder of data table JSON files (the format produced by
``python/ollama_learning/datatable.py`` and defined by ``ollama_learning.schemas.DataTable``)
and displays them in an interactive table viewer with sorting, filtering, and export options.

Standard library only -- tkinter, json, pathlib, argparse.

    python python/datatable_viewer.py
    python python/datatable_viewer.py --table-dir output/datatables
"""

import argparse
import json
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import List, Optional, Dict, Any


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

@dataclass
class StudyField:
    """Field definition, mirroring schemas.StudyField."""
    name: str
    description: str
    example: Optional[str] = None


@dataclass
class DataTable:
    """A loaded data table, mirroring schemas.DataTable plus its source path."""
    title: str
    fields: List[StudyField]
    data: List[Dict[str, str]]
    path: Optional[Path] = None

    @classmethod
    def from_dict(cls, data: dict, path: Optional[Path] = None) -> "DataTable":
        fields = []
        for raw in data.get("fields", []):
            if "name" not in raw or "description" not in raw:
                raise ValueError("field missing required 'name' or 'description'")
            fields.append(StudyField(
                name=raw["name"],
                description=raw["description"],
                example=raw.get("example")
            ))
        
        data_rows = data.get("data", [])
        if not isinstance(data_rows, list):
            raise ValueError("'data' must be a list")
        
        return cls(
            title=data.get("title", "Untitled"),
            fields=fields,
            data=data_rows,
            path=path,
        )

    @classmethod
    def load(cls, path: Path) -> "DataTable":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data, path)

    @property
    def field_names(self) -> List[str]:
        return [f.name for f in self.fields]

    @property
    def row_count(self) -> int:
        return len(self.data)


def load_datatable_dir(table_dir: Path) -> tuple:
    """Load every *.json data table in a folder. Returns (tables, errors)."""
    tables, errors = [], []
    for path in sorted(table_dir.glob("*.json")):
        try:
            tables.append(DataTable.load(path))
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    return tables, errors


# --------------------------------------------------------------------------
# Table viewer
# --------------------------------------------------------------------------

class DataTableWindow(tk.Toplevel):
    """Interactive viewer for a single data table."""

    def __init__(self, master: tk.Misc, table: DataTable):
        super().__init__(master)
        self.table = table
        self.filtered_data: List[Dict[str, str]] = list(table.data)
        self.sort_column: Optional[str] = None
        self.sort_reverse: bool = False

        self.title(f"Data Table: {table.title}")
        self.geometry("1100x700")
        self.minsize(800, 500)

        self._build_ui()
        self._load_data()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Header
        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header, text=self.table.title, font=("Segoe UI", 15, "bold"), wraplength=800
        ).grid(row=0, column=0, sticky="w")
        
        ttk.Label(
            header, text=f"{self.table.row_count} rows · {len(self.table.fields)} fields",
            foreground="#666666"
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        # Toolbar
        toolbar = ttk.Frame(self, padding=(20, 8, 20, 8))
        toolbar.grid(row=1, column=0, sticky="ew")
        toolbar.columnconfigure(3, weight=1)

        ttk.Label(toolbar, text="Filter:").grid(row=0, column=0, padx=(0, 6))
        self.filter_var = tk.StringVar()
        filter_entry = ttk.Entry(toolbar, textvariable=self.filter_var, width=25)
        filter_entry.grid(row=0, column=1, padx=(0, 6))
        filter_entry.bind("<KeyRelease>", lambda _e: self._apply_filter())
        
        ttk.Button(toolbar, text="Clear", command=self._clear_filter).grid(row=0, column=2, padx=(0, 12))

        ttk.Label(toolbar, text="Export:").grid(row=0, column=4, padx=(0, 6))
        ttk.Button(toolbar, text="CSV", command=self._export_csv).grid(row=0, column=5, padx=(0, 4))
        ttk.Button(toolbar, text="JSON", command=self._export_json).grid(row=0, column=6)

        # Treeview
        body = ttk.Frame(self, padding=(20, 8, 20, 8))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(body, selectmode="extended")
        self.tree.grid(row=0, column=0, sticky="nsew")
        
        v_scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        h_scroll = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        # Configure columns
        self.tree["columns"] = self.table.field_names
        for i, field in enumerate(self.table.fields):
            self.tree.heading(i, text=field.name, command=lambda c=field.name: self._sort_by(c))
            self.tree.column(i, width=150, minwidth=100)
        
        # Status bar
        status = ttk.Frame(self, padding=(20, 8, 20, 16))
        status.grid(row=3, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        
        self.status_label = ttk.Label(status, text="", foreground="#666666")
        self.status_label.grid(row=0, column=0, sticky="w")

    def _load_data(self) -> None:
        """Load data into the treeview."""
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Add rows
        for row in self.filtered_data:
            values = [row.get(field.name, "") for field in self.table.fields]
            self.tree.insert("", "end", values=values)
        
        self._update_status()

    def _apply_filter(self) -> None:
        """Apply filter to data."""
        filter_text = self.filter_var.get().lower()
        if not filter_text:
            self.filtered_data = list(self.table.data)
        else:
            self.filtered_data = [
                row for row in self.table.data
                if any(filter_text in str(row.get(f.name, "")).lower() for f in self.table.fields)
            ]
        self._load_data()

    def _clear_filter(self) -> None:
        """Clear the filter."""
        self.filter_var.set("")
        self._apply_filter()

    def _sort_by(self, column: str) -> None:
        """Sort by column."""
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        
        self.filtered_data.sort(
            key=lambda row: str(row.get(column, "")).lower(),
            reverse=self.sort_reverse
        )
        self._load_data()

    def _export_csv(self) -> None:
        """Export to CSV."""
        from tkinter import filedialog
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"{self.table.title}.csv"
        )
        if not filename:
            return
        
        try:
            import csv
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.table.field_names)
                writer.writeheader()
                writer.writerows(self.filtered_data)
            messagebox.showinfo("Export", f"Exported {len(self.filtered_data)} rows to {filename}", parent=self)
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export: {e}", parent=self)

    def _export_json(self) -> None:
        """Export to JSON."""
        from tkinter import filedialog
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=f"{self.table.title}.json"
        )
        if not filename:
            return
        
        try:
            export_data = {
                "title": self.table.title,
                "fields": [
                    {"name": f.name, "description": f.description, "example": f.example}
                    for f in self.table.fields
                ],
                "data": self.filtered_data
            }
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Export", f"Exported {len(self.filtered_data)} rows to {filename}", parent=self)
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export: {e}", parent=self)

    def _update_status(self) -> None:
        """Update status bar."""
        if self.filter_var.get():
            self.status_label.config(text=f"Showing {len(self.filtered_data)} of {self.table.row_count} rows (filtered)")
        else:
            self.status_label.config(text=f"Showing {len(self.filtered_data)} rows")


# --------------------------------------------------------------------------
# Launcher
# --------------------------------------------------------------------------

class LauncherApp(tk.Tk):
    """Main window: pick a data table from a folder and view it."""

    def __init__(self, table_dir: Path):
        super().__init__()
        self.table_dir = table_dir
        self.tables: List[DataTable] = []

        self.title("Data Table Launcher")
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
        ttk.Label(head, text="Data Table Launcher", font=("Segoe UI", 16, "bold")).grid(
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

        list_frame = ttk.LabelFrame(body, text="Available tables", padding=8)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame, activestyle="dotbox", exportselection=False)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=list_scroll.set)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._show_details())
        self.listbox.bind("<Double-Button-1>", lambda _e: self.open_table())

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

        self.open_button = ttk.Button(footer, text="Open table", command=self.open_table, state="disabled")
        self.open_button.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(footer, text="Quit", command=self.quit).grid(row=0, column=1)

    def refresh(self) -> None:
        self.tables, errors = load_datatable_dir(self.table_dir)
        self.listbox.delete(0, "end")
        for table in self.tables:
            self.listbox.insert("end", table.title)
        self.dir_label.config(text=str(self.table_dir))
        
        if self.tables:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self._show_details()
        else:
            self._set_details([(f"No data tables found in {self.table_dir}\n", "dim")])
        
        if errors:
            messagebox.showwarning("Some tables failed to load", "\n".join(errors), parent=self)

    def _selected(self) -> Optional[DataTable]:
        sel = self.listbox.curselection()
        return self.tables[sel[0]] if sel else None

    def _show_details(self) -> None:
        table = self._selected()
        if table is None:
            self.open_button.config(state="disabled")
            return
        
        self.open_button.config(state="normal")
        self._set_details([
            (table.title + "\n\n", "h"),
            (f"Rows: {table.row_count}\n", "dim"),
            (f"Fields: {len(table.fields)}\n", "dim"),
            (f"File: {table.path.name if table.path else 'n/a'}\n\n", "dim"),
            ("Fields\n", "h"),
            ("".join(f"  • {f.name}: {f.description}\n" for f in table.fields), None),
        ])

    def _set_details(self, chunks) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        for text, tag in chunks:
            self.details.insert("end", text, tag)
        self.details.configure(state="disabled")

    def open_table(self) -> None:
        table = self._selected()
        if table:
            DataTableWindow(self, table)


def main() -> None:
    default_dir = Path(__file__).resolve().parent.parent / "output" / "datatable"
    parser = argparse.ArgumentParser(description="Browse generated data tables in a GUI")
    parser.add_argument(
        "--table-dir",
        type=Path,
        default=default_dir,
        help="Folder containing data table JSON files (default: output/datatable)",
    )
    args = parser.parse_args()

    if not args.table_dir.exists():
        print(f"Creating directory: {args.table_dir}")
        args.table_dir.mkdir(parents=True, exist_ok=True)

    app = LauncherApp(args.table_dir)
    app.mainloop()


if __name__ == "__main__":
    main()