/**
 * Port of python/mindmap_viewer.py.
 *
 * The tkinter version laid the tree out on a Canvas; this one runs the same
 * tidy-tree algorithm and emits SVG, which gives real pan/zoom for free.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LibraryShell, DetailRow } from "../components/LibraryShell";
import { req, ValidationError } from "../lib/content";
import { useLibrary } from "../lib/useLibrary";
import type { MindMap, MindMapNode } from "../types";

const H_GAP = 46;
const V_GAP = 12;
const BOX_PAD_X = 10;
const BOX_PAD_Y = 6;
const LINE_HEIGHT = 15;
const CHAR_W = 6.6;
const MAX_LABEL_CHARS = 34;

const DEPTH_COLORS = [
  { fill: "#1f3a5f", stroke: "#16293f", text: "#ffffff" },
  { fill: "#2f6f9f", stroke: "#1f4a6b", text: "#ffffff" },
  { fill: "#dce9f5", stroke: "#9ab8d4", text: "#16293f" },
  { fill: "#f2f5f8", stroke: "#c3d0dc", text: "#33414d" },
];
const HIGHLIGHT = { fill: "#ffe9a8", stroke: "#d9a300", text: "#4a3800" };

function parseMindMap(raw: Record<string, unknown>, where: string): MindMap {
  const walk = (data: Record<string, unknown>, at: string): MindMapNode => {
    const name = req<string>(data, "name", "string", at);
    const children = data.children ?? [];
    if (!Array.isArray(children)) {
      throw new ValidationError(`${at}: 'children' must be a list`);
    }
    return {
      name,
      children: children.map((c) => walk(c as Record<string, unknown>, `node '${name}'`)),
    };
  };
  return walk(raw, where);
}

/** Port of mindmap_viewer.wrap_label. */
function wrapLabel(text: string, width = MAX_LABEL_CHARS): string[] {
  const lines: string[] = [];
  let current = "";
  for (let word of text.split(/\s+/).filter(Boolean)) {
    while (word.length > width) {
      if (current) {
        lines.push(current);
        current = "";
      }
      lines.push(word.slice(0, width));
      word = word.slice(width);
    }
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= width) current = candidate;
    else {
      if (current) lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  return lines.length ? lines : [""];
}

interface Laid {
  node: MindMapNode;
  id: string;
  depth: number;
  lines: string[];
  x: number;
  y: number;
  w: number;
  h: number;
  children: Laid[];
  hasChildren: boolean;
  collapsed: boolean;
}

/** Port of mindmap_viewer.TreeLayout. */
function layout(root: MindMapNode, collapsed: Set<string>): { nodes: Laid[]; w: number; h: number } {
  const build = (node: MindMapNode, depth: number, id: string): Laid => {
    const lines = wrapLabel(node.name);
    const longest = Math.max(...lines.map((l) => l.length));
    const isCollapsed = collapsed.has(id);
    return {
      node,
      id,
      depth,
      lines,
      x: 0,
      y: 0,
      w: longest * CHAR_W + 2 * BOX_PAD_X,
      h: lines.length * LINE_HEIGHT + 2 * BOX_PAD_Y,
      children: isCollapsed
        ? []
        : node.children.map((child, i) => build(child, depth + 1, `${id}.${i}`)),
      hasChildren: node.children.length > 0,
      collapsed: isCollapsed,
    };
  };

  const tree = build(root, 0, "0");

  const assignX = (n: Laid, x: number): void => {
    n.x = x;
    n.children.forEach((c) => assignX(c, x + n.w + H_GAP));
  };
  const assignY = (n: Laid, top: number): number => {
    if (n.children.length === 0) {
      n.y = top + n.h / 2;
      return top + n.h;
    }
    let cursor = top;
    n.children.forEach((child, i) => {
      if (i) cursor += V_GAP;
      cursor = assignY(child, cursor);
    });
    n.y = (n.children[0].y + n.children[n.children.length - 1].y) / 2;
    return Math.max(cursor, n.y + n.h / 2);
  };

  assignX(tree, 0);
  const height = assignY(tree, 0);

  const flat: Laid[] = [];
  const collect = (n: Laid) => {
    flat.push(n);
    n.children.forEach(collect);
  };
  collect(tree);
  return { nodes: flat, w: Math.max(...flat.map((n) => n.x + n.w)), h: height };
}

function countNodes(node: MindMapNode): number {
  return 1 + node.children.reduce((total, child) => total + countNodes(child), 0);
}

function maxDepth(node: MindMapNode, depth = 0): number {
  return node.children.length === 0
    ? depth
    : Math.max(...node.children.map((c) => maxDepth(c, depth + 1)));
}

export function MindmapView() {
  const lib = useLibrary<MindMap>("mindmaps", parseMindMap);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [scale, setScale] = useState(1);
  const [search, setSearch] = useState("");
  const [depthLimit, setDepthLimit] = useState(3);
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);

  const map = lib.selected?.doc ?? null;

  useEffect(() => {
    setCollapsed(new Set());
    setScale(1);
    if (viewport.current) viewport.current.scrollTo({ top: 0, left: 0 });
  }, [lib.selectedIndex, lib.documents.length]);

  const { nodes, w, h } = useMemo(
    () => (map ? layout(map, collapsed) : { nodes: [], w: 0, h: 0 }),
    [map, collapsed],
  );

  const toggle = (id: string, hasChildren: boolean) => {
    if (!hasChildren) return;
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  /** Port of collapse_to_depth: collapse every node at or beyond `depth`. */
  const collapseToDepth = useCallback(
    (depth: number) => {
      if (!map) return;
      const ids = new Set<string>();
      const walk = (node: MindMapNode, d: number, id: string) => {
        if (d >= depth && node.children.length > 0) ids.add(id);
        node.children.forEach((child, i) => walk(child, d + 1, `${id}.${i}`));
      };
      walk(map, 0, "0");
      setCollapsed(ids);
    },
    [map],
  );

  const onMouseDown = (event: React.MouseEvent) => {
    if (!viewport.current) return;
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      left: viewport.current.scrollLeft,
      top: viewport.current.scrollTop,
    };
  };
  const onMouseMove = (event: React.MouseEvent) => {
    if (!drag.current || !viewport.current) return;
    viewport.current.scrollLeft = drag.current.left - (event.clientX - drag.current.x);
    viewport.current.scrollTop = drag.current.top - (event.clientY - drag.current.y);
  };
  const endDrag = () => {
    drag.current = null;
  };

  const onWheel = (event: React.WheelEvent) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    setScale((s) => Math.min(2.5, Math.max(0.35, s * (event.deltaY < 0 ? 1.1 : 1 / 1.1))));
  };

  const term = search.trim().toLowerCase();
  const pad = 30;

  const details = map ? (
    <>
      <p className="details-title">{map.name}</p>
      <DetailRow label="Main branches" value={map.children.length} />
      <DetailRow label="Total nodes" value={countNodes(map)} />
      <DetailRow label="Depth" value={maxDepth(map)} />
      <DetailRow label="File" value={lib.selected?.entry.file ?? "n/a"} />
      <p className="details-subheading">Branches</p>
      <ul className="bullets">
        {map.children.map((child) => (
          <li key={child.name}>{child.name}</li>
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
      <button type="button" onClick={() => setCollapsed(new Set())}>
        Expand all
      </button>
      <label className="field">
        Collapse to depth
        <input
          type="number"
          min={1}
          max={6}
          value={depthLimit}
          onChange={(e) => setDepthLimit(Number(e.target.value))}
        />
      </label>
      <button type="button" onClick={() => collapseToDepth(depthLimit)}>
        Apply
      </button>
      <span className="spacer" />
      <label className="field">
        Highlight
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="term" />
      </label>
      <div className="zoom">
        <button type="button" onClick={() => setScale((s) => Math.max(0.35, s / 1.15))}>
          −
        </button>
        <button type="button" onClick={() => setScale(1)}>
          100%
        </button>
        <button type="button" onClick={() => setScale((s) => Math.min(2.5, s * 1.15))}>
          +
        </button>
      </div>
    </>
  );

  return (
    <LibraryShell
      documents={lib.documents}
      errors={lib.errors}
      loading={lib.loading}
      selectedIndex={lib.selectedIndex}
      onSelect={lib.select}
      titleOf={(m) => m.name}
      details={details}
      toolbar={toolbar}
      status={
        map
          ? `${nodes.length} of ${countNodes(map)} nodes shown · zoom ${Math.round(scale * 100)}%`
          : ""
      }
      hint="Click a node to collapse/expand · drag to pan · Ctrl+wheel to zoom"
      emptyMessage="No mind maps found in new_output/*/mindmaps."
    >
      {map ? (
        <div
          className="canvas-viewport"
          ref={viewport}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={endDrag}
          onMouseLeave={endDrag}
          onWheel={onWheel}
        >
          <svg
            width={(w + 2 * pad) * scale}
            height={(h + 2 * pad) * scale}
            viewBox={`0 0 ${w + 2 * pad} ${h + 2 * pad}`}
            role="img"
            aria-label={`Mind map: ${map.name}`}
          >
            {nodes.flatMap((node) =>
              node.children.map((child) => {
                const x1 = node.x + node.w + pad;
                const y1 = node.y + pad;
                const x2 = child.x + pad;
                const y2 = child.y + pad;
                const mid = (x1 + x2) / 2;
                return (
                  <path
                    key={`${node.id}->${child.id}`}
                    d={`M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`}
                    fill="none"
                    stroke="#a8b6c4"
                    strokeWidth={1.4}
                  />
                );
              }),
            )}
            {nodes.map((node) => {
              const hit = term && node.node.name.toLowerCase().includes(term);
              const palette = hit
                ? HIGHLIGHT
                : DEPTH_COLORS[Math.min(node.depth, DEPTH_COLORS.length - 1)];
              return (
                <g
                  key={node.id}
                  className={node.hasChildren ? "node clickable" : "node"}
                  onClick={() => toggle(node.id, node.hasChildren)}
                >
                  <rect
                    x={node.x + pad}
                    y={node.y - node.h / 2 + pad}
                    width={node.w}
                    height={node.h}
                    rx={6}
                    fill={palette.fill}
                    stroke={palette.stroke}
                    strokeWidth={1.2}
                  />
                  <text
                    x={node.x + node.w / 2 + pad}
                    y={node.y - node.h / 2 + pad + BOX_PAD_Y + LINE_HEIGHT * 0.75}
                    textAnchor="middle"
                    fontSize={11}
                    fontWeight={node.depth <= 1 ? 700 : 400}
                    fill={palette.text}
                  >
                    {node.lines.map((line, i) => (
                      <tspan
                        key={i}
                        x={node.x + node.w / 2 + pad}
                        dy={i === 0 ? 0 : LINE_HEIGHT}
                      >
                        {line}
                      </tspan>
                    ))}
                  </text>
                  {node.hasChildren && (
                    <>
                      <circle
                        cx={node.x + node.w + pad + 1}
                        cy={node.y + pad}
                        r={6}
                        fill="#ffffff"
                        stroke={palette.stroke}
                      />
                      <text
                        x={node.x + node.w + pad + 1}
                        y={node.y + pad + 3}
                        textAnchor="middle"
                        fontSize={9}
                        fontWeight={700}
                        fill={palette.stroke}
                      >
                        {node.collapsed ? "+" : "−"}
                      </text>
                    </>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
      ) : (
        <div className="placeholder">Select a mind map.</div>
      )}
    </LibraryShell>
  );
}
