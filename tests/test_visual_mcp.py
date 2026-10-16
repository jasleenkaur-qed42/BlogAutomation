"""ai_image visuals made by the image-generation MCP: blog.py hands out GENERATE_IMAGE, Claude calls the MCP,
`submit-image` validates and records the file. The shipped config/visuals.json is used as is (Mermaid on for flow diagrams)."""
import json
from pathlib import Path

import pytest
from PIL import Image

import blog
import visual_checks
import visual_stage
from conftest import Driver, make_draft, make_review, set_visuals
from test_visual_flow import NONE, PROMPT, SVG, plan, v


@pytest.fixture
def md(root):
    set_visuals(root, True, legacy=False)
    d = Driver(root)
    d.write(make_draft(visuals=False))
    d.review(make_review())
    return d


def submit(d, p):
    a = d.next()
    assert a["action"] == "PLAN_VISUALS", a
    Path(a["output"]).write_text(json.dumps(p))
    return blog.cmd_submit_visual_plan(d.root, d.run, a["output"])


def mcp_plan():
    return plan(v("v1", "One", "concept", "ai_image", PROMPT, 1),
                v("v2", "Two", "hero", "ai_image", {**PROMPT, "negative": "text"}, 2),
                v("v3", "Three", "compare", "svg", SVG, 3))


def make_png(path, size=(1376, 768)):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    im = Image.effect_noise(size, 60).convert("RGB")  # noisy, so it is big and not blank
    im.save(path, "PNG")


def test_flow_intents_use_mermaid_and_only_hero_concept_use_ai_image():
    cfg = visual_checks.load_config()
    assert cfg["image_backend"] == "mcp" and "_disabled_intents" not in cfg
    for intent in ("show_process", "show_architecture", "show_sequence", "show_relationships"):
        assert cfg["intents"][intent] == ["mermaid"]
    assert cfg["intents"]["hero"] == cfg["intents"]["concept"] == ["ai_image"]


def set_image_source(d, source):
    st = d.state()
    st["brief"].setdefault("visuals", {})["image_source"] = source
    blog.save_state(d.root, st)


def test_resolve_backend_prefers_the_brief_over_the_config(root):
    assert visual_stage.resolve_backend({}, root) == "mcp"  # config default
    assert visual_stage.resolve_backend({"visuals": {"min": 1}}, root) == "mcp"
    assert visual_stage.resolve_backend({"visuals": {"image_source": "prompt"}}, root) == "placeholder"
    assert visual_stage.resolve_backend({"visuals": {"image_source": "gemini"}}, root) == "mcp"


def test_image_source_prompt_gives_boxes_with_the_prompt_and_no_generation(md):
    set_image_source(md, "prompt")
    res = submit(md, mcp_plan())
    assert res["result"] == "VISUALS_READY" and res["image_prompts"] == 2, res
    rd = md.root / "runs" / md.run / "delivery"
    doc = (rd / "doc.md").read_text()
    assert doc.count("kind: placeholder") == 2 and "Flat editorial illustration" in doc
    assert (rd / "image-prompts.md").exists()
    assert md.next()["action"] == "CREATE_DOC"


def test_image_source_gemini_generates_even_if_config_says_placeholder(root):
    cfg = json.loads((root / "config" / "visuals.json").read_text())
    cfg["image_backend"], cfg["enabled"] = "placeholder", True
    (root / "config" / "visuals.json").write_text(json.dumps(cfg))
    d = Driver(root)
    d.write(make_draft(visuals=False))
    d.review(make_review())
    set_image_source(d, "gemini")
    assert submit(d, mcp_plan())["result"] == "HITL"
    assert d.next()["action"] == "GENERATE_IMAGE"


def test_brief_schema_rejects_an_unknown_image_source():
    import common
    assert common.schema_errors({"topic": "abc", "audience": "devs", "primary_keyword": "kw", "tone": "t",
                                 "target_words": {"min": 1, "max": 2}, "visuals": {"image_source": "dalle"}}, "brief")


def test_ai_image_is_rejected_for_flow_diagrams(md):
    p = plan(v("v1", "One", "show_process", "ai_image", PROMPT, 1), v("v2", "Two", "hero", "ai_image", PROMPT, 2))
    res = submit(md, p)
    assert res["result"] == "MALFORMED" and "must use mermaid" in " ".join(res["reason"])


def test_plan_waits_for_generation_then_continues(md):
    res = submit(md, mcp_plan())
    assert res["result"] == "HITL", res
    assert res["result"] == "HITL" and res["pending_images"] == ["v1", "v2"]
    a = md.next()
    assert a["action"] == "GENERATE_IMAGE" and a["id"] == "v1" and a["tool"] == "mcp__media-pipeline__create_asset"
    assert a["aspect_ratio"] == "16:9" and a["output_path"] == f"{md.run}/incoming/img-v1.png"
    assert a["prompt"].startswith("Flat editorial illustration")
    assert md.next()["prompt"] == a["prompt"]  # idempotent until submitted


