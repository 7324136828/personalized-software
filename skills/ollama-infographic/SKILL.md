# AI Infographic Generator

Generate infographic specifications from documents using multiple LLM providers (Ollama, OpenAI, Claude) with RAG.

## Features

- Create visual infographic specifications from source documents
- **Two-stage rendering**: review a plain-text wireframe before finalizing
- Multi-panel layouts with full-width and half-width sections
- Six section types: stat, chart, flow, comparison, quote, **svg**
- Embed existing SVG diagrams, inlined and sanitized
- Export to self-contained HTML, standalone SVG, Markdown, or JSON
- Responsive layout with automatic light/dark theming
- Support for multiple LLM providers

## The Two-Stage Workflow

Do not go straight to HTML. Generate the **pre-infographic** first — a plain-text
wireframe showing panel structure, section order, and which sections pair up side
by side. Read it, correct the spec, and only then render the final artifact.

```bash
# Stage 1 + 2 in one run: write the wireframe, then finalize
python python/ollama_learning/infographic.py \
  --input input/classical_chinese \
  --topic "the Qingjing Jing" \
  --pre-infographic output/infographics/qingjing.wireframe.txt \
  --output output/infographics/qingjing.html \
  --format html \
  --provider ollama \
  --model qwen2.5
```

To stop at the wireframe and inspect it before committing, use `--format wireframe`:

```bash
python python/ollama_learning/infographic.py \
  --input input/classical_chinese \
  --topic "the Qingjing Jing" \
  --output output/infographics/qingjing.wireframe.txt \
  --format wireframe \
  --provider ollama \
  --model qwen2.5
```

The wireframe looks like this — panel boxes, one line per section, `|` splitting
sections that sit side by side:

```
+============================================================================+
|              THE SCRIPTURE OF CONSTANT CLARITY AND STILLNESS               |
+============================================================================+

+----------------------------------------------------------------------------+
| PANEL 1: The Nature of the Great Dao & Cosmic Duality                      |
+----------------------------------------------------------------------------+
| [svg] Cosmic duality :: diagram: assets/qingjing_duality.svg               |
+----------------------------------------------------------------------------+
| [flow] Yang — clarity, movement ::  | [flow] Yin — turbidity, stillness    |
| Heaven -> Active -> Clear           | :: Earth -> Still -> Turbid          |
+----------------------------------------------------------------------------+
```

Borders are measured in display columns, so CJK text stays aligned.

## Usage

### Using Ollama (Local)

```bash
python python/ollama_learning/infographic.py \
  --input input/classical_chinese \
  --topic "how the five texts differ" \
  --output output/infographic.html \
  --format html \
  --sections 6 \
  --provider ollama \
  --model qwen2.5
```

### Using OpenAI

```bash
python python/ollama_learning/infographic.py \
  --input input/classical_chinese \
  --topic "how the five texts differ" \
  --output output/infographic.html \
  --format html \
  --sections 6 \
  --provider openai \
  --model gpt-4 \
  --api-key YOUR_OPENAI_API_KEY
```

### Using Claude

```bash
python python/ollama_learning/infographic.py \
  --input input/classical_chinese \
  --topic "how the five texts differ" \
  --output output/infographic.html \
  --format html \
  --sections 6 \
  --provider claude \
  --model claude-3-5-sonnet-20241022 \
  --api-key YOUR_ANTHROPIC_API_KEY
```

## Parameters

- `--input`: Input folder containing text documents (*.txt)
- `--topic`: Infographic topic
- `--output`: Output file path
- `--format`: Output format (json, html, markdown, svg, wireframe)
- `--sections`: Number of sections to generate (default: 6)
- `--pre-infographic`: Write the wireframe here before rendering the final output
- `--no-panels`: Generate a flat section list instead of grouped panels
- `--svg-dir`: Base directory for resolving svg section paths (default: the output directory)
- `--provider`: LLM provider (ollama, openai, claude)
- `--model`: Model to use
- `--embedding-model`: Embedding model (provider-specific)
- `--api-key`: API key for OpenAI/Claude

## Panels

Every section may carry a `panel` name. Sections sharing a name render together
under one numbered heading, in the order given — and they are grouped even if they
are not adjacent in the spec. Sections with no `panel` fall into a single unnamed
panel, so older flat specs keep working unchanged.

`span` controls width within a panel: `"full"` (default) takes the whole row, and
two consecutive `"half"` sections sit side by side. On narrow screens halves stack.

```json
{
  "type": "flow",
  "title": "The path of inner cultivation",
  "items": ["Eliminate desires", "Purify the mind"],
  "panel": "The Two Paths",
  "span": "half"
}
```

