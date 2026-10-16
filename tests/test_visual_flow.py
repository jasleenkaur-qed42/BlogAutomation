import copy
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import blog
from common import markdown_to_doc_text, markdown_to_html
from conftest import Driver, make_draft, make_review
from visual_render import mermaid


def fake_mermaid(fail=False):
    def run(cmd, **kw):
        if fail:
            return subprocess.CompletedProcess(cmd, 1, "", "Parse error on line 2")
        out = cmd[cmd.index("-o") + 1]
        if out.endswith(".png"):
            im = Image.new("RGB", (900, 300), "white")
            ImageDraw.Draw(im).rectangle((100, 80, 500, 200), fill="#1a73e8")
            im.save(out, "PNG")
        else:
            Path(out).write_text("<svg/>")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


@pytest.fixture(autouse=True)
def mermaid_ok(monkeypatch):
    monkeypatch.setattr(mermaid, "_run", fake_mermaid())
    monkeypatch.setattr(mermaid, "chrome_path", lambda: "/chrome")


def v(id_, section, intent, renderer, source, n, **kw):
    return {"id": id_, "section": section, "intent": intent, "renderer": renderer, "placement": {"after": "heading"},
            "title": f"Visual {id_}", "alt": f"Alt text for {id_}", "caption": f"Figure {n}: Caption for {id_}.",
            "source": source, "rationale": "because", **kw}


MERMAID = {"mermaid": "flowchart LR\n  A --> B\n  B --> C"}
PROMPT = {"prompt": "Flat editorial illustration of a small team around a laptop, blue palette, no text", "aspect": "16:9"}
SVG = {"template": "comparison", "data": {"left": "Before", "right": "After", "rows": [["Setup", "Slow", "Fast"]]}}
SCREEN = {"url": "https://example.com/console", "steps": ["Open"], "requires_login": True, "redact_note": "hide email"}
SCENE = {"type": "ui_screen", "heading": "Sign-in method", "options": [{"label": "Email", "detail": "Enabled"}]}
NONE = [{"section": "Frequently asked questions", "visual": "none", "reason": "prose"},
        {"section": "Conclusion", "visual": "none", "reason": "prose"}, {"section": "References", "visual": "none", "reason": "list"}]


def plan(*visuals, sections=NONE):
    covered = {x["section"] for x in visuals}
    extra = [{"section": n, "visual": "none", "reason": "prose"} for n in ("One", "Two", "Three") if n not in covered]
    return {"visuals": list(visuals), "sections": [*extra, *sections]}


def good_plan():
    return plan(v("v1", "One", "show_process", "mermaid", MERMAID, 1),
                v("v2", "Two", "hero", "ai_image", PROMPT, 2),
                v("v3", "Three", "compare", "svg", SVG, 3))


@pytest.fixture
def vd(vroot):
    d = Driver(vroot)
    d.write(make_draft(visuals=False))
    d.review(make_review())
    return d


def submit(d, p):
    a = d.next()
    assert a["action"] == "PLAN_VISUALS", a
    Path(a["output"]).write_text(p if isinstance(p, str) else json.dumps(p))
    return blog.cmd_submit_visual_plan(d.root, d.run, a["output"])


def rd(d):
    return d.root / "runs" / d.run


def test_review_pass_enters_visual_stage_then_delivery(vd):
    assert vd.state()["state"] == "VISUALS_PLAN"
    a = vd.next()
    prompt = Path(a["prompt"]).read_text()
    assert a["action"] == "PLAN_VISUALS" and "- One" in prompt and "- Three" in prompt and "hero" in prompt
    res = submit(vd, good_plan())
    assert res["result"] == "VISUALS_READY" and res["image_prompts"] == 1
    assert vd.state()["state"] == "AI_REVIEW_PASSED"
    assert vd.next()["action"] == "CREATE_DOC"


def test_doc_md_is_derived_and_the_draft_is_untouched(vd):
    draft_before = (rd(vd) / "draft-1.md").read_text()
    submit(vd, good_plan())
    doc = (rd(vd) / "delivery" / "doc.md").read_text()
    assert (rd(vd) / "draft-1.md").read_text() == draft_before
    assert f"path: runs/{vd.run}/assets/v1.png" in doc and "*Figure 1: Caption for v1.*" in doc
    assert "kind: placeholder" in doc and "*Figure 3: Caption for v3.*" in doc
    assert doc.index("Visual v1") < doc.index("## Two") < doc.index("kind: placeholder") < doc.index("## Three")
    assert (rd(vd) / "assets" / "v1.png").exists() and (rd(vd) / "assets" / "v3.png").exists()
    assert "IMAGE TO ADD" not in doc  # the box text is rendered from the spec, not stored in the Markdown


