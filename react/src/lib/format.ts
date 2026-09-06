/**
 * Shared formatting helpers ported from the Python launchers.
 */

/** Port of infographic.parse_chart_item: "Label: 42%" -> [label, 42, "%"]. */
const CHART_ITEM = /^(.+?)\s*[:|—-]\s*([\d.]+)\s*(%|[A-Za-z]*)$/;

export interface ChartItem {
  label: string;
  value: number | null;
  unit: string;
}

export function parseChartItem(item: string): ChartItem {
  const match = CHART_ITEM.exec(item.trim());
  if (!match) return { label: item.trim(), value: null, unit: "" };
  const value = Number.parseFloat(match[2]);
  if (Number.isNaN(value)) return { label: item.trim(), value: null, unit: "" };
  return { label: match[1].trim(), value, unit: match[3] };
}

/** Port of reports._format_citation: omit page and chunk parts that are unset. */
export function formatCitation(citation: {
  source_id: string;
  page: number | null;
  chunk_id: string | null;
}): string {
  const parts = [citation.source_id];
  if (citation.page !== null && citation.page !== undefined) {
    parts.push(`p.${citation.page}`);
  }
  if (citation.chunk_id) parts.push(citation.chunk_id);
  return parts.join(":");
}

/**
 * Port of datatable_launcher._sorted: numeric ordering when every value in the
 * column parses as a number, case-insensitive text ordering otherwise.
 */
export function sortRows<T extends Record<string, string>>(
  rows: T[],
  column: string,
  reverse: boolean,
): T[] {
  const numeric = rows.every((row) => {
    const raw = (row[column] ?? "").replace(/,/g, "");
    return raw.trim() !== "" && !Number.isNaN(Number(raw));
  });
  const sorted = [...rows].sort((a, b) => {
    if (numeric) {
      return (
        Number((a[column] ?? "").replace(/,/g, "")) -
        Number((b[column] ?? "").replace(/,/g, ""))
      );
    }
    return (a[column] ?? "")
      .toLowerCase()
      .localeCompare((b[column] ?? "").toLowerCase());
  });
  return reverse ? sorted.reverse() : sorted;
}

/** Port of datatable_launcher.write_csv: UTF-8, minimal quoting. */
export function toCsv(
  columns: string[],
  rows: Record<string, string>[],
): string {
  const cell = (value: string) =>
    /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
  const lines = [columns.map(cell).join(",")];
  for (const row of rows) {
    lines.push(columns.map((c) => cell(row[c] ?? "")).join(","));
  }
  return lines.join("\n") + "\n";
}

export function download(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Fisher-Yates, matching random.shuffle's role in the Python launchers. */
export function shuffle<T>(items: T[]): T[] {
  const result = [...items];
  for (let i = result.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}

/**
 * Port of infographic.group_panels: group sections by panel name, preserving
 * first-seen order and keeping non-adjacent sections of the same panel together.
 */
export function groupPanels<T extends { panel: string | null }>(
  sections: T[],
): { name: string | null; sections: T[] }[] {
  const order: (string | null)[] = [];
  const buckets = new Map<string | null, T[]>();
  for (const section of sections) {
    const key = section.panel || null;
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(section);
  }
  return order.map((name) => ({ name, sections: buckets.get(name)! }));
}

/** Port of infographic.sanitize_svg — strip scripts, handlers, external refs. */
export function sanitizeSvg(markup: string): string {
  let cleaned = markup
    .replace(/<script\b[\s\S]*?<\/script\s*>/gi, "")
    .replace(/<foreignObject\b[\s\S]*?<\/foreignObject\s*>/gi, "")
    .replace(/\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, "")
    .replace(/\s(?:xlink:)?href\s*=\s*("|')\s*(?!#)[a-z]+:[^"']*\1/gi, "");
  const start = cleaned.toLowerCase().indexOf("<svg");
  if (start !== -1) cleaned = cleaned.slice(start);
  return cleaned.trim();
}

export function percent(value: number, total: number): number {
  return total > 0 ? (value / total) * 100 : 0;
}
