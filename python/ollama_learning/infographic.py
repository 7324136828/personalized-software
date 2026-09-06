"""Generate infographic specifications from documents using Ollama.

Rendering runs in two stages. The *pre-infographic* is a plain-text wireframe of
the panel layout, meant to be reviewed (and corrected) before anything is
finalized; ``save_infographic(..., format="wireframe")`` produces it. The final
render then goes to HTML, SVG, Markdown, or JSON. The CLI writes the
pre-infographic automatically whenever ``--pre-infographic`` is supplied.
"""

import html
import json
import logging
import re
import textwrap
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .client_interface import BaseLLMClient
from .rag_system import RAGSystem
from .schemas import Infographic, InfographicSection

LOG = logging.getLogger(__name__)

SECTION_TYPES = ("stat", "flow", "chart", "quote", "comparison", "svg")

# "Label: 42", "Label | 42" and "Label — 42%" all parse; anything else is label-only.
_CHART_ITEM = re.compile(r"^(?P<label>.+?)\s*[:|—-]\s*(?P<value>[\d.]+)\s*(?P<unit>%|[A-Za-z]*)$")

# Defence in depth for SVG pulled in from disk: drop scripts, event handlers, and
# external references before the markup is inlined into a page.
_SVG_SCRIPT = re.compile(r"<script\b.*?</script\s*>", re.S | re.I)
_SVG_FOREIGN = re.compile(r"<foreignObject\b.*?</foreignObject\s*>", re.S | re.I)
_SVG_ON_ATTR = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_SVG_HREF = re.compile(r"\s(?:xlink:)?href\s*=\s*(\"|')\s*(?!#)[a-z]+:[^\"']*\1", re.I)
_SVG_TAG = re.compile(r"<svg\b[^>]*>", re.I)
_SVG_VIEWBOX = re.compile(r'viewBox\s*=\s*["\']([-\d.\s]+)["\']', re.I)
_SVG_DIM = re.compile(r'\b(width|height)\s*=\s*["\']([\d.]+)\w*["\']', re.I)


def display_width(text: str) -> int:
    """Terminal column width of a string, counting CJK characters as two columns."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _wrap_wide(text: str, width: int) -> List[str]:
    """Wrap text to a column width, measuring CJK characters as two columns."""
    lines: List[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if display_width(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        # a single word wider than the column is split on character boundaries
        while display_width(word) > width:
            cut = ""
            for char in word:
                if display_width(cut + char) > width:
                    break
                cut += char
            lines.append(cut)
            word = word[len(cut):]
        current = word
    if current:
        lines.append(current)
    return lines


def parse_chart_item(item: str) -> Tuple[str, Optional[float], str]:
    """Split a chart item into (label, numeric value, unit). Value is None if absent."""
    match = _CHART_ITEM.match(item.strip())
    if not match:
        return item.strip(), None, ""
    try:
        return match.group("label").strip(), float(match.group("value")), match.group("unit")
    except ValueError:
        return item.strip(), None, ""


def sanitize_svg(markup: str) -> str:
    """Strip scripts, event handlers, and external references from SVG markup."""
    cleaned = _SVG_SCRIPT.sub("", markup)
    cleaned = _SVG_FOREIGN.sub("", cleaned)
    cleaned = _SVG_ON_ATTR.sub("", cleaned)
    cleaned = _SVG_HREF.sub("", cleaned)
    start = cleaned.lower().find("<svg")
    return cleaned[start:].strip() if start != -1 else cleaned.strip()


def load_svg(value: str, base_dir: Optional[Path] = None) -> str:
    """Resolve an svg section's value: inline markup, or a path relative to base_dir."""
    text = (value or "").strip()
    if not text:
        raise ValueError("svg section has no value")
    if "<svg" in text.lower():
        return sanitize_svg(text)

    path = Path(text)
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    if not path.exists():
        raise FileNotFoundError(f"SVG file not found: {path}")
    return sanitize_svg(path.read_text(encoding="utf-8"))