## Section Types

Every section has a `type` and an optional `title`. The remaining fields depend on the type:

| Type | Fields used | Renders as |
|------|-------------|------------|
| `stat` | `value`, `label` | A large headline figure above its caption |
| `chart` | `items` | Horizontal bars, scaled to the largest value |
| `flow` | `items` | A numbered sequence of steps |
| `comparison` | `items` | Paired rows split on ` vs ` |
| `quote` | `value`, `label` | A pull quote with attribution |
| `svg` | `value`, `label` | An inlined diagram with a caption |

### SVG sections

Put either a **file path** or **inline markup** in `value`. Paths are resolved
relative to the output directory, or to `--svg-dir` when given.

```json
{
  "type": "svg",
  "title": "Cosmic duality",
  "value": "assets/qingjing_duality.svg",
  "label": "Clarity and turbidity — each the root of the other",
  "panel": "The Nature of the Great Dao"
}
```

How each format handles it:

- **HTML** — the file is read and inlined into a `<figure>`, so the page stays
  self-contained with no external requests
- **SVG** — nested inside the document SVG, scaled to the card width by its `viewBox`
- **Markdown** — emitted as an image reference to the original path
- **Wireframe** — listed by path, so you can confirm the diagram before rendering

Markup is **sanitized on the way in**: `<script>` blocks, `<foreignObject>`,
`on*` event handlers, and external `href`/`xlink:href` references are stripped.
Geometry, gradients, markers, and text are preserved. A missing or unreadable file
degrades to a "Diagram unavailable" notice rather than failing the render.

Authoring notes for diagrams you supply:
- Give the root `<svg>` a `viewBox` so it scales to the card; without one, `width`
  and `height` are used, and failing both a 640×360 box is assumed
- Prefix `id` attributes (markers, gradients) to avoid collisions when several
  diagrams are inlined into one page — for example `qj-arrow-end`, not `arrow`
- Use explicit fills rather than inheriting page color, since the card background
  differs between light and dark themes

### Chart item format

Chart entries carry their magnitude in the string itself, as `Label: number` with an
optional unit. A separator of `:`, `|`, or an em dash all parse:

```json
{
  "type": "chart",
  "title": "Nodes per mind map",
  "items": ["Qian precepts: 89", "Zhu Zi precepts: 84", "Yin Fu Jing: 79"]
}
```

Entries without a parsable number render as label-only rows with no bar, so a partly
numeric chart still displays.

### Comparison item format

Use ` vs ` to split the two sides of a pairing. Entries without it render as single rows.

```json
{
  "type": "comparison",
  "title": "Stance toward the senses",
  "items": ["Heart Sutra: negated vs Yin Fu Jing: controlled"]
}
```

## Output Formats

- **wireframe**: The pre-infographic — plain-text panel layout for review
- **HTML**: A self-contained page with no external assets — open it directly in a browser
- **SVG**: One standalone vector file, suitable for print or embedding
- **Markdown**: Headings, ordered lists, blockquotes; suitable for docs and README embedding
- **JSON**: The `Infographic` structure, for custom rendering

## Structure

Infographics produced by this skill contain:
- A title and optional subtitle
- Three to five panels, most consequential first
- Two to four sections per panel
- Figures and wording restricted to what the source documents support
- Short labels (about eight words or fewer) so the rendered layout holds

## Rendering Notes

- The HTML output declares a light and a dark palette and follows the reader's system setting
- Panels are numbered; `half` sections pair on wide screens and stack under 720px
- All text content is HTML-escaped, and embedded SVG is sanitized
- No JavaScript and no network requests, so the page renders offline and can be emailed as a file
- The standalone SVG grows vertically to fit its content; the canvas is 900 units wide

## Viewing

`python python/infographic_launcher.py` browses a folder of specs, renders panels
and sections natively, opens the pre-infographic wireframe in a side window, and
launches the HTML export in a browser. SVG sections appear as a stub card naming
the source file, with a button to open the diagram — tkinter cannot rasterize SVG
without a third-party library, so the full diagram appears in the HTML and SVG
exports.

## Use Cases

- Summarize a report into a single shareable page
- Turn a comparison table into a visual matrix
- Produce a one-page briefing from a document set
- Combine hand-authored diagrams with generated statistics and quotations
- Build a study aid that pairs statistics with quotations

## Requirements

- For Ollama: Ollama running locally with required models
- For OpenAI: OpenAI API key
- For Claude: Anthropic API key
- For viewing: any modern browser (HTML and SVG output have no dependencies)