def test_image_prompt_placeholder_reaches_the_doc_and_the_sidecar(vd):
    submit(vd, good_plan())
    html = markdown_to_html((rd(vd) / "delivery" / "doc.md").read_text(), root=vd.root)
    assert html.count("data:image/png;base64,") >= 2
    assert "[IMAGE TO ADD" in html and "Flat editorial illustration" in html and "#fff8e1" in html
    side = (rd(vd) / "delivery" / "image-prompts.md").read_text()
    assert "## v2 · Hero · 16:9 (section: Two)" in side and "Flat editorial illustration" in side


def test_verify_doc_passes_with_visuals_and_placeholder_text(vd, tmp_path):
    submit(vd, good_plan())
    doc = (rd(vd) / "delivery" / "doc.md").read_text()
    exported = "﻿" + markdown_to_doc_text(doc)
    assert "IMAGE TO ADD" in exported and "Alt text for v1" in exported
    f = tmp_path / "readback.txt"
    f.write_text(exported)
    assert blog.cmd_verify_doc(vd.root, vd.run, str(f)) == {"match": True}
    f.write_text(exported.replace("Flat editorial illustration", "Different"))
    assert blog.cmd_verify_doc(vd.root, vd.run, str(f))["match"] is False


def test_allow_delivery_accepts_the_derived_doc_exactly(vd):
    submit(vd, good_plan())
    doc = (rd(vd) / "delivery" / "doc.md").read_text()
    title = blog.load_state(vd.root, vd.run)["delivery"]["doc_title"]
    hook = {"tool_name": "mcp__blog-drive__create_doc", "tool_input": {"title": title, "content": doc}}
    assert blog.cmd_allow_delivery(vd.root, hook)[0]
    hook["tool_input"]["content"] = doc.replace("Alt text for v1", "Tampered")
    assert not blog.cmd_allow_delivery(vd.root, hook)[0]


def test_slack_text_reports_image_prompts(vd):
    submit(vd, good_plan())
    blog.cmd_record_delivery(vd.root, vd.run, "doc_created", doc_id="d", doc_url="http://x")
    assert "1 image prompt(s) to fill in the Doc" in blog.render_slack(vd.root, vd.state()).read_text()


def test_invalid_plan_is_malformed_then_stops(vd):
    bad = good_plan()
    bad["sections"] = []
    r = submit(vd, bad)
    assert r["result"] == "MALFORMED" and any("'Conclusion' has no visual" in e for e in r["reason"])
    assert "Conclusion" in Path(vd.next()["prompt"]).read_text()  # the planner sees what to fix
    assert submit(vd, "not json")["result"] == "MALFORMED"
    assert submit(vd, bad)["result"] == "STOPPED" and vd.state()["state"] == "STOPPED"


def test_render_error_gets_one_planner_retry_with_the_error(vd, monkeypatch):
    monkeypatch.setattr(mermaid, "_run", fake_mermaid(fail=True))
    r = submit(vd, good_plan())
    assert r["result"] == "RENDER_ERRORS" and "Parse error on line 2" in r["errors"][0]
    a = vd.next()
    assert "Parse error on line 2" in Path(a["prompt"]).read_text()
    assert json.loads(Path(a["output"]).read_text()) == good_plan()  # prefilled for in-place fixes
    monkeypatch.setattr(mermaid, "_run", fake_mermaid())
    Path(a["output"]).write_text(json.dumps(good_plan()))
    assert blog.cmd_submit_visual_plan(vd.root, vd.run, a["output"])["result"] == "VISUALS_READY"


def test_optional_visual_that_keeps_failing_is_dropped_and_figures_renumber(vd, monkeypatch):
    monkeypatch.setattr(mermaid, "_run", fake_mermaid(fail=True))
    submit(vd, good_plan())
    a = vd.next()
    Path(a["output"]).write_text(Path(a["output"]).read_text())
    r = blog.cmd_submit_visual_plan(vd.root, vd.run, a["output"])
    assert r["result"] == "VISUALS_READY" and r["dropped"] == ["v1"]
    doc = (rd(vd) / "delivery" / "doc.md").read_text()
    assert "Caption for v1" not in doc and "Figure 1: Caption for v2" in doc and "Figure 2: Caption for v3" in doc
    assert json.loads((rd(vd) / "visual-report.json").read_text())["visuals"][-1]["status"] == "dropped"
    assert json.loads((rd(vd) / "result.json").read_text())["visuals"]["dropped"] == ["v1"]


