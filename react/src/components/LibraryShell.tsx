/**
 * React port of launcher_common.LibraryApp.
 *
 * Supplies the frame every viewer shares: a document list on the left, a
 * details pane beneath it, a toolbar, a content area, and a status bar. Views
 * pass the pieces in rather than subclassing.
 */

import type { ReactNode } from "react";
import type { Loaded } from "../lib/content";

export interface LibraryShellProps<T> {
  documents: Loaded<T>[];
  errors: string[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  titleOf: (doc: T) => string;
  details: ReactNode;
  toolbar?: ReactNode;
  children: ReactNode;
  status?: ReactNode;
  hint?: string;
  loading?: boolean;
  emptyMessage?: string;
}

export function LibraryShell<T>({
  documents,
  errors,
  selectedIndex,
  onSelect,
  titleOf,
  details,
  toolbar,
  children,
  status,
  hint,
  loading = false,
  emptyMessage = "No documents found.",
}: LibraryShellProps<T>) {
  if (loading) {
    return <div className="placeholder">Loading…</div>;
  }

  return (
    <div className="shell">
      {toolbar ? <div className="toolbar">{toolbar}</div> : null}

      <div className="shell-body">
        <aside className="sidebar">
          <h2 className="sidebar-heading">Library</h2>
          {documents.length === 0 ? (
            <p className="muted small">{emptyMessage}</p>
          ) : (
            <ul className="doc-list" role="listbox" aria-label="Documents">
              {documents.map((item, index) => (
                <li key={item.entry.file}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === selectedIndex}
                    className={index === selectedIndex ? "doc active" : "doc"}
                    onClick={() => onSelect(index)}
                  >
                    {titleOf(item.doc)}
                  </button>
                </li>
              ))}
            </ul>
          )}

          <h2 className="sidebar-heading">Details</h2>
          <div className="details">{details}</div>

          {errors.length > 0 && (
            <div className="errors" role="alert">
              <strong>Some documents failed to load</strong>
              <ul>
                {errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </div>
          )}
        </aside>

        <main className="content">{children}</main>
      </div>

      <div className="statusbar">
        <span>{status}</span>
        <span className="hint">{hint}</span>
      </div>
    </div>
  );
}

/** Small labelled block used throughout the details panes. */
export function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="detail-row">
      <span className="detail-label">{label}</span>
      <span className="detail-value">{value}</span>
    </div>
  );
}