def test_submit_image_records_asset_and_finishes(md):
    submit(md, mcp_plan())
    rd = md.root / "runs" / md.run
    for vid, last in (("v1", False), ("v2", True)):
        a = md.next()
        assert a["id"] == vid
        make_png(a["out_path"])
        res = blog.cmd_submit_image(md.root, md.run, vid, a["out_path"])
        assert (res["result"] == "VISUALS_READY") is last
    assert res["image_prompts"] == 0
    for vid in ("v1", "v2"):
        w, _ = Image.open(rd / "assets" / f"{vid}.png").size
        assert 600 <= w <= 1600 and (rd / "assets" / f"{vid}.png").stat().st_size <= 1500000
    doc = (rd / "delivery" / "doc.md").read_text()
    assert f"runs/{md.run}/assets/v1.png" in doc and "kind: placeholder" not in doc
    assert not (rd / "delivery" / "image-prompts.md").exists()
    assert md.next()["action"] == "CREATE_DOC"


def test_submit_image_rejects_wrong_path_state_and_garbage(md):
    with pytest.raises(blog.BlogError, match="out of order"):
        blog.cmd_submit_image(md.root, md.run, "v1", "x.png")
    submit(md, mcp_plan())
    a = md.next()
    with pytest.raises(blog.BlogError, match="unexpected path"):
        blog.cmd_submit_image(md.root, md.run, "v1", str(md.root / "other.png"))
    with pytest.raises(blog.BlogError, match="file not found"):
        blog.cmd_submit_image(md.root, md.run, "v1", a["out_path"])
    Path(a["out_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(a["out_path"]).write_text("not an image")
    with pytest.raises(blog.BlogError, match="not a readable image"):
        blog.cmd_submit_image(md.root, md.run, "v1", a["out_path"])
    with pytest.raises(blog.BlogError, match="out of order"):
        blog.cmd_submit_image(md.root, md.run, "v3", a["out_path"])  # v3 is not an ai_image


def test_jpeg_from_the_mcp_is_accepted_and_stored_as_png(md):
    submit(md, mcp_plan())
    a = md.next()
    jpg = Path(a["out_path"]).with_suffix(".jpg")
    Image.effect_noise((1376, 768), 60).convert("RGB").save(jpg, "JPEG")
    blog.cmd_submit_image(md.root, md.run, "v1", str(jpg))
    assert Image.open(md.root / "runs" / md.run / "assets" / "v1.png").format == "PNG"


def test_blank_generated_image_is_rejected(md):
    submit(md, mcp_plan())
    a = md.next()
    Image.new("RGB", (1200, 700), "white").save(a["out_path"])
    with pytest.raises(blog.BlogError, match="blank"):
        blog.cmd_submit_image(md.root, md.run, "v1", a["out_path"])
    assert not (md.root / "runs" / md.run / "assets" / "v1.png").exists()


def test_skip_drops_a_failed_generation(md):
    submit(md, mcp_plan())
    blog.cmd_skip_visual(md.root, md.run, "v1")
    a = md.next()
    assert a["id"] == "v2"
    make_png(a["out_path"])
    res = blog.cmd_submit_image(md.root, md.run, "v2", a["out_path"])
    assert res["result"] == "VISUALS_READY" and res["dropped"] == ["v1"]


def test_dry_run_never_generates_and_uses_boxes(root):
    set_visuals(root, True, legacy=False)
    d = Driver(root, dry_run=True)
    d.write(make_draft(visuals=False))
    d.review(make_review())
    res = submit(d, mcp_plan())
    assert res["result"] == "VISUALS_READY" and res["image_prompts"] == 2
    assert "kind: placeholder" in (root / "runs" / d.run / "delivery" / "doc.md").read_text()


def test_oversized_generated_image_is_shrunk_to_the_limits(tmp_path):
    src, dest = tmp_path / "in.png", tmp_path / "out.png"
    make_png(src, (1600, 1600))
    visual_stage.normalize_generated(src, dest, Path(__file__).resolve().parent.parent)
    a = visual_checks.load_config()["assets"]
    assert dest.stat().st_size <= a["max_bytes_each"] and Image.open(dest).width <= a["max_width"]


def test_launcher_confines_output_to_runs_and_needs_a_key(monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_servers"))
    import image_gen_server as g
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(g, "load_env", lambda: None)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        g.main()
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    called = {}
    monkeypatch.setattr(g.os, "execv", lambda exe, args: called.update(args=args))
    g.main()
    assert called["args"][1] == str(g.BUNDLE) and g.BUNDLE.exists()
    assert g.os.environ["IMAGE_OUTPUT_DIR"] == str(g.ROOT / "runs")
