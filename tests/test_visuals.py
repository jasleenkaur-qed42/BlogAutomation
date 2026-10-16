import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import checks  # noqa: E402
import visuals  # noqa: E402
from common import markdown_to_doc_text, markdown_to_html  # noqa: E402
from conftest import make_draft  # noqa: E402

BRIEF = {"primary_keyword": "design tokens", "target_words": {"min": 700, "max": 1100}}
FLOW = "```visual\ntype: flow\ntitle: T\nnodes: [A, B, C]\nedges: [[A, B], [A, C]]\n```\n"
BAR = "```visual\ntype: bar\ntitle: T\nlabels: [x, y]\nseries:\n  - {name: s, values: [1, 2]}\n```\n"
LINE = BAR.replace("bar", "line")
PNG = b"\x89PNG"


@pytest.mark.parametrize("block", [FLOW, BAR, LINE])
def test_each_type_renders_png(block):
    spec, err = visuals.parse_blocks(block)[0]
    assert err is None and visuals.render_png(spec).startswith(PNG)


@pytest.mark.parametrize("bad", [
    "type: pie\ntitle: T", "type: flow\ntitle: T\nnodes: [A]\nedges: []",
    "type: flow\ntitle: T\nnodes: [A, B]\nedges: [[A, Z]]", "type: flow\nnodes: [A, B]\nedges: [[A, B]]",
    "type: bar\ntitle: T\nlabels: [x, y]\nseries:\n  - {name: s, values: [1]}", "a: [unclosed"])
def test_invalid_specs_are_rejected(bad):
    spec, err = visuals.parse_blocks(f"```visual\n{bad}\n```\n")[0]
    assert spec is None and err


def _run(body, brief=BRIEF):
    return checks.run_checks(make_draft(body=body), brief, {}, check_links=False)


def test_visuals_hard_check_counts_valid_blocks():
    r = _run("# T\n\nIntro text.\n\n" + FLOW, {**BRIEF, "images": {"min": 0}})
    assert [h["id"] for h in r["hard"] if h["id"] == "visuals"] and r["signals"]["visual_count"] == 1
    assert not [h for h in _run("# T\n\nIntro.\n\n" + FLOW + "\n" + BAR + "\n" + BANNER)["hard"] if h["id"] == "visuals"]


def test_brief_can_opt_out_and_invalid_block_fails():
    assert not [h for h in _run("# T\n\nIntro.", {**BRIEF, "visuals": {"min": 0}, "images": {"min": 0}})["hard"] if h["id"] == "visuals"]
    r = _run("# T\n\nIntro.\n\n```visual\ntype: pie\ntitle: T\n```\n", {**BRIEF, "visuals": {"min": 0}, "images": {"min": 0}})
    assert any(h["id"] == "visuals" and "invalid" in h["detail"] for h in r["hard"])


def test_visuals_do_not_count_as_words_or_claims():
    plain = "# T\n\nOne two three.\n"
    assert checks.word_count(plain + FLOW) == checks.word_count(plain)
    assert not checks.verifiable_claims({}, plain + FLOW, {})


def test_html_embeds_png_and_doc_text_ignores_it():
    md = "# T\n\nBefore.\n\n" + FLOW + "*Figure 1: caption.*\n\nAfter.\n"
    html = markdown_to_html(md)
    assert '<img src="data:image/png;base64,' in html and "visual" not in html and "Figure 1" in html
    text = markdown_to_doc_text(md)
    assert "base64" not in text and "Figure 1: caption." in text and "T" in text.split() and "nodes" not in text


BANNER = "```visual\ntype: banner\ntitle: T\ntiles: [{label: Firebase, icon: flame}, {label: React Native, icon: atom}]\n```\n"
SCREEN = ("```visual\ntype: ui_screen\ntitle: T\nheading: Create database\nsidebar: [Auth, Database]\nactive: Database\n"
          "options:\n  - {label: Test mode, detail: Open for 30 days.}\nselected: Test mode\nbutton: Next\n```\n")
CARDS = "```visual\ntype: cards\ntitle: Projects\ncards:\n  - {title: Create, icon: plus}\n  - {title: App, subtitle: app-1}\n```\n"


@pytest.mark.parametrize("block", [BANNER, SCREEN, CARDS])
def test_scene_types_render_png(block):
    spec, err = visuals.parse_blocks(block)[0]
    assert err is None and visuals.render_png(spec).startswith(PNG)


@pytest.mark.parametrize("bad", [
    "type: banner\ntitle: T\ntiles: []", "type: banner\ntitle: T\ntiles: [{label: A, icon: nope}]",
    "type: ui_screen\ntitle: T\nheading: H", "type: ui_screen\ntitle: T\nheading: H\nsidebar: [A]\nselected: X",
    "type: cards\ntitle: T\ncards: [{title: A}]"])
def test_invalid_scenes_rejected(bad):
    spec, err = visuals.parse_blocks(f"```visual\n{bad}\n```\n")[0]
    assert spec is None and err


def test_topic_image_required_by_default_and_configurable():
    body = "# T\n\nIntro.\n\n" + FLOW + "\n" + BAR
    assert any("topic image" in h["detail"] for h in _run(body)["hard"])
    assert not any("topic image" in h["detail"] for h in _run(body + "\n" + BANNER)["hard"])
    assert not any("topic image" in h["detail"] for h in _run(body, {**BRIEF, "images": {"min": 0}})["hard"])


def test_code_block_gets_language_label():
    html = markdown_to_html("# T\n\n```js\nconst a = 1;\n```\n")
    assert ">JS<" in html and "const a = 1;" in html
