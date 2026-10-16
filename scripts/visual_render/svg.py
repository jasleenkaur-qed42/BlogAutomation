"""Precise technical visuals from Python templates (comparison, timeline, layers). All text is XML-escaped and
wrapped; text that does not fit is an error, never silently clipped. No free-form SVG from the planner."""
import textwrap
from xml.sax.saxutils import escape

import cairosvg

from . import RenderError, image_result

W = 1200
FONT = 'font-family="Helvetica, Arial, sans-serif"'
INK, MUTED, LINE, FILL_A, FILL_B, ACCENT = "#202124", "#5f6368", "#dadce0", "#f1f3f4", "#e8f0fe", "#1a73e8"


def _text(v, label, max_len):
    if not isinstance(v, str) or not v.strip():
        raise RenderError(f"svg: {label} must be non-empty text")
    if len(v) > max_len:
        raise RenderError(f"svg: {label} is {len(v)} characters; the limit is {max_len}")
    return v.strip()


def _lines(text, chars, max_lines, label):
    lines = textwrap.wrap(text, chars) or [text]
    if len(lines) > max_lines:
        raise RenderError(f"svg: {label} does not fit ({len(lines)} lines of {chars} characters, max {max_lines})")
    return lines


def _tspans(lines, x, y, size, step, fill=INK, weight="normal", anchor="start"):
    out = []
    for i, line in enumerate(lines):
        out.append(f'<text x="{x}" y="{y + i * step}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
                   f'text-anchor="{anchor}" {FONT}>{escape(line)}</text>')
    return "".join(out)


def _rows(data, key, lo, hi, width, what):
    rows = data.get(key)
    if not (isinstance(rows, list) and lo <= len(rows) <= hi
            and all(isinstance(r, list) and len(r) == width for r in rows)):
        raise RenderError(f"svg: {key} must be a list of {lo}-{hi} rows of {width} items ({what})")
    return rows


def comparison(data):
    left, right = _text(data.get("left"), "left", 28), _text(data.get("right"), "right", 28)
    rows = _rows(data, "rows", 1, 8, 3, "[dimension, left, right]")
    head, row_h, x0 = 70, 84, 40
    col_w = 420
    cols = [x0, x0 + 260, W - x0 - col_w]  # header cells end flush with the row's right edge
    height = head + row_h * len(rows) + 40
    body = [f'<rect x="{cols[1]}" y="20" width="{col_w}" height="{head - 20}" rx="8" fill="{FILL_B}"/>',
            f'<rect x="{cols[2]}" y="20" width="{col_w}" height="{head - 20}" rx="8" fill="{FILL_B}"/>',
            _tspans([left], cols[1] + col_w // 2, 53, 26, 0, ACCENT, "bold", "middle"),
            _tspans([right], cols[2] + col_w // 2, 53, 26, 0, ACCENT, "bold", "middle")]
    for i, (dim, a, b) in enumerate(rows):
        y = head + i * row_h
        body.append(f'<rect x="{x0}" y="{y}" width="{W - 2 * x0}" height="{row_h - 8}" rx="8" '
                    f'fill="{FILL_A if i % 2 == 0 else "#ffffff"}" stroke="{LINE}"/>')
        dl = _lines(_text(dim, f"row {i + 1} dimension", 50), 20, 2, f"row {i + 1} dimension")
        body.append(_tspans(dl, cols[0] + 16, y + 46 - 14 * (len(dl) - 1), 22, 28, INK, "bold"))
        for cx, val, nm in ((cols[1], a, "left"), (cols[2], b, "right")):
            vl = _lines(_text(val, f"row {i + 1} {nm}", 90), 36, 2, f"row {i + 1} {nm}")
            body.append(_tspans(vl, cx + 16, y + 46 - 14 * (len(vl) - 1), 22, 28, MUTED))
    return W, height, "".join(body)


def timeline(data):
    items = _rows(data, "items", 2, 6, 2, "[label, detail]")
    n = len(items)
    cell = (W - 80) // n
    chars = max(cell // 13, 10)
    height = 290
    body = [f'<line x1="40" y1="150" x2="{W - 40}" y2="150" stroke="{LINE}" stroke-width="4"/>']
    for i, (label, detail) in enumerate(items):
        cx = 40 + cell * i + cell // 2
        body.append(f'<circle cx="{cx}" cy="150" r="16" fill="{ACCENT}"/>')
        body.append(_tspans([str(i + 1)], cx, 157, 18, 0, "#ffffff", "bold", "middle"))
        body.append(_tspans(_lines(_text(label, f"item {i + 1} label", 40), chars, 3, f"item {i + 1} label"),
                            cx, 100 - 28 * (len(_lines(label, chars, 3, "label")) - 1), 24, 28, INK, "bold", "middle"))
        body.append(_tspans(_lines(_text(detail, f"item {i + 1} detail", 70), chars, 4, f"item {i + 1} detail"),
                            cx, 205, 21, 27, MUTED, "normal", "middle"))
    return W, height, "".join(body)


def layers(data):
    rows = _rows(data, "layers", 2, 6, 2, "[name, detail]")
    row_h = 92
    height = 40 + row_h * len(rows)
    body = []
    for i, (name, detail) in enumerate(rows):
        y = 20 + i * row_h
        inset = 40 + i * 24
        body.append(f'<rect x="{inset}" y="{y}" width="{W - 2 * inset}" height="{row_h - 14}" rx="10" '
                    f'fill="{FILL_B if i % 2 == 0 else FILL_A}" stroke="{LINE}"/>')
        nl = _lines(_text(name, f"layer {i + 1} name", 40), 24, 2, f"layer {i + 1} name")
        body.append(_tspans(nl, inset + 20, y + 47 - 14 * (len(nl) - 1), 24, 28, ACCENT, "bold"))
        dl = _lines(_text(detail, f"layer {i + 1} detail", 100), 52, 2, f"layer {i + 1} detail")
        body.append(_tspans(dl, inset + 340, y + 46 - 13 * (len(dl) - 1), 21, 27, MUTED))
    return W, height, "".join(body)


TEMPLATES = {"comparison": comparison, "timeline": timeline, "layers": layers}


def build_svg(template, data):
    fn = TEMPLATES.get(template)
    if fn is None:
        raise RenderError(f"svg: template must be one of {', '.join(TEMPLATES)}")
    w, h, body = fn(data)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="100%" height="100%" fill="#ffffff"/>{body}</svg>')


def render(visual, out_dir):
    src = visual["source"]
    svg = build_svg(src["template"], src["data"])
    vid = visual["id"]
    (out_dir / f"{vid}.svg").write_text(svg)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(out_dir / f"{vid}.png"))
    return image_result(out_dir, f"{vid}.png", f"{vid}.svg")