def svg_viewport(markup: str) -> Tuple[float, float]:
    """Best-effort intrinsic size of an SVG, falling back to a 16:9 box."""
    tag = _SVG_TAG.search(markup)
    if tag:
        box = _SVG_VIEWBOX.search(tag.group(0))
        if box:
            parts = box.group(1).split()
            if len(parts) == 4:
                try:
                    return float(parts[2]), float(parts[3])
                except ValueError:
                    pass
        dims = dict((k.lower(), v) for k, v in _SVG_DIM.findall(tag.group(0)))
        if "width" in dims and "height" in dims:
            try:
                return float(dims["width"]), float(dims["height"])
            except ValueError:
                pass
    return 640.0, 360.0


def group_panels(sections: List[InfographicSection]) -> List[Tuple[Optional[str], List[InfographicSection]]]:
    """Group sections into (panel name, sections), preserving order.

    Sections without a panel are grouped under None. Sections sharing a panel name
    are kept together even when they are not adjacent in the spec.
    """
    order: List[Optional[str]] = []
    buckets: Dict[Optional[str], List[InfographicSection]] = {}
    for section in sections:
        key = section.panel or None
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(section)
    return [(key, buckets[key]) for key in order]


class InfographicGenerator:
    """Generate infographic specifications using RAG and Ollama."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        rag_system: RAGSystem
    ):
        self.llm_client = llm_client
        self.rag = rag_system

    def generate_infographic(
        self,
        topic: str,
        source_id: Optional[str] = None,
        section_count: int = 6,
        panels: bool = True
    ) -> Infographic:
        """Generate an infographic specification on a topic."""

        # Retrieve relevant context
        LOG.info(f"Retrieving context for topic: {topic}")
        context_chunks = self.rag.retrieve(topic, top_k=15, source_id=source_id)

        if not context_chunks:
            LOG.warning("No relevant context found, generating without RAG")
            context_text = "No specific context available."
        else:
            context_text = "\n\n".join([
                f"[{chunk.filename}]: {chunk.text}"
                for chunk in context_chunks
            ])

        panel_guidance = (
            """
Group the sections into panels. Give every section a "panel" name; sections that
share a name are rendered together under one heading, in the order given. Aim for
three to five panels, each holding two to four sections. Set "span" to "half" on
two consecutive sections that should sit side by side (for example, two opposed
paths), and leave it "full" otherwise.
"""
            if panels else ""
        )

        # Build prompt
        prompt = f"""Generate an infographic specification for: {topic}

Relevant context from source documents:
{context_text}

Create {section_count} sections drawn from the source material, using these types:
- stat: a single headline figure. Put the figure in "value" and its meaning in "label".
- chart: a small set of comparable magnitudes. Put entries in "items" as "Label: number",
  optionally with a unit, e.g. "Recall questions: 24" or "Coverage: 80%".
- flow: an ordered sequence of steps. Put the steps in "items" in order.
- comparison: two or more things set against each other. Put entries in "items",
  using " vs " to separate the two sides of a pair when there is a pairing.
