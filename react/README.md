# Learning Content Viewers

React viewers for generated learning content. The app reads files from
`../output` through the local Python backend; no content-copy or sync step is
required.

## Quick start

From the repository root:

```bat
run.bat dev
```

This starts the backend and Vite together, then opens
http://localhost:5174/#/qanda. Newly generated content appears after clicking
**Reload content**.

For a production build and local server, run `run.bat`. Use `run.bat build` to
build without serving and `run.bat help` for all options.

| Command | What it does |
|---|---|
| `run.bat` | Build, host the app/API on 4173, and open Q&A |
| `run.bat dev` | Start the API and Vite on 5174 with hot reload |
| `run.bat build` | Build only |

From this directory, the equivalent npm scripts are:

| Script | What it does |
|---|---|
| `npm run dev` | Start the Python API and Vite on port 5174 |
| `npm run build` | Typecheck and build to `dist/` |
| `npm run start` | Serve `dist/`, output data, and Q&A APIs on port 8765 |
| `npm run typecheck` | Types only, no emit |

## Data flow

`../python/backend/server.py` builds a manifest from `../new_output` on every
request, merging every subject folder (`new_output/<subject>/<kind>/`) into one
list per kind. It serves JSON and related files (`.md`, `.html`, `.svg`,
`.csv`, `.mmd`, `.txt`, and `.wireframe.txt`) under `/api/content`. The browser
always sees current generated output without staging it in `react/public/data`.
The older flat `../output/<kind>/` layout is still read when present.

A malformed document is reported in the sidebar rather than taking the whole
view down. In development, Vite proxies `/api` to the backend. In production,
the backend serves the React build and API from the same origin.

## Free-text Q&A

Q&A sets live in `new_output/<subject>/qandas/*.json`. Questions may be plain
strings or objects:

```json
{
  "title": "Reading reflection",
  "description": "Answer in your own words.",
  "questions": [
    "What is the central idea?",
    {
      "id": "apply-it",
      "question": "How would you apply it?",
      "placeholder": "Describe a concrete example…",
      "required": true
    }
  ]
}
```

The browser autosaves answers through `/api/qa/sessions`. The backend writes
sessions to the operating system's temporary directory and prints the exact
location when it starts. The Q&A view restores the last session for each file
and can download its JSON during or after the flow.

Run `python ../python/backend/server.py --help` to configure the content,
response, static, or port location.

## Viewer map

| Python/content feature | React view |
|---|---|
| Quizzes | `src/views/QuizView.tsx` |
| `qanda_launcher.py` | `src/views/QandaView.tsx` |
| Flashcards | `src/views/FlashcardsView.tsx` |
| Mind maps | `src/views/MindmapView.tsx` |
| Reports | `src/views/ReportsView.tsx` |
| Slides | `src/views/SlidesView.tsx` |
| Data tables | `src/views/DatatableView.tsx` |
| Infographics | `src/views/InfographicView.tsx` |

## Keyboard

- **Quiz** — click to answer, submit, then advance
- **Flashcards** — space flips then advances, ← → navigate, `j` known, `f` review
- **Slides** — ← → or space to move, F5 present, Esc exit
- **Mind maps** — click a node to collapse/expand, drag to pan, Ctrl+wheel zoom
