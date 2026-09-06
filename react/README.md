# Learning Content Viewers

React port of the tkinter launchers in `../python`. One route per content type,
reading the same JSON files that the Python viewers read from `../output`.

## Quick start

From the repository root, `run.bat` handles everything — install, sync, build,
and host — and opens the infographics:

```bat
run.bat
```

Or work in this folder directly:

```bash
npm install
npm run dev
```

Then open http://localhost:5174. `npm run sync` runs automatically before `dev`
and `build`; run it by hand after regenerating content.

### run.bat

| Command | What it does |
|---|---|
| `run.bat` | Sync, build, host on 4173, open `#/infographics` |
| `run.bat dev` | Sync, then dev server on 5174 with hot reload |
| `run.bat build` | Sync and build only |
| `run.bat sync` | Copy `output\` into `react/public/data` only |

Options: `--port N` to change the port, `--no-open` to skip the browser. Exits
non-zero on failure, so it works in CI or a task runner.

## Scripts

| Script | What it does |
|---|---|
| `npm run sync` | Copy `../output/**/*.json` into `public/data` and write `manifest.json` |
| `npm run dev` | Sync, then start Vite on port 5174 |
| `npm run build` | Sync, typecheck, and build to `dist/` |
| `npm run preview` | Serve the production build |
| `npm run typecheck` | Types only, no emit |

## Where each Python script went

| Python | React |
|---|---|
| `launcher_common.py` | `src/components/LibraryShell.tsx` + `src/lib/useLibrary.ts` |
| `quiz_launcher.py` | `src/views/QuizView.tsx` |
| `flashcards_launcher.py` + `flashcard_launcher.py` | `src/views/FlashcardsView.tsx` |
| `mindmap_viewer.py` | `src/views/MindmapView.tsx` |
| `reports_launcher.py` | `src/views/ReportsView.tsx` |
| `slides_launcher.py` | `src/views/SlidesView.tsx` |
| `datatable_launcher.py` + `datatable_viewer.py` | `src/views/DatatableView.tsx` |
| `infographic_launcher.py` | `src/views/InfographicView.tsx` |

Two pairs of Python scripts covered the same content type under singular and
plural names. Each pair became one view taking the union of both feature sets:

- **Flashcards** — tag/type filters, shuffle, and "review missed" from
  `flashcards_launcher.py`; mastery marking and reshuffle-on-completion from
  `flashcard_launcher.py`
- **Data tables** — header sorting, filtering, and the record pane from
  `datatable_launcher.py`; JSON export alongside CSV from `datatable_viewer.py`

Ported helpers live in `src/lib/format.ts`: `parseChartItem`, `formatCitation`,
`sortRows`, `toCsv`, `groupPanels`, and `sanitizeSvg`, each matching its Python
counterpart's behaviour.

## Data flow

The tkinter launchers open JSON straight off disk with `pathlib`. A browser
cannot, so `scripts/sync-data.mjs` stages `../output` into `public/data` and
emits a manifest listing every document plus its sidecar files (`.md`, `.html`,
`.svg`, `.csv`, `.wireframe.txt`). Views fetch the manifest, then load their
kind. A malformed document is reported in the sidebar rather than taking the
view down, matching `launcher_common.load_documents`.

`public/data/` is generated and git-ignored.

## Differences from the Python viewers

- **SVG infographic sections render**. tkinter cannot rasterize SVG without a
  third-party library, so `infographic_launcher.py` showed a stub card. The
  browser inlines the diagram after sanitizing it with the same rules as
  `infographic.sanitize_svg`.
- **Mind maps are SVG, not Canvas**, using the same tidy-tree layout — so pan,
  zoom, and text scaling come for free.
- **Exports download** rather than opening a save dialog.
- **Present mode is an overlay**, not an OS full-screen window; Esc exits.
- Routing uses `HashRouter`, so `dist/` also works opened from the filesystem.

## Keyboard

- **Quiz** — click to answer, submit, then advance
- **Flashcards** — space flips then advances, ← → navigate, `j` known, `f` review
- **Slides** — ← → or space to move, F5 present, Esc exit
- **Mind maps** — click a node to collapse/expand, drag to pan, Ctrl+wheel zoom
