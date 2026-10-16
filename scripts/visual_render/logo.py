"""Official logos from the vendored simple-icons subset (CC0 files; trademarks belong to their owners). A logo
that is not vendored is never invented: the render fails and the plan falls back."""
import re

import cairosvg
from common import ROOT, load_json
from xml.sax.saxutils import escape

from . import RenderError, image_result

LOGO_DIR = ROOT / "assets" / "logos"
CELL, ICON, PAD = 200, 96, 40


def lookup(name, manifest):
    key = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    key = manifest["aliases"].get(key, key.replace(" ", ""))
    return manifest["icons"].get(key)


def render(visual, out_dir):
    manifest = load_json(LOGO_DIR / "manifest.json")
    names = visual["source"]["names"]
    found = [(n, lookup(n, manifest)) for n in names]
    missing = [n for n, e in found if e is None]
    if missing:
        raise RenderError(f"logo: not in assets/logos/manifest.json: {', '.join(missing)}")
    width = PAD * 2 + CELL * len(found)
    parts = []
    for i, (_, e) in enumerate(found):
        d = re.search(r'<path d="([^"]+)"', (LOGO_DIR / e["file"]).read_text())
        if not d:
            raise RenderError(f"logo: {e['file']} has no path")
        x = PAD + i * CELL + (CELL - ICON) // 2
        parts.append(f'<svg x="{x}" y="{PAD}" width="{ICON}" height="{ICON}" viewBox="0 0 24 24">'
                     f'<path fill="#{e["hex"]}" d="{d.group(1)}"/></svg>'
                     f'<text x="{PAD + i * CELL + CELL // 2}" y="{PAD + ICON + 44}" text-anchor="middle" '
                     f'font-family="Helvetica, Arial, sans-serif" font-size="24" fill="#202124">{escape(e["title"])}</text>')
    height = PAD * 2 + ICON + 44
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
           f'<rect width="100%" height="100%" fill="#ffffff"/>{"".join(parts)}</svg>')
    vid = visual["id"]
    (out_dir / f"{vid}.svg").write_text(svg)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(out_dir / f"{vid}.png"), output_width=max(width, 600))
    return image_result(out_dir, f"{vid}.png", f"{vid}.svg")
