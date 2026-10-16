"""Visual renderers. `render(visual, out_dir)` turns one planned visual into an asset. The planner decides WHAT
to show; these modules decide HOW, deterministically. Returns one of:
  {"kind": "image", "png": <file name in out_dir>, "svg": <file name or None>, "w": int, "h": int}
  {"kind": "code", "language": str, "code": str}
  {"kind": "placeholder", "label": str, "aspect": str, "prompt": str, "alt": str, "caption": str}"""
from pathlib import Path


class RenderError(Exception):
    """A visual could not be rendered; the message is safe to show the planner for one retry."""


def png_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def image_result(out_dir, png, svg=None):
    w, h = png_size(Path(out_dir) / png)
    return {"kind": "image", "png": png, "svg": svg, "w": w, "h": h}


def render(visual, out_dir):
    from . import chart, code_block, image_prompt, logo, mermaid, scene, svg
    renderers = {"mermaid": mermaid, "svg": svg, "chart": chart, "scene": scene, "logo": logo,
                 "code": code_block, "ai_image": image_prompt}
    mod = renderers.get(visual["renderer"])
    if mod is None:
        raise RenderError(f"no renderer for {visual['renderer']!r} (screenshots are captured by a human-approved step)")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return mod.render(visual, out_dir)
