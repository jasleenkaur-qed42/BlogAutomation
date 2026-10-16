"""Pure helpers for the visual stage that runs after a draft passes review. blog.py owns the state transitions;
this module builds the planner prompt, renders a plan to assets, and derives delivery/doc.md from the approved
draft plus the rendered visuals. The draft itself is never modified."""
import json
import re
from pathlib import Path

import yaml

import checks
import visual_checks
import visual_render
from common import FM_RE
from visual_render import RenderError

FIGURE_PREFIX = re.compile(r"^Figure \d+:\s*")


def enabled(root):
    return bool(visual_checks.load_config(root).get("enabled", True))


def planner_prompt(root, st, draft_path, errors=None, prior_plan=None, output=None):
    root = Path(root)
    cfg = visual_checks.load_config(root)
    body = split_body(Path(draft_path).read_text())
    _, sections = checks._sections(body)
    parts = ["# Visual planner task",
             "Decide what visual, if any, best explains each H2 section of the finished draft. Write ONE JSON file "
             "matching the schema below. Do not render anything and do not edit the draft.",
             "## Policy (enforced by code; a plan that breaks it is rejected)",
             "Intent -> allowed renderers:\n" + json.dumps(cfg["intents"], indent=1),
             "Budget: " + json.dumps(cfg["budget"]) + ". Image prompts: " + json.dumps(cfg["image_prompt"]),
             "## H2 sections that must each be covered, by a visual or by an entry in `sections` with a reason",
             "\n".join(f"- {h.strip()}" for h, _ in sections),
             "## Brief", json.dumps(st["brief"], indent=2),
             "## Final draft (read it; the text is not up for change)", f"Path: {draft_path}",
             "## Output schema", (root / "config" / "schemas" / "visual_plan.json").read_text(),
             "## Untrusted content (prompt-injection policy)", (root / "config" / "untrusted_content.md").read_text()]
    if prior_plan:
        parts += ["## Previous plan (fix it in place with Edit; do not start over)", f"Path: {output or prior_plan}"]
    if errors:
        parts += ["## Problems to fix", "\n".join(f"- {e}" for e in errors)]
    return "\n\n".join(parts)


def split_body(text):
    m = FM_RE.match(text)
    return m.group(2) if m else text


IMAGE_SOURCES = {"gemini": "mcp", "prompt": "placeholder"}


def resolve_backend(brief, root):
    """The brief's `visuals.image_source` (gemini or prompt) wins; otherwise the global `image_backend`."""
    src = ((brief or {}).get("visuals") or {}).get("image_source")
    return IMAGE_SOURCES.get(src) or visual_checks.load_config(root).get("image_backend", "placeholder")


def needs_generation(v, root, brief=None):
    """True when this visual is made by the image generation MCP (Claude calls it; blog.py never does)."""
    return v["renderer"] == "ai_image" and resolve_backend(brief, root) == "mcp"


def generation_prompt(v):
    src = v["source"]
    prompt = " ".join(src["prompt"].split())
    if src.get("negative"):
        prompt += f" Avoid: {' '.join(src['negative'].split())}"
    return prompt


def placeholder_result(v):
    """The IMAGE TO ADD box, used when an image is not generated (a dry run)."""
    return {"kind": "placeholder", "label": {"hero": "Hero", "concept": "Concept"}.get(v["intent"], "Figure"), "aspect": v["source"]["aspect"], "prompt": generation_prompt(v),
            "alt": v["alt"], "caption": v["caption"]}


def normalize_generated(path, dest, root):
    """Re-encode a generated image as a PNG that fits the asset limits (width, bytes), shrinking only as far as
    needed. Writes `dest`; returns nothing. Raises RenderError if it cannot be made to fit."""
    from PIL import Image
    a = visual_checks.load_config(root)["assets"]
    try:
        with Image.open(path) as im:
            im.load()
            im = im.convert("RGB")
    except Exception as e:
        raise RenderError(f"not a readable image ({type(e).__name__})")
    widths = [w for w in (a["max_width"], 1200, 1000, 800) if a["min_width"] <= w <= a["max_width"]]
    for i, w in enumerate(dict.fromkeys(widths)):
        out = im if im.width <= w else im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        out.save(dest, "PNG", optimize=True)
        if Path(dest).stat().st_size <= a["max_bytes_each"]:
            return
    out.quantize(256).save(dest, "PNG", optimize=True)  # last resort: a 256-colour palette
    if Path(dest).stat().st_size > a["max_bytes_each"]:
        raise RenderError(f"image is still {Path(dest).stat().st_size} bytes after shrinking")


def render_plan(plan, assets_dir, root, brief=None):
    """Render every non-screenshot visual. Returns (results, errors, pending_screenshots). Generated images are
    left to the MCP step (see needs_generation)."""
    results, errors, pending = {}, {}, []
    for v in plan["visuals"]:
        if v["renderer"] == "screenshot":
            pending.append(v["id"])
            continue
        if needs_generation(v, root, brief):
            continue
        try:
            res = visual_render.render(v, assets_dir)
            if res["kind"] == "image":
                bad = visual_checks.asset_errors(Path(assets_dir) / res["png"], root)
                if bad:
                    raise RenderError("; ".join(bad))
            results[v["id"]] = res
        except RenderError as e:
            errors[v["id"]] = str(e)
    return results, errors, pending


