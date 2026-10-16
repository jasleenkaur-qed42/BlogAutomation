"""Mermaid -> SVG + PNG through the pinned @mermaid-js/mermaid-cli, driving the locally installed Chrome."""
import json
import os
import shutil
import subprocess

from . import RenderError, image_result

VERSION = "12.0.0"
TIMEOUT = 180
CHROME_CANDIDATES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",)
_run = subprocess.run  # test seam


def chrome_path():
    for c in (os.environ.get("BLOG_CHROME"), *CHROME_CANDIDATES,
              shutil.which("google-chrome"), shutil.which("chromium")):
        if c and os.path.exists(c):
            return c
    raise RenderError("mermaid: no Chrome found (set BLOG_CHROME to a Chrome or Chromium binary)")


def render(visual, out_dir):
    if not shutil.which("npx"):
        raise RenderError("mermaid: npx (Node.js) is not installed")
    vid = visual["id"]
    src = out_dir / f"{vid}.mmd"
    src.write_text(visual["source"]["mermaid"].strip() + "\n")
    cfg = out_dir / f"{vid}.puppeteer.json"
    cfg.write_text(json.dumps({"executablePath": chrome_path(), "args": ["--no-sandbox"]}))
    env = {**os.environ, "PUPPETEER_SKIP_DOWNLOAD": "1"}
    for ext, extra in (("png", ["-b", "white", "-s", "2"]), ("svg", ["-b", "transparent"])):
        cmd = ["npx", "-y", f"@mermaid-js/mermaid-cli@{VERSION}", "-i", str(src), "-o", str(out_dir / f"{vid}.{ext}"),
               "-p", str(cfg), *extra]
        try:
            r = _run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=env)
        except subprocess.TimeoutExpired:
            raise RenderError(f"mermaid: render timed out after {TIMEOUT}s")
        if r.returncode != 0 or not (out_dir / f"{vid}.{ext}").exists():
            tail = " ".join((r.stderr or r.stdout or "").split())[-400:]
            raise RenderError(f"mermaid: syntax or render error: {tail}")
    src.unlink()
    cfg.unlink()
    return image_result(out_dir, f"{vid}.png", f"{vid}.svg")
