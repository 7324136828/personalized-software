/**
 * Port of python/datatable_launcher.py, merged with python/datatable_viewer.py.
 *
 * Those two scripts covered the same content type; this view takes the union:
 * header sorting, text filtering, and the full-record pane from the first, plus
 * the JSON export alongside CSV from the second.
 */

import { useEffect, useMemo, useState } from "react";
import { LibraryShell, DetailRow } from "../components/LibraryShell";
import { req, ValidationError } from "../lib/content";
import { download, sortRows, toCsv } from "../lib/format";
import { useLibrary } from "../lib/useLibrary";
import type { DataTable } from "../types";

function parseTable(raw: Record<string, unknown>, where: string): DataTable {
  const fields = req<Record<string, unknown>[]>(raw, "fields", "array", where);
  const rows = req<Record<string, unknown>[]>(raw, "data", "array", where);
  if (rows.length === 0) throw new ValidationError(`${where}: table has no rows`);

  const parsedFields = fields.map((f, i) => ({
    name: req<string>(f, "name", "string", `${where} field ${i + 1}`),
    description: (f.description as string) ?? "",
    example: (f.example as string | null) ?? null,
  }));

  const parsedRows = rows.map((row, i) => {
    if (typeof row !== "object" || Array.isArray(row)) {
      throw new ValidationError(`${where} row ${i + 1}: expected an object`);
    }
    return Object.fromEntries(
      Object.entries(row).map(([k, v]) => [k, v === null || v === undefined ? "" : String(v)]),
    );
  });

  const missing = parsedFields
    .map((f) => f.name)
    .filter((name) => parsedRows.some((row) => !(name in row)));
  if (missing.length > 0) {
    throw new ValidationError(
      `${where}: rows are missing declared field(s) ${missing.join(", ")}`,
    );
  }

  return { title: req<string>(raw, "title", "string", where), fields: parsedFields, data: parsedRows };
}

/** Declared fields first, then extras the rows carry (source_id, page). */
function columnsOf(table: DataTable): string[] {
  const names = table.fields.map((f) => f.name);
  for (const row of table.data) {
    for (const key of Object.keys(row)) {
      if (!names.includes(key)) names.push(key);
    }
  }
  return names;
}

export function DatatableView() {
  const lib = useLibrary<DataTable>("datatables", parseTable);
  const [filter, setFilter] = useState("");
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [reverse, setReverse] = useState(false);
  const [rowIndex, setRowIndex] = useState(0);

  const table = lib.selected?.doc ?? null;
  const columns = useMemo(() => (table ? columnsOf(table) : []), [table]);

  useEffect(() => {
    setFilter("");
    setSortColumn(null);
    setReverse(false);
    setRowIndex(0);
  }, [lib.selectedIndex, lib.documents.length]);

  const visible = useMemo(() => {
    if (!table) return [];
    const term = filter.trim().toLowerCase();
    let rows = table.data.filter(
      (row) => !term || Object.values(row).some((v) => v.toLowerCase().includes(term)),
    );
    if (sortColumn) rows = sortRows(rows, sortColumn, reverse);
    return rows;
  }, [table, filter, sortColumn, reverse]);

  useEffect(() => {
    setRowIndex(0);
  }, [filter, sortColumn, reverse]);

  const sortBy = (column: string) => {
    if (sortColumn === column) setReverse(!reverse);
    else {
      setSortColumn(column);
      setReverse(false);
    }
  };

  const describeField = (name: string) =>
    table?.fields.find((f) => f.name === name)?.description ?? "";

  const record = visible[rowIndex] ?? null;
  const stem = lib.selected?.entry.stem ?? "table";

  const details = table ? (
    <>
      <p className="details-title">{table.title}</p>
      <DetailRow label="Rows" value={table.data.length} />
      <DetailRow label="Columns" value={columns.length} />
      <DetailRow label="Declared fields" value={table.fields.length} />
      <DetailRow label="File" value={lib.selected?.entry.file ?? "n/a"} />
      <p className="details-subheading">Fields</p>
      <ul className="bullets">
        {table.fields.map((field) => (
          <li key={field.name}>
            <code>{field.name}</code>
            {field.description && <div className="muted small">{field.description}</div>}
          </li>
        ))}
      </ul>
    </>
  ) : null;

  const toolbar = (
    <>
      <button type="button" onClick={lib.reload}>
        Reload
      </button>
      <span className="divider" />
      <label className="field">
        Filter
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="match any column"
        />
      </label>
      <button type="button" onClick={() => setFilter("")} disabled={!filter}>
        Clear
      </button>
      <span className="spacer" />
      <span className="muted small">Export visible rows:</span>
      <button
        type="button"
        disabled={visible.length === 0}
        onClick={() => download(`${stem}_filtered.csv`, toCsv(columns, visible), "text/csv")}
      >
        CSV
      </button>
      <button
        type="button"
        disabled={visible.length === 0}
        onClick={() =>
          download(
            `${stem}_filtered.json`,
            JSON.stringify({ title: table?.title, fields: table?.fields, data: visible }, null, 2),
            "application/json",
          )
        }
      >
        JSON
      </button>
    </>
  );

  return (
    <LibraryShell
      documents={lib.documents}
      errors={lib.errors}
      loading={lib.loading}
      selectedIndex={lib.selectedIndex}
      onSelect={lib.select}
      titleOf={(t) => t.title}
      details={details}
      toolbar={toolbar}
      status={
        table
          ? `${visible.length} of ${table.data.length} rows · ${columns.length} columns` +
            (sortColumn ? ` · sorted by ${sortColumn} ${reverse ? "descending" : "ascending"}` : "")
          : ""
      }
      hint="Click a header to sort · select a row to see the full record"
      emptyMessage="No data tables found in output/datatables."
    >
      {table ? (
        <div className="table-pane">
          <div className="grid-scroll">
            <table className="grid">
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th key={column}>
                      <button type="button" onClick={() => sortBy(column)}>
                        {column}
                        {sortColumn === column && <span>{reverse ? " ▼" : " ▲"}</span>}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((row, i) => (
                  <tr
                    key={i}
                    className={i === rowIndex ? "selected" : undefined}
                    onClick={() => setRowIndex(i)}
                  >
                    {columns.map((column) => (
                      <td key={column} title={row[column]}>
                        {row[column]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {visible.length === 0 && (
              <p className="muted pad">No rows match the current filter.</p>
            )}
          </div>

          <div className="record">
            <h3>Record</h3>
            {record ? (
              <dl>
                {columns.map((column) => (
                  <div key={column}>
                    <dt>{column}</dt>
                    {describeField(column) && (
                      <dd className="muted small">{describeField(column)}</dd>
                    )}
                    <dd>{record[column]}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="muted">No row selected.</p>
            )}
          </div>
        </div>
      ) : (
        <div className="placeholder">Select a data table.</div>
      )}
    </LibraryShell>
  );
}