- quote: a short verbatim quotation. Put the quotation in "value" and the attribution in "label".
- svg: a diagram supplied as a file. Put the path in "value" and a caption in "label".
  Only use this type when a diagram file already exists; do not invent paths.
{panel_guidance}
Requirements:
- Give every section a short title
- Use only figures and wording supported by the source documents
- Lead with the most consequential panel
- Keep labels under about eight words so they fit the rendered layout
"""

        # Define JSON schema
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": list(SECTION_TYPES)},
                            "title": {"type": "string"},
                            "value": {"type": "string"},
                            "label": {"type": "string"},
                            "items": {"type": "array", "items": {"type": "string"}},
                            "panel": {"type": "string"},
                            "span": {"type": "string", "enum": ["full", "half"]}
                        },
                        "required": ["type"]
                    }
                }
            },
            "required": ["title", "sections"]
        }

        try:
            response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=schema,
                temperature=0.7
            )

            infographic_data = json.loads(response)
            return Infographic(**infographic_data)

        except Exception as e:
            LOG.error(f"Failed to generate infographic: {e}")
            raise

    # -- saving ------------------------------------------------------------

    def save_infographic(
        self,
        infographic: Infographic,
        output_path: Path,
        format: str = "html",
        base_dir: Optional[Path] = None
    ):
        """Save infographic to file.

        `base_dir` resolves relative paths in svg sections; it defaults to the
        output file's own directory.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        base_dir = base_dir or output_path.parent

        if format == "json":
            self._save_json(infographic, output_path)
        elif format == "html":
            self._save_html(infographic, output_path, base_dir)
        elif format == "markdown":
            self._save_markdown(infographic, output_path)
        elif format == "svg":
            self._save_svg(infographic, output_path, base_dir)
        elif format == "wireframe":
            self._save_wireframe(infographic, output_path)
        else:
            raise ValueError(f"Unsupported format: {format}")

        LOG.info(f"Saved infographic to {output_path}")

    def _save_json(self, infographic: Infographic, output_path: Path):
        """Save infographic specification as JSON."""
        output_path.write_text(
            json.dumps(infographic.model_dump(mode='json'), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    # -- pre-infographic ---------------------------------------------------

    def _save_wireframe(self, infographic: Infographic, output_path: Path, width: int = 78):
        """Save the pre-infographic: a plain-text wireframe of the panel layout.

        This is the review stage. It shows how many panels there are, what sits in
        each, and which sections pair up side by side, without committing to any
        final styling.
        """
        output_path.write_text(self.render_wireframe(infographic, width), encoding="utf-8")

    def render_wireframe(self, infographic: Infographic, width: int = 78) -> str:
        """Render the pre-infographic wireframe as text."""
        inner = width - 2
        lines: List[str] = []

        def rule(char: str = "-") -> None:
            lines.append("+" + char * inner + "+")

        def row(text: str = "", align: str = "left") -> None:
            for piece in (_wrap_wide(text, inner - 2) or [""]):
                pad = inner - 2 - display_width(piece)
                if align == "center":
                    body = " " * (pad // 2) + piece + " " * (pad - pad // 2)
                else:
                    body = piece + " " * pad
                lines.append("| " + body + " |")

        def split_row(left: str, right: str) -> None:
            half = (inner - 3) // 2
            left_lines = _wrap_wide(left, half - 1) or [""]
            right_lines = _wrap_wide(right, half - 1) or [""]
            for i in range(max(len(left_lines), len(right_lines))):
                a = left_lines[i] if i < len(left_lines) else ""
                b = right_lines[i] if i < len(right_lines) else ""
                a += " " * (half - display_width(a))
                b += " " * (half - display_width(b))
                lines.append("| " + a + "|" + " " + b + " |")

        rule("=")
        row(infographic.title.upper(), "center")
        if infographic.subtitle:
            row(infographic.subtitle, "center")
        rule("=")

        panels = group_panels(infographic.sections)
        for index, (name, sections) in enumerate(panels, start=1):
            lines.append("")
            heading = f"PANEL {index}: {name}" if name else f"PANEL {index}"
            rule()
            row(heading)
            rule()

            i = 0
            while i < len(sections):
                section = sections[i]
                pair = (
                    sections[i + 1]
                    if section.span == "half" and i + 1 < len(sections)
                    and sections[i + 1].span == "half"
                    else None
                )
                if pair is not None:
                    split_row(self._wireframe_block(section), self._wireframe_block(pair))
                    i += 2
                else:
                    row(self._wireframe_block(section))
                    i += 1
                rule()

        lines.append("")
        lines.append(
            f"{len(panels)} panel(s), {len(infographic.sections)} section(s). "
            "Review this layout, then render the final artifact."
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _wireframe_block(section: InfographicSection) -> str:
        """One-line summary of a section for the wireframe."""
        head = f"[{section.type}] {section.title or ''}".strip()
        if section.type == "stat":
            detail = f"{section.value or ''} — {section.label or ''}"
        elif section.type == "quote":
            detail = f'"{(section.value or "")[:60]}" — {section.label or ""}'
        elif section.type == "svg":
            detail = f"diagram: {section.value or ''}"
        elif section.type == "chart":
            detail = " / ".join(section.items[:4]) + (" …" if len(section.items) > 4 else "")
        else:
            detail = " -> ".join(section.items[:4]) + (" …" if len(section.items) > 4 else "")
        return f"{head} :: {detail.strip(' —')}"

    # -- markdown ----------------------------------------------------------

    def _save_markdown(self, infographic: Infographic, output_path: Path):
        """Save infographic as Markdown."""
        lines = [f"# {infographic.title}", ""]
        if infographic.subtitle:
            lines += [f"*{infographic.subtitle}*", ""]

        for index, (name, sections) in enumerate(group_panels(infographic.sections), start=1):
            if name:
                lines += [f"## Panel {index}: {name}", ""]

            for section in sections:
                heading = "###" if name else "##"
                lines.append(f"{heading} {section.title or section.type.title()}")

                if section.type == "stat":
                    lines.append(f"**{section.value or ''}**")
                    if section.label:
                        lines.append(f"  {section.label}")
                elif section.type == "quote":
                    lines.append(f"> {section.value or ''}")
                    if section.label:
                        lines += [">", f"> — {section.label}"]
                elif section.type == "flow":
                    for i, item in enumerate(section.items, start=1):
                        lines.append(f"{i}. {item}")
                elif section.type == "chart":
                    for item in section.items:
                        label, value, unit = parse_chart_item(item)
                        lines.append(f"- {label}: {value:g}{unit}" if value is not None else f"- {label}")
                elif section.type == "svg":
                    lines.append(f"![{section.label or section.title or 'diagram'}]({section.value or ''})")
                else:  # comparison
                    for item in section.items:
                        lines.append(f"- {item}")

                lines.append("")

        output_path.write_text("\n".join(lines), encoding="utf-8")

    # -- html --------------------------------------------------------------

    def _save_html(self, infographic: Infographic, output_path: Path, base_dir: Path):
        """Save infographic as a self-contained HTML page."""
        panels = []
        for index, (name, sections) in enumerate(group_panels(infographic.sections), start=1):
            cards = "\n".join(self._render_section(s, base_dir) for s in sections)
            heading = (
                f'    <h2 class="panel-title"><span class="panel-num">{index}</span>'
                f"{html.escape(name)}</h2>\n" if name else ""
            )
            panels.append(f'  <section class="panel">\n{heading}    <div class="grid">\n{cards}\n    </div>\n  </section>')
        body = "\n".join(panels)
        subtitle = (
            f'  <p class="subtitle">{html.escape(infographic.subtitle)}</p>\n'
            if infographic.subtitle else ""
        )

        page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(infographic.title)}</title>
<style>
  :root {{
    --bg: #f4f6f8; --card: #ffffff; --ink: #16293f; --muted: #6b7580;
    --line: #dbe2ea; --accent: #2f6f9f; --accent-soft: #dce9f5; --panel: #eef2f6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f1720; --card: #17222e; --ink: #e8eef4; --muted: #94a3b1;
      --line: #26343f; --accent: #6fa8d6; --accent-soft: #22384b; --panel: #131e29;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 40px 20px; background: var(--bg); color: var(--ink);
    font: 16px/1.5 "Segoe UI", system-ui, -apple-system, sans-serif;
  }}
  main {{ max-width: 1040px; margin: 0 auto; }}
  h1 {{ font-size: 2rem; margin: 0 0 6px; letter-spacing: -0.01em; }}
  .subtitle {{ color: var(--muted); margin: 0 0 26px; }}
  .panel {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
    padding: 18px; margin-bottom: 22px;
  }}
  .panel-title {{
    display: flex; align-items: center; gap: 10px; font-size: 1.05rem;
    margin: 4px 4px 14px; letter-spacing: 0.01em;
  }}
  .panel-num {{
    background: var(--accent); color: #fff; border-radius: 999px;
    width: 26px; height: 26px; display: inline-flex; align-items: center;
    justify-content: center; font-size: 0.82rem; flex: none;
  }}
  .grid {{ display: grid; gap: 14px; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .card {{
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 20px 22px; grid-column: span 2; min-width: 0;
  }}
  .card.half {{ grid-column: span 1; }}
  @media (max-width: 720px) {{ .card.half {{ grid-column: span 2; }} }}
  .kicker {{
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.09em;
    color: var(--muted); margin-bottom: 10px;
  }}
  .stat-value {{ font-size: 2.6rem; font-weight: 700; color: var(--accent); line-height: 1.1; }}
  .stat-label {{ color: var(--muted); margin-top: 6px; }}
  .bar-row {{ display: grid; grid-template-columns: minmax(90px, 34%) 1fr auto; gap: 12px;
              align-items: center; margin: 10px 0; }}
  .bar-track {{ background: var(--accent-soft); border-radius: 999px; height: 12px; }}
  .bar-fill {{ background: var(--accent); border-radius: 999px; height: 100%; }}
  .bar-value {{ font-variant-numeric: tabular-nums; color: var(--muted); font-size: 0.88rem; }}
  ol.flow {{ margin: 0; padding-left: 20px; }}
  ol.flow li {{ margin: 8px 0; }}
  .pair {{ display: grid; grid-template-columns: 1fr auto 1fr; gap: 12px; align-items: center;
           padding: 10px 0; border-bottom: 1px solid var(--line); }}
  .pair:last-child {{ border-bottom: 0; }}
  .pair .vs {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; }}
  blockquote {{ margin: 0; font-size: 1.15rem; line-height: 1.5; }}
  blockquote footer {{ margin-top: 12px; color: var(--muted); font-size: 0.9rem; }}
  figure {{ margin: 0; }}
  figure svg {{ display: block; width: 100%; height: auto; max-width: 100%; }}
  figcaption {{ color: var(--muted); font-size: 0.88rem; margin-top: 10px; }}
</style>
</head>
<body>
<main>
  <h1>{html.escape(infographic.title)}</h1>
{subtitle}{body}
</main>
</body>
</html>
"""
        output_path.write_text(page, encoding="utf-8")

    def _render_section(self, section: InfographicSection, base_dir: Path) -> str:
        """Render one section as an HTML card."""
        esc = html.escape
        kicker = f'<div class="kicker">{esc(section.title)}</div>' if section.title else ""
        klass = "card half" if section.span == "half" else "card"
        body = ""

        if section.type == "stat":
            body = (
                f'<div class="stat-value">{esc(section.value or "")}</div>'
                f'<div class="stat-label">{esc(section.label or "")}</div>'
            )

        elif section.type == "quote":
            attribution = f"<footer>— {esc(section.label)}</footer>" if section.label else ""
            body = f"<blockquote>{esc(section.value or '')}{attribution}</blockquote>"

        elif section.type == "flow":
            steps = "".join(f"<li>{esc(item)}</li>" for item in section.items)
            body = f'<ol class="flow">{steps}</ol>'

        elif section.type == "chart":
            parsed = [parse_chart_item(item) for item in section.items]
            values = [v for _, v, _ in parsed if v is not None]
            peak = max(values) if values else 0
            rows = []
            for label, value, unit in parsed:
                width = (value / peak * 100) if value is not None and peak else 0
                shown = f"{value:g}{unit}" if value is not None else ""
                rows.append(
                    f'<div class="bar-row"><span>{esc(label)}</span>'
                    f'<span class="bar-track"><span class="bar-fill" style="width:{width:.1f}%"></span></span>'
                    f'<span class="bar-value">{esc(shown)}</span></div>'
                )
            body = "".join(rows)

        elif section.type == "svg":
            try:
                markup = load_svg(section.value or "", base_dir)
            except (OSError, ValueError) as exc:
                LOG.warning(f"svg section could not be inlined: {exc}")
                body = f'<p class="stat-label">Diagram unavailable: {esc(str(exc))}</p>'
            else:
                caption = f"<figcaption>{esc(section.label)}</figcaption>" if section.label else ""
                body = f"<figure>{markup}{caption}</figure>"

        else:  # comparison
            rows = []
            for item in section.items:
                if " vs " in item:
                    left, right = item.split(" vs ", 1)
                    rows.append(
                        f'<div class="pair"><span>{esc(left.strip())}</span>'
                        f'<span class="vs">vs</span><span>{esc(right.strip())}</span></div>'
                    )
                else:
                    rows.append(f'<div class="pair"><span>{esc(item)}</span></div>')
            body = "".join(rows)

        return f'      <section class="{klass}">{kicker}{body}</section>'

    # -- svg ---------------------------------------------------------------

    def _save_svg(self, infographic: Infographic, output_path: Path, base_dir: Path):
        """Save the whole infographic as a single standalone SVG."""
        W, PAD, CARD_PAD = 900, 28, 18
        body: list = []
        y = float(PAD + 12)

        y = self._svg_text(body, infographic.title, PAD, y, 26, "#16293f", "bold") + 8
        if infographic.subtitle:
            y = self._svg_wrap(body, infographic.subtitle, PAD, y, 13, "#6b7580", 100)
        y += 10

        for index, (name, sections) in enumerate(group_panels(infographic.sections), start=1):
            if name:
                y += 18
                body.append(f'<circle cx="{PAD + 11}" cy="{y - 5:.0f}" r="11" fill="#2f6f9f"/>')
                self._svg_text(body, str(index), PAD + 11, y - 1, 11, "#ffffff", "bold", "middle")
                self._svg_text(body, name, PAD + 32, y, 15, "#16293f", "bold")
                y += 20

            for section in sections:
                card: list = []
                cy = self._svg_section(card, section, base_dir, PAD, CARD_PAD, W, y + CARD_PAD + 14)
                height = cy - y + CARD_PAD - 4
                body.append(
                    f'<rect x="{PAD}" y="{y:.0f}" width="{W - 2 * PAD}" height="{height:.0f}" '
                    f'rx="12" fill="#ffffff" stroke="#dbe2ea"/>'
                )
                body.extend(card)
                y += height + 12

        total_h = y + PAD
        content = "\n".join(body)
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"\n'
            f'     width="{W}" height="{total_h:.0f}" viewBox="0 0 {W} {total_h:.0f}">\n'
            '<rect width="100%" height="100%" fill="#f4f6f8"/>\n'
            f"{content}\n</svg>\n"
        )
        output_path.write_text(svg, encoding="utf-8")

    # -- svg drawing primitives -------------------------------------------

    @staticmethod
    def _svg_text(out: list, content: str, x: float, y: float, size: int, fill: str,
                  weight: str = "normal", anchor: str = "start") -> float:
        out.append(
            f'<text x="{x:.0f}" y="{y:.0f}" font-family="Segoe UI, system-ui, sans-serif" '
            f'font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}">{html.escape(content)}</text>'
        )
        return y + size * 1.2

    @classmethod
    def _svg_wrap(cls, out: list, content: str, x: float, y: float, size: int, fill: str,
                  chars: int) -> float:
        for line in textwrap.wrap(content, chars) or [""]:
            cls._svg_text(out, line, x, y, size, fill)
            y += size * 1.45
        return y

    def _svg_section(self, out: list, section: InfographicSection, base_dir: Path,
                     PAD: int, CARD_PAD: int, W: int, cy: float) -> float:
        """Draw one section into `out`, returning the y coordinate after it."""
        left = PAD + CARD_PAD

        if section.title:
            self._svg_text(out, section.title.upper(), left, cy, 10, "#6b7580", "bold")
            cy += 18

        if section.type == "stat":
            self._svg_text(out, section.value or "", left, cy + 20, 34, "#2f6f9f", "bold")
            cy += 46
            cy = self._svg_wrap(out, section.label or "", left, cy, 12, "#6b7580", 92)

        elif section.type == "quote":
            cy = self._svg_wrap(out, f'“{section.value or ""}”', left, cy + 6, 16,
                                "#16293f", 70)
            if section.label:
                cy = self._svg_wrap(out, f"— {section.label}", left, cy + 4, 11, "#6b7580", 100)

        elif section.type == "flow":
            for i, item in enumerate(section.items, start=1):
                out.append(
                    f'<rect x="{left}" y="{cy - 11:.0f}" width="18" height="18" rx="4" fill="#dce9f5"/>'
                )
                self._svg_text(out, str(i), left + 9, cy + 3, 10, "#2f6f9f", "bold", "middle")
                cy = self._svg_wrap(out, item, left + 28, cy, 12, "#16293f", 84) + 4

        elif section.type == "chart":
            parsed = [parse_chart_item(i) for i in section.items]
            values = [v for _, v, _ in parsed if v is not None]
            peak = max(values) if values else 0
            track_x = left + 210
            track_w = W - track_x - PAD - CARD_PAD - 56
            for label, value, unit in parsed:
                self._svg_text(out, label, track_x - 10, cy + 4, 11, "#16293f", "normal", "end")
                out.append(
                    f'<rect x="{track_x}" y="{cy - 5:.0f}" width="{track_w}" height="11" '
                    f'rx="5.5" fill="#dce9f5"/>'
                )
                if value is not None and peak:
                    out.append(
                        f'<rect x="{track_x}" y="{cy - 5:.0f}" width="{track_w * (value / peak):.1f}" '
                        f'height="11" rx="5.5" fill="#2f6f9f"/>'
                    )
                    self._svg_text(out, f"{value:g}{unit}", W - PAD - CARD_PAD, cy + 4, 11,
                                   "#6b7580", "normal", "end")
                cy += 24

        elif section.type == "svg":
            try:
                markup = load_svg(section.value or "", base_dir)
            except (OSError, ValueError) as exc:
                LOG.warning(f"svg section could not be embedded: {exc}")
                cy = self._svg_wrap(out, f"Diagram unavailable: {exc}", left, cy, 12, "#6b7580", 92)
            else:
                vw, vh = svg_viewport(markup)
                box_w = W - 2 * PAD - 2 * CARD_PAD
                box_h = box_w * (vh / vw) if vw else 300.0
                out.append(
                    f'<svg x="{left}" y="{cy - 6:.0f}" width="{box_w}" height="{box_h:.0f}" '
                    f'viewBox="0 0 {vw:g} {vh:g}" preserveAspectRatio="xMidYMid meet">'
                    f"{markup}</svg>"
                )
                cy += box_h + 6
                if section.label:
                    cy = self._svg_wrap(out, section.label, left, cy + 10, 11, "#6b7580", 100)

        else:  # comparison
            mid = PAD + (W - 2 * PAD) / 2
            for item in section.items:
                if " vs " in item:
                    a, b = item.split(" vs ", 1)
                    ly = self._svg_wrap(out, a.strip(), left, cy, 12, "#16293f", 46)
                    ry = self._svg_wrap(out, b.strip(), mid + 18, cy, 12, "#16293f", 46)
                    self._svg_text(out, "vs", mid, cy + 3, 9, "#6b7580", "bold", "middle")
                    cy = max(ly, ry) + 6
                else:
                    cy = self._svg_wrap(out, item, left, cy, 12, "#16293f", 96) + 6

        return cy


def main():
    """CLI for infographic generation."""
    import argparse
    from pathlib import Path
    from .client_interface import create_client

    parser = argparse.ArgumentParser(description="Generate infographics using LLM")
    parser.add_argument("--input", type=Path, required=True, help="Input folder with documents")
    parser.add_argument("--topic", type=str, required=True, help="Infographic topic")
    parser.add_argument("--output", type=Path, required=True, help="Output file path")
    parser.add_argument("--format", choices=["json", "html", "markdown", "svg", "wireframe"],
                        default="html")
    parser.add_argument("--sections", type=int, default=6, help="Number of sections to generate")
    parser.add_argument("--no-panels", action="store_true",
                        help="Generate a flat section list instead of grouped panels")
    parser.add_argument("--pre-infographic", type=Path, default=None,
                        help="Write the wireframe preview here before rendering the final output")
    parser.add_argument("--svg-dir", type=Path, default=None,
                        help="Base directory for resolving svg section paths (default: output dir)")
    parser.add_argument("--provider", choices=["ollama", "openai", "claude"], default="ollama", help="LLM provider")
    parser.add_argument("--model", type=str, default="qwen2.5", help="Model to use")
    parser.add_argument("--embedding-model", type=str, default=None, help="Embedding model (provider-specific)")
    parser.add_argument("--api-key", type=str, default=None, help="API key for OpenAI/Claude")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    # Initialize client
    client_kwargs = {}
    if args.api_key:
        client_kwargs["api_key"] = args.api_key
    if args.embedding_model:
        client_kwargs["embedding_model"] = args.embedding_model

    llm_client = create_client(args.provider, args.model, **client_kwargs)

    # Initialize RAG (skip for Claude since it doesn't have embeddings)
    if args.provider == "claude":
        LOG.warning("Claude doesn't support embeddings. RAG will be disabled.")
        rag = None
    else:
        rag = RAGSystem(llm_client)

    # Ingest documents (only if RAG is available)
    if rag:
        LOG.info(f"Ingesting documents from {args.input}")
        for file_path in args.input.glob("*.txt"):
            LOG.info(f"Processing {file_path.name}")
            rag.add_document_from_file(file_path)
    else:
        LOG.info("Skipping document ingestion (no RAG available)")

    # Generate infographic
    generator = InfographicGenerator(llm_client, rag)
    infographic = generator.generate_infographic(
        args.topic, section_count=args.sections, panels=not args.no_panels
    )

    # Pre-infographic stage: write the wireframe for review before finalizing
    if args.pre_infographic:
        generator.save_infographic(infographic, args.pre_infographic, "wireframe")
        LOG.info(f"Wrote pre-infographic wireframe to {args.pre_infographic}")

    # Save infographic
    generator.save_infographic(infographic, args.output, args.format, base_dir=args.svg_dir)


if __name__ == "__main__":
    main()