def test_required_visual_failure_waits_for_a_human(vd, monkeypatch):
    p = good_plan()
    p["visuals"][0]["required"] = True
    monkeypatch.setattr(mermaid, "_run", fake_mermaid(fail=True))
    submit(vd, p)
    a = vd.next()
    r = blog.cmd_submit_visual_plan(vd.root, vd.run, a["output"])
    assert r["result"] == "HITL" and "v1" in r["blocked"] and vd.state()["state"] == "VISUALS_HITL"
    d = vd.next()
    assert d["action"] == "VISUAL_DECISION" and d["id"] == "v1" and "Parse error" in d["reason"]
    assert blog.cmd_skip_visual(vd.root, vd.run, "v1")["result"] == "VISUALS_READY"
    assert vd.state()["state"] == "AI_REVIEW_PASSED"


def shot(path, size=(1280, 720)):
    im = Image.new("RGB", size, "white")
    ImageDraw.Draw(im).rectangle((100, 100, 700, 400), fill="#34a853")
    im.save(path, "PNG")


def screenshot_plan(**kw):  # the sample brief asks for at least 2 visuals
    return plan(v("v1", "One", "show_ui", "screenshot", SCREEN, 1, **kw), v("v2", "Two", "compare", "svg", SVG, 2))


def test_screenshot_requires_human_approval_and_a_valid_png(vd):
    r = submit(vd, screenshot_plan())
    assert r["result"] == "HITL" and r["pending_screenshots"] == ["v1"]
    a = vd.next()
    assert a["action"] == "CAPTURE_SCREENSHOT" and a["requires_login"] and a["url"] == "https://example.com/console"
    shot(a["out_path"])
    with pytest.raises(blog.BlogError, match="approved-by-human"):
        blog.cmd_submit_screenshot(vd.root, vd.run, "v1", a["out_path"], approved=False)
    assert vd.state()["state"] == "VISUALS_HITL"
    other = vd.root / "elsewhere.png"
    shot(other)
    with pytest.raises(blog.BlogError, match="unexpected path"):
        blog.cmd_submit_screenshot(vd.root, vd.run, "v1", other, approved=True)
    Path(a["out_path"]).write_bytes(b"not an image")
    with pytest.raises(blog.BlogError, match="not a readable image"):
        blog.cmd_submit_screenshot(vd.root, vd.run, "v1", a["out_path"], approved=True)
    shot(a["out_path"], size=(300, 200))
    with pytest.raises(blog.BlogError, match="width 300px"):
        blog.cmd_submit_screenshot(vd.root, vd.run, "v1", a["out_path"], approved=True)
    shot(a["out_path"])
    assert blog.cmd_submit_screenshot(vd.root, vd.run, "v1", a["out_path"], approved=True)["result"] == "VISUALS_READY"
    events = json.loads((rd(vd) / "visual-report.json").read_text())["events"]
    assert events[0]["event"] == "screenshot_approved_by_human"
    assert "Caption for v1" in (rd(vd) / "delivery" / "doc.md").read_text()


def test_declined_screenshot_falls_back_to_an_honest_illustration(vd):
    submit(vd, screenshot_plan(fallback="scene", fallback_scene=SCENE))
    assert vd.next()["has_fallback"]
    assert blog.cmd_skip_visual(vd.root, vd.run, "v1")["result"] == "VISUALS_READY"
    doc = (rd(vd) / "delivery" / "doc.md").read_text()
    assert "*Figure 1: Illustration of Visual v1.*" in doc and "Caption for v1" not in doc
    assert "Alt text for v1" not in doc and "alt: Illustration of Visual v1" in doc


def test_declined_screenshot_without_fallback_is_dropped(vd):
    submit(vd, screenshot_plan())
    r = blog.cmd_skip_visual(vd.root, vd.run, "v1")
    assert r["result"] == "VISUALS_READY" and r["dropped"] == ["v1"]


def test_skip_visual_out_of_order_is_rejected(vd):
    with pytest.raises(blog.BlogError, match="not waiting for a decision"):
        blog.cmd_skip_visual(vd.root, vd.run, "v1")