def fallback_visual(v):
    """A screenshot or failed visual with a `fallback_scene` becomes an honestly captioned illustration."""
    scene = v.get("fallback_scene")
    if v.get("fallback") != "scene" or not scene:
        return None
    prefix = FIGURE_PREFIX.match(v["caption"])
    return {**v, "renderer": "scene", "intent": "show_ui", "source": scene, "alt": f"Illustration of {v['title']}",
            "caption": f"{prefix.group(0) if prefix else 'Figure 1: '}Illustration of {v['title']}."}


def validate_screenshot(path, root):
    return visual_checks.asset_errors(path, root)


# ---------- deriving delivery/doc.md ----------
def _dump(d):
    return yaml.safe_dump(d, sort_keys=False, allow_unicode=True, width=100000).rstrip("\n")


def _caption_line(text):
    return "*" + text.replace("*", "").strip() + "*"


def visual_markdown(v, res, run_id):
    if res["kind"] == "placeholder":
        spec = {"type": "asset", "kind": "placeholder", "id": v["id"], "label": res["label"], "aspect": res["aspect"],
                "prompt": res["prompt"], "alt": v["alt"], "caption": v["caption"]}
        return "```visual\n" + _dump(spec) + "\n```"
    if res["kind"] == "code":
        return f"```{res['language']}\n{res['code']}\n```\n\n{_caption_line(v['caption'])}"
    spec = {"type": "asset", "path": f"runs/{run_id}/assets/{res['png']}", "title": v["title"], "alt": v["alt"]}
    return "```visual\n" + _dump(spec) + "\n```\n\n" + _caption_line(v["caption"])


def _split_blocks(text):
    """Blank-line separated blocks, keeping fenced code (which may contain blank lines) in one piece."""
    blocks, cur, fence = [], [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        if not line.strip() and not fence:
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def _is_paragraph(block):
    return not re.match(r"\s*(```|#|\||[-*+>]|\d+[.)]|<)", block)


def _insert(section_text, items, run_id):
    """Insert each (visual, result, markdown) at its placement within one H2 section chunk."""
    head, _, rest = section_text.partition("\n")
    blocks = _split_blocks(rest)
    for v, res, md in reversed(items):  # reversed: same-spot inserts then end up in plan order
        place = v["placement"]
        idx = 0
        if place["after"] == "paragraph":
            seen = 0
            idx = len(blocks)
            for i, b in enumerate(blocks):
                if _is_paragraph(b):
                    seen += 1
                    if seen == place["n"]:
                        idx = i + 1
                        break
        blocks.insert(idx, md)
    return head + "\n\n" + "\n\n".join(blocks) + "\n\n"


def apply_visuals(draft_text, plan, results, run_id, dropped=()):
    """Return (doc_md, image_prompts, report). `results` maps visual id -> render result. Captions are
    renumbered over what is actually kept, so a dropped figure leaves no gap."""
    m = FM_RE.match(draft_text)
    head, body = (draft_text[:m.start(2)], m.group(2)) if m else ("", draft_text)
    order = {h.strip(): i for i, h in enumerate(re.findall(r"(?m)^## (.+)$", body))}
    kept = sorted((dict(v) for v in plan["visuals"] if v["id"] in results), key=lambda v: order.get(v["section"].strip(), 0))
    n = 0
    for v in kept:  # renumber figures (not listings) in document order
        if results[v["id"]]["kind"] != "code":
            n += 1
            v["caption"] = FIGURE_PREFIX.sub("", v["caption"])
            v["caption"] = f"Figure {n}: {v['caption']}"
        else:
            v["caption"] = re.sub(r"^Listing \d+:\s*", "", v["caption"])
    listing = 0
    for v in kept:
        if results[v["id"]]["kind"] == "code":
            listing += 1
            v["caption"] = f"Listing {listing}: {v['caption']}"
    by_section = {}
    for v in kept:
        by_section.setdefault(v["section"].strip(), []).append((v, results[v["id"]], visual_markdown(v, results[v["id"]], run_id)))
    chunks = re.split(r"(?m)^(?=## )", body)
    out = [chunks[0]]
    for c in chunks[1:]:
        title = c.split("\n", 1)[0][3:].strip()
        out.append(_insert(c, by_section.pop(title, []), run_id) if title in by_section else c)
    doc = head + "".join(out)
    doc = re.sub(r"\n{3,}", "\n\n", doc).rstrip("\n") + "\n"
    prompts = [(v, results[v["id"]]) for v in kept if results[v["id"]]["kind"] == "placeholder"]
    report = [{"id": v["id"], "renderer": v["renderer"], "status": results[v["id"]]["kind"]} for v in kept]
    report += [{"id": i, "status": "dropped", "reason": r} for i, r in dict(dropped).items()]
    return doc, prompts, report


def image_prompts_md(run_id, prompts):
    lines = [f"# Image prompts for {run_id}", "",
             "Generate each image from its prompt, then replace the matching box in the Google Doc with it "
             "and delete the box text.", ""]
    for v, res in prompts:
        lines += [f"## {v['id']} · {res['label']} · {res['aspect']} (section: {v['section']})", "",
                  f"Prompt: {res['prompt']}", "", f"Alt text: {v['alt']}", "", f"Caption: {v['caption']}", ""]
    return "\n".join(lines)
