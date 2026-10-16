"""Deterministic checks for a visual plan: schema, section coverage, intent/renderer policy, budgets, captions,
image prompts. Policy lives in config/visuals.json; nothing here is decided by the planner."""
import math
import re
from pathlib import Path

import checks
import scenes
from common import ROOT, load_json, schema_errors

IMAGE_RENDERERS = ("ai_image", "screenshot", "scene")
NEGATION = re.compile(r"\b(no|not|without|avoid|never|don't|do not|exclude|excluding)\b", re.I)
FORBIDDEN_IN_PROMPT = ("logo", "logos", "watermark", "watermarks")


def load_config(root=ROOT):
    return load_json(Path(root) / "config" / "visuals.json")


def _prompt_errors(vid, source, cfg):
    p = cfg["image_prompt"]
    prompt = source.get("prompt", "")
    errs = []
    if not p["min_chars"] <= len(prompt.strip()) <= p["max_chars"]:
        errs.append(f"{vid}: image prompt must be {p['min_chars']}-{p['max_chars']} characters, got {len(prompt.strip())}")
    if source.get("aspect") not in p["aspects"]:
        errs.append(f"{vid}: aspect must be one of {', '.join(p['aspects'])}")
    for word in FORBIDDEN_IN_PROMPT:
        for m in re.finditer(rf"\b{word}\b", prompt, re.I):
            clause = re.split(r"[.;!?]", prompt[:m.start()])[-1]  # a negation earlier in the same sentence covers a list
            if not NEGATION.search(clause):
                errs.append(f"{vid}: image prompt must not ask for {word} (generated logos and text are unreliable)")
                break
    return errs


def plan_errors(plan, body, brief=None, root=ROOT):
    """Return a list of human-readable problems with `plan` for the draft `body` (empty list = valid)."""
    errs = schema_errors(plan, "visual_plan", root)
    if errs:
        return errs
    cfg = load_config(root)
    brief = brief or {}
    _, sections = checks._sections(body)
    names = [h.strip() for h, _ in sections]
    vis = plan["visuals"]

    ids = [v["id"] for v in vis]
    if len(set(ids)) != len(ids):
        errs.append("visual ids must be unique")

    covered = {v["section"].strip() for v in vis} | {s["section"].strip() for s in plan["sections"]}
    errs += [f"section {n!r} has no visual and no explicit 'none'" for n in names if n not in covered]
    errs += [f"unknown section {n!r} (not an H2 of the draft)" for n in sorted(covered) if n not in names]
    for s in plan["sections"]:
        if any(v["section"].strip() == s["section"].strip() for v in vis):
            errs.append(f"section {s['section']!r} is both planned and marked none")

    for v in vis:
        allowed = cfg["intents"].get(v["intent"])
        if allowed is None:
            errs.append(f"{v['id']}: unknown intent {v['intent']!r}")
        elif v["renderer"] not in allowed:
            errs.append(f"{v['id']}: intent {v['intent']!r} must use {' or '.join(allowed)}, not {v['renderer']!r}")
        if v["placement"]["after"] == "paragraph" and "n" not in v["placement"]:
            errs.append(f"{v['id']}: placement after a paragraph needs n")
        if v["renderer"] == "ai_image":
            errs += _prompt_errors(v["id"], v["source"], cfg)
        if v.get("fallback") == "scene":
            import visuals
            err = visuals.spec_error({**(v.get("fallback_scene") or {}), "title": v["title"]})
            if err or (v.get("fallback_scene") or {}).get("type") not in scenes.SCENE_TYPES:
                errs.append(f"{v['id']}: fallback 'scene' needs a valid fallback_scene ({err or 'type must be a scene type'})")

    order = {n: i for i, n in enumerate(names)}
    in_doc = sorted((v for v in vis if v["renderer"] != "code"), key=lambda v: order.get(v["section"].strip(), 0))
    for i, v in enumerate(in_doc, 1):
        if not re.match(rf"Figure {i}:", v["caption"]):
            errs.append(f"{v['id']}: caption must start with 'Figure {i}:' (captions are numbered in document order)")

    b = cfg["budget"]
    words = checks.word_count(body)
    figures = [v for v in vis if v["renderer"] != "code"]
    limit = max(b["min_allowed"], math.floor(b["max_per_1000_words"] * words / 1000))
    if len(figures) > limit:
        errs.append(f"{len(figures)} figures for {words} words; the budget is {limit}")
    for renderer, key in (("ai_image", "max_ai_image"), ("screenshot", "max_screenshot")):
        n = sum(v["renderer"] == renderer for v in vis)
        if n > b[key]:
            errs.append(f"{n} {renderer} visuals; the maximum is {b[key]}")

    ceiling = (brief.get("visuals") or {}).get("max")
    if ceiling is not None and len(vis) > ceiling:
        errs.append(f"brief allows at most {ceiling} visuals, the plan has {len(vis)}")
    floor_v = (brief.get("visuals") or {}).get("min", 0)
    floor_i = (brief.get("images") or {}).get("min", 0)
    if len(vis) < floor_v:
        errs.append(f"brief requires at least {floor_v} visuals, the plan has {len(vis)}")
    if sum(v["renderer"] in IMAGE_RENDERERS for v in vis) < floor_i:
        errs.append(f"brief requires at least {floor_i} images (ai_image, screenshot or scene)")
    return errs


def asset_errors(png_path, root=ROOT):
    """Problems with one rendered PNG: it must decode, be a sensible width and size, and not be blank."""
    from PIL import Image, ImageStat
    a = load_config(root)["assets"]
    path = Path(png_path)
    try:
        with Image.open(path) as im:
            im.load()
            w, h = im.size
            stddev = max(ImageStat.Stat(im.convert("L")).stddev)
    except Exception as e:
        return [f"{path.name}: not a readable image ({type(e).__name__})"]
    errs = []
    if not a["min_width"] <= w <= a["max_width"]:
        errs.append(f"{path.name}: width {w}px is outside {a['min_width']}-{a['max_width']}")
    if path.stat().st_size > a["max_bytes_each"]:
        errs.append(f"{path.name}: {path.stat().st_size} bytes exceeds {a['max_bytes_each']}")
    if stddev < a["min_pixel_stddev"]:
        errs.append(f"{path.name}: image looks blank")
    return errs


def total_size_errors(png_paths, root=ROOT):
    total = sum(Path(p).stat().st_size for p in png_paths)
    limit = load_config(root)["assets"]["max_bytes_total"]
    return [f"images total {total} bytes; the document limit is {limit}"] if total > limit else []
