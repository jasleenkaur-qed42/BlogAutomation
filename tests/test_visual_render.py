import json
import os
import subprocess

import pytest
from PIL import Image

import visual_checks
import visual_render
from common import ROOT
from visual_render import RenderError, mermaid

GOLDEN = ROOT / "evals" / "golden_visuals"


def visual(name, vid):
    plan = json.loads((GOLDEN / f"{name}.plan.json").read_text())
    return next(v for v in plan["visuals"] if v["id"] == vid)


@pytest.mark.parametrize("name,vid", [("conceptual", "v3"), ("ai-engineering", "v2"), ("integration", "v3")])
def test_image_renderers_make_valid_pngs(tmp_path, name, vid):
    r = visual_render.render(visual(name, vid), tmp_path)
    assert r["kind"] == "image" and (tmp_path / r["png"]).read_bytes().startswith(b"\x89PNG")
    assert visual_checks.asset_errors(tmp_path / r["png"]) == []
    assert (tmp_path / r["svg"]).read_text().startswith("<svg")


def test_layers_template_and_chart_and_scene(tmp_path):
    layers = {"id": "v1", "renderer": "svg", "source": {"template": "layers", "data": {
        "layers": [["Presentation", "Pages"], ["Platform", "Hosting and auth"]]}}}
    chart = {"id": "v2", "renderer": "chart", "title": "Time per stage", "source": {
        "type": "bar", "labels": ["Before", "After"], "series": [{"name": "Hours", "values": [8, 3]}]}}
    scene = {"id": "v3", "renderer": "scene", "title": "Console", "source": {
        "type": "cards", "cards": [{"title": "One"}, {"title": "Two"}]}}
    for v in (layers, chart, scene):
        r = visual_render.render(v, tmp_path)
        assert visual_checks.asset_errors(tmp_path / r["png"]) == [], v["renderer"]


def test_svg_text_is_escaped_and_overflow_is_an_error(tmp_path):
    ok = {"id": "v1", "renderer": "svg", "source": {"template": "comparison", "data": {
        "left": "A <b>", "right": "B & C", "rows": [["Cost", "<script>x</script>", "5 > 3"]]}}}
    r = visual_render.render(ok, tmp_path)
    svg = (tmp_path / r["svg"]).read_text()
    assert "<script>" not in svg and "&lt;script&gt;" in svg and "B &amp; C" in svg
    long = {"id": "v2", "renderer": "svg", "source": {"template": "timeline", "data": {
        "items": [["A very long label that cannot possibly fit in its cell " * 2, "d"], ["B", "d"]]}}}
    with pytest.raises(RenderError, match="characters"):
        visual_render.render(long, tmp_path)


@pytest.mark.parametrize("source,msg", [
    ({"template": "nope", "data": {}}, "template must be"),
    ({"template": "comparison", "data": {"left": "L", "right": "R", "rows": []}}, "rows must be"),
    ({"template": "timeline", "data": {"items": [["only", "one"]]}}, "items must be"),
])
def test_bad_svg_specs_have_clear_errors(tmp_path, source, msg):
    with pytest.raises(RenderError, match=msg):
        visual_render.render({"id": "v1", "renderer": "svg", "source": source}, tmp_path)


def test_logo_uses_vendored_assets_and_never_invents_one(tmp_path):
    ok = {"id": "v1", "renderer": "logo", "source": {"names": ["React Native", "Firebase"]}}
    assert visual_render.render(ok, tmp_path)["kind"] == "image"
    with pytest.raises(RenderError, match="not in assets/logos/manifest.json: Acme Corp"):
        visual_render.render({"id": "v2", "renderer": "logo", "source": {"names": ["Firebase", "Acme Corp"]}}, tmp_path)


def test_code_renderer_returns_a_fenced_block_spec(tmp_path):
    v = {"id": "v1", "renderer": "code", "source": {"language": "python", "code": "def retrieve(q):\n    return index.search(q)\n"}}
    r = visual_render.render(v, tmp_path)
    assert r == {"kind": "code", "language": "python", "code": "def retrieve(q):\n    return index.search(q)"}
    bad = {"id": "v1", "renderer": "code", "source": {"language": "md", "code": "```\nx\n```"}}
    with pytest.raises(RenderError, match="fence"):
        visual_render.render(bad, tmp_path)


def test_ai_image_makes_a_placeholder_with_no_network_or_files(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network used"))
    r = visual_render.render(visual("conceptual", "v1"), tmp_path)
    assert r["kind"] == "placeholder" and r["label"] == "Hero" and r["aspect"] == "16:9"
    assert r["prompt"].startswith("Flat editorial illustration") and list(tmp_path.iterdir()) == []


def test_ai_image_only_for_hero_and_concept(tmp_path):
    v = {**visual("conceptual", "v1"), "intent": "show_process"}
    with pytest.raises(RenderError, match="hero and concept"):
        visual_render.render(v, tmp_path)


def test_screenshots_are_not_rendered_automatically(tmp_path):
    with pytest.raises(RenderError, match="screenshots"):
        visual_render.render(visual("integration", "v1"), tmp_path)


def test_mermaid_runs_pinned_cli_with_local_chrome(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw["env"]))
        out = cmd[cmd.index("-o") + 1]
        Image.new("RGB", (800, 200), "white").save(out, "PNG") if out.endswith(".png") else open(out, "w").write("<svg/>")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(mermaid, "_run", fake_run)
    monkeypatch.setattr(mermaid, "chrome_path", lambda: "/chrome")
    r = visual_render.render(visual("rag", "v1"), tmp_path)
    assert r["png"] == "v1.png" and r["svg"] == "v1.svg" and r["w"] == 800
    assert all(f"@mermaid-js/mermaid-cli@{mermaid.VERSION}" in c for c, _ in calls)
    assert all(e["PUPPETEER_SKIP_DOWNLOAD"] == "1" for _, e in calls)
    assert not (tmp_path / "v1.mmd").exists() and not (tmp_path / "v1.puppeteer.json").exists()


def test_mermaid_syntax_error_is_reported_for_a_planner_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(mermaid, "_run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, "", "Parse error on line 2: Expecting 'SEMI'"))
    monkeypatch.setattr(mermaid, "chrome_path", lambda: "/chrome")
    with pytest.raises(RenderError, match="Parse error on line 2"):
        visual_render.render(visual("rag", "v1"), tmp_path)


@pytest.mark.skipif(not os.environ.get("BLOG_RUN_SLOW"), reason="set BLOG_RUN_SLOW=1 to run real mermaid-cli")
def test_mermaid_real_render(tmp_path):
    r = visual_render.render(visual("rag", "v1"), tmp_path)
    assert visual_checks.asset_errors(tmp_path / r["png"]) == []


def test_asset_checks_reject_blank_tiny_and_unreadable(tmp_path):
    Image.new("RGB", (900, 300), "white").save(tmp_path / "blank.png")
    Image.new("RGB", (200, 100), "black").save(tmp_path / "tiny.png")
    (tmp_path / "bad.png").write_bytes(b"not a png")
    assert any("blank" in e for e in visual_checks.asset_errors(tmp_path / "blank.png"))
    assert any("width 200px" in e for e in visual_checks.asset_errors(tmp_path / "tiny.png"))
    assert any("not a readable image" in e for e in visual_checks.asset_errors(tmp_path / "bad.png"))
    assert visual_checks.total_size_errors([tmp_path / "blank.png"]) == []
