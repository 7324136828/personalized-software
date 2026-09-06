/**
 * Loading and validation helpers.
 *
 * Ports `launcher_common.load_documents` / `require` and the per-launcher
 * validation that lived in each script's dataclass `from_dict`. A malformed
 * document is collected as an error rather than taking the whole view down,
 * matching the tkinter behaviour.
 */

import type { Kind, Manifest, ManifestEntry } from "../types";

export class ValidationError extends Error {}

/** Port of launcher_common.require: fetch a field or fail with a readable message. */
export function req<T>(
  data: Record<string, unknown>,
  field: string,
  kind: "string" | "number" | "array" | "object",
  where: string,
): T {
  if (!(field in data) || data[field] === undefined || data[field] === null) {
    throw new ValidationError(`${where}: missing required field '${field}'`);
  }
  const value = data[field];
  const ok =
    kind === "array"
      ? Array.isArray(value)
      : kind === "object"
        ? typeof value === "object" && !Array.isArray(value)
        : typeof value === kind;
  if (!ok) {
    throw new ValidationError(`${where}: field '${field}' must be ${kind}`);
  }
  return value as T;
}

export interface Loaded<T> {
  entry: ManifestEntry;
  doc: T;
}

export interface LoadResult<T> {
  documents: Loaded<T>[];
  errors: string[];
}

export function dataUrl(kind: Kind, file: string): string {
  const encoded = file.split("/").map(encodeURIComponent).join("/");
  return `${import.meta.env.BASE_URL}api/content/${kind}/${encoded}`;
}

export async function fetchManifest(): Promise<Manifest> {
  const response = await fetch(`${import.meta.env.BASE_URL}api/content/manifest`);
  if (!response.ok) {
    throw new Error(
      `Could not load the content manifest (${response.status}). ` +
        `Make sure the Python backend is running.`,
    );
  }
  return (await response.json()) as Manifest;
}

/**
 * Port of launcher_common.load_documents: load every document of a kind,
 * returning what parsed plus a list of per-file errors.
 */
export async function loadKind<T>(
  kind: Kind,
  manifest: Manifest,
  parse: (raw: Record<string, unknown>, where: string) => T,
): Promise<LoadResult<T>> {
  const entries = manifest.kinds[kind] ?? [];
  const documents: Loaded<T>[] = [];
  const errors: string[] = [];

  await Promise.all(
    entries.map(async (entry) => {
      try {
        const response = await fetch(dataUrl(kind, entry.file));
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const raw = (await response.json()) as Record<string, unknown>;
        documents.push({ entry, doc: parse(raw, entry.file) });
      } catch (error) {
        errors.push(`${entry.file}: ${(error as Error).message}`);
      }
    }),
  );

  // Promise.all resolves out of order; restore the manifest's sorted order.
  documents.sort(
    (a, b) =>
      entries.indexOf(a.entry) - entries.indexOf(b.entry),
  );
  return { documents, errors };
}