def test_dry_run_never_waits_for_a_screenshot(vroot):
    d = Driver(vroot, dry_run=True)
    d.write(make_draft(visuals=False))
    d.review(make_review())
    r = submit(d, screenshot_plan(fallback="scene", fallback_scene=SCENE))
    assert r["result"] == "VISUALS_READY" and d.state()["state"] == "AI_REVIEW_PASSED"
    assert d.next()["action"] == "DRY_RUN_DELIVERY"


def test_asset_blocks_cannot_escape_the_runs_assets_folder(vd):
    submit(vd, good_plan())
    for bad in ("../../etc/passwd", f"runs/{vd.run}/draft-1.md", "/etc/passwd", f"runs/{vd.run}/assets/../state.json"):
        md = f"```visual\ntype: asset\npath: {bad}\ntitle: t\nalt: a\n```\n"
        with pytest.raises(ValueError, match="not allowed"):
            markdown_to_html(md, root=vd.root)


def test_writers_cannot_author_asset_blocks(root):
    import checks
    BRIEF = blog.parse_brief(Path(__file__).resolve().parent.parent / "briefs" / "sample.md")[0]
    body = ("# T\n\n## One\n" + "word " * 30 + "\n\n```visual\ntype: asset\npath: runs/x/assets/v1.png\ntitle: t\nalt: a\n```\n")
    res = checks.run_checks(make_draft(body=body), BRIEF, {}, check_links=False)
    assert any(h["id"] == "visuals" for h in res["hard"])


def test_visuals_can_be_turned_off(root):
    d = Driver(root)
    d.write(make_draft())
    d.review(make_review())
    assert d.state()["state"] == "AI_REVIEW_PASSED"


def test_writer_visual_blocks_are_rejected_when_the_planner_runs(vroot):
    d = Driver(vroot)
    r = d.write(make_draft())  # the default draft carries legacy visual blocks
    assert any(h["id"] == "visuals" and "visual planner" in h["detail"] for h in d.state()["last_checks"]["hard"])
    assert "visual planner" in Path(d.next()["prompt"]).read_text() or "Do not write `visual` blocks" in Path(d.next()["prompt"]).read_text()


def test_brief_visual_ceiling_applies_to_the_plan(vd):
    st = vd.state()
    st["brief"]["visuals"] = {"min": 0, "max": 1}
    blog.save_state(vd.root, st)
    r = submit(vd, good_plan())
    assert r["result"] == "MALFORMED" and any("at most 1 visuals" in e for e in r["reason"])


def test_code_visual_is_inserted_as_a_fenced_block_with_a_listing_caption(vd):
    code = {"language": "python", "code": "def retrieve(q):\n    return index.search(q)"}
    c = v("v2", "Two", "show_code", "code", code, 1, caption="Listing 1: A retrieval function.")
    c["placement"] = {"after": "paragraph", "n": 1}
    submit(vd, plan(v("v1", "One", "show_process", "mermaid", MERMAID, 1), c))
    doc = (rd(vd) / "delivery" / "doc.md").read_text()
    assert "```python\ndef retrieve(q):\n    return index.search(q)\n```\n\n*Listing 1: A retrieval function.*" in doc
    assert doc.index("## Two") < doc.index("def retrieve") < doc.index("## Three")
    assert "Figure 1: Caption for v1" in doc


def test_cli_subcommands_drive_the_visual_stage(vd, capsys):
    root, run = vd.root, vd.run
    assert blog.main(["next", run], root=root) == 0
    a = json.loads(capsys.readouterr().out)
    assert a["action"] == "PLAN_VISUALS"
    Path(a["output"]).write_text(json.dumps(screenshot_plan(fallback="scene", fallback_scene=SCENE)))
    assert blog.main(["submit-visual-plan", run, a["output"]], root=root) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "HITL"
    assert blog.main(["next", run], root=root) == 0
    shot_action = json.loads(capsys.readouterr().out)
    shot(shot_action["out_path"])
    assert blog.main(["submit-screenshot", run, "v1", shot_action["out_path"]], root=root) == 1  # no --approved-by-human
    assert "approved-by-human" in capsys.readouterr().err
    assert blog.main(["submit-screenshot", run, "v1", shot_action["out_path"], "--approved-by-human"], root=root) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "VISUALS_READY"
    assert blog.main(["skip-visual", run, "v1"], root=root) == 1
