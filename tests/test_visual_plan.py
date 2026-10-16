import copy
import json

import pytest

import visual_checks
from common import ROOT, split_front_matter

GOLDEN = ROOT / "evals" / "golden_visuals"
NAMES = ["conceptual", "ai-engineering", "rag", "integration"]


@pytest.fixture(autouse=True)
def legacy_policy(monkeypatch):
    """The golden plans use Mermaid and one placeholder image: validate them against the legacy policy."""
    from conftest import legacy_visual_config
    real = visual_checks.load_config
    monkeypatch.setattr(visual_checks, "load_config", lambda root=ROOT: legacy_visual_config(real(root)))


def load(name):
    _, body = split_front_matter((GOLDEN / f"{name}.md").read_text())
    plan = json.loads((GOLDEN / f"{name}.plan.json").read_text())
    expected = json.loads((GOLDEN / f"{name}.expected.json").read_text())
    return body, plan, expected


@pytest.mark.parametrize("name", NAMES)
def test_golden_plans_are_valid_and_match_expectations(name):
    body, plan, expected = load(name)
    assert visual_checks.plan_errors(plan, body) == []
    used = {v["renderer"] for v in plan["visuals"]}
    assert set(expected["required"]) <= used
    assert not used & set(expected["forbidden"])


def test_conceptual_blog_has_no_screenshot_and_integration_has_one():
    assert "screenshot" not in {v["renderer"] for v in load("conceptual")[1]["visuals"]}
    assert "screenshot" in {v["renderer"] for v in load("integration")[1]["visuals"]}


def errs(name, mutate, brief=None):
    body, plan, _ = load(name)
    plan = copy.deepcopy(plan)
    mutate(plan)
    return visual_checks.plan_errors(plan, body, brief)


def test_every_section_needs_a_visual_or_explicit_none():
    e = errs("rag", lambda p: p["sections"].clear())
    assert any("'Conclusion' has no visual" in x for x in e)


def test_none_section_may_not_also_have_a_visual():
    e = errs("rag", lambda p: p["sections"].append({"section": "How the pipeline fits together", "visual": "none", "reason": "skip"}))
    assert any("both planned and marked none" in x for x in e)


def test_unknown_section_rejected():
    e = errs("rag", lambda p: p["sections"].append({"section": "Invented", "visual": "none", "reason": "skip"}))
    assert any("unknown section 'Invented'" in x for x in e)


def test_intent_must_match_renderer_policy():
    def bad(p):
        p["visuals"][0]["renderer"] = "ai_image"
        p["visuals"][0]["source"] = {"prompt": "x" * 30, "aspect": "16:9"}
    assert any("must use mermaid, not 'ai_image'" in x for x in errs("rag", bad))


def test_unknown_intent_rejected():
    assert any("unknown intent" in x for x in errs("rag", lambda p: p["visuals"][0].update(intent="vibes")))


def test_screenshot_needs_a_real_url():
    e = errs("integration", lambda p: p["visuals"][0]["source"].update(url="not a url"))
    assert e and "url" in e[0]


def test_schema_rejects_missing_source_fields():
    assert errs("rag", lambda p: p["visuals"][0].update(source={"nope": 1}))


def test_captions_numbered_in_document_order():
    e = errs("conceptual", lambda p: p["visuals"][1].update(caption="Figure 3: out of order."))
    assert any("must start with 'Figure 2:'" in x for x in e)


def test_duplicate_ids_rejected():
    assert any("unique" in x for x in errs("rag", lambda p: p["visuals"][1].update(id="v1")))


def test_budget_limits_ai_images():
    def two_hero(p):
        extra = copy.deepcopy(p["visuals"][0])
        extra.update(id="v9", section="Conclusion", caption="Figure 4: another hero.")
        p["visuals"].append(extra)
        p["sections"].clear()
    assert any("2 ai_image visuals" in x for x in errs("conceptual", two_hero))


def test_figure_budget_scales_with_length():
    def many(p):
        for i in range(4, 8):
            extra = copy.deepcopy(p["visuals"][1])
            extra.update(id=f"v{i}", caption=f"Figure {i}: more.")
            p["visuals"].append(extra)
    assert any("figures for" in x for x in errs("conceptual", many))


def test_brief_floors_apply_after_the_plan():
    def none_plan(p):
        p["sections"].extend({"section": v["section"], "visual": "none", "reason": "skip"} for v in p["visuals"])
        p["visuals"].clear()
    assert errs("rag", none_plan) == []  # a post may legitimately have no visuals
    e = errs("rag", none_plan, brief={"visuals": {"min": 2}, "images": {"min": 1}})
    assert any("at least 2 visuals" in x for x in e) and any("at least 1 images" in x for x in e)


@pytest.mark.parametrize("prompt,ok", [
    ("Flat illustration of a developer at a desk, blue palette, no text, no logos", True),
    ("Flat illustration of a developer at a desk with a company logo on the laptop", False),
    ("Flat illustration of a developer at a desk, without any watermark", True),
    ("Flat illustration of a developer at a desk. No text, no logos, no watermarks, no real brand interfaces.", True),
    ("Flat illustration of a developer. Avoid text, logos or watermarks.", True),
    ("A developer at a desk. No people in the background. A laptop with a big logo on it.", False),
    ("short", False),
    ("x" * 700, False),
])
def test_image_prompt_rules(prompt, ok):
    e = errs("conceptual", lambda p: p["visuals"][0]["source"].update(prompt=prompt))
    assert (e == []) is ok


def test_aspect_must_be_allowed():
    assert errs("conceptual", lambda p: p["visuals"][0]["source"].update(aspect="21:9"))
