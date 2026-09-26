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
http://localhost:5174/. The landing page lists the individual study sets in the
current and saved libraries. Upload a workspace ZIP or load a previously
uploaded ZIP from the website header. Each `output` directory listed by
`workspace.json` appears as a study set using its declared name. Newly generated
content appears after clicking **Reload content**.

Use **Upload ZIP** to import a workspace collection into the SQLite database at
the operating system's temporary
`personalized-software/workspaces/study-notes.sqlite3`. Uploaded archives may
be up to 512 MB compressed, 2 GB expanded during validation, and 20,000 files;
unsafe paths, symbolic links, and encrypted ZIPs are rejected. Custom Kokoro
`.pt` voice models and the synthesized flashcard narration cache remain
file-backed. Older extracted uploads are migrated automatically. **Load
existing workspace** lists imports held in the database.
Use **Delete** on a landing-page study-set card to remove that set. A confirmation
is required; deleting the final set also removes its now-empty library.
Use **Delete ZIP** in a library heading to remove the entire imported archive.

Every new ZIP import must contain exactly one `workspace.json`. Paths are
resolved relative to that file and must identify existing `output` directories:

```json
{
  "workspace": [
    {
      "name": "An Introduction to Statistical Learning",
      "path": "./an_introduction_to_statistical_learning/output"
    }
  ]
}
```

While a ZIP is received, extracted, validated, and saved, the app displays a
percentage and the name of the study set currently being processed.

When the app is started with `run.bat --lan`, another computer can also use the
output dropdown, **Upload ZIP**, and **Load existing workspace**.

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

After an output is selected in the website, `../python/backend/server.py`
builds a manifest from SQLite for imported workspaces, or from the configured
`output` folder for locally generated content, merging every
subject folder (`output/<subject>/<kind>/`) into one list per kind. It serves
JSON and related files (`.md`, `.html`, `.svg`,
`.csv`, `.mmd`, `.txt`, and `.wireframe.txt`) under `/api/content`. The browser
always sees current generated output without staging it in `react/public/data`.
Direct backend and npm commands still default to `../new_output`. The older flat
`output/<kind>/` layout is also read when present.

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
- **Flashcards** — space flips then advances, ← → navigate, `j` known, `f` review,
  and **Play** generates cached Kokoro narration for both sides
- **Slides** — ← → or space to move, F5 present, Esc exit
- **Mind maps** — click a node to collapse/expand, drag to pan, Ctrl+wheel zoom
