import json
import shutil
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC / "scripts"))
import blog  # noqa: E402

# Sentences that test reviews quote as issue anchors; a review is rejected when its anchors are not in the draft.
ANCHORS = " ".join(["The claim x here is a placeholder. Same anchor, reused. Intro."] + [f"Anchor {i}." for i in range(10)])
LONG = " ".join(["Design tokens keep a design system consistent across css variables and teams."] * 70)


VISUALS = (
    "```visual\ntype: banner\ntitle: Design tokens\ntiles: [{label: Tokens, icon: code}]\n```\n"
    "*Figure 0: Illustration.*\n\n"
    "```visual\ntype: flow\ntitle: Token flow\nnodes: [Design, Tokens, Code]\nedges: [[Design, Tokens], [Tokens, Code]]\n```\n"
    "*Figure 1: From design to code.*\n\n"
    "```visual\ntype: bar\ntitle: Setup effort\nlabels: [A, B]\nseries:\n  - {name: hours, values: [3, 5]}\n```\n"
    "*Figure 2: Effort.*\n\n")
SECTION = " ".join(["Tokens name each design decision once so that every component can reuse it."] * 3)
FAQ = "\n\n".join(f"### Question number {w}?\nTokens answer it with one named decision." for w in "abcde")
DIMS = {"technical_accuracy": 20, "technical_depth": 15, "practical_usefulness": 15, "originality": 15,
        "structure_clarity": 10, "examples_implementation": 10, "tradeoffs_limitations": 5,
        "references_support": 5, "seo": 3, "audience_fit": 2}


def make_draft(title="Why small teams should adopt design tokens today", slug="design-tokens-small-teams",
               desc=None, body=None, extra_fm="", visuals=True):
    desc = desc or ("A practical guide to design tokens, design system basics and css variables for small "
                    "front-end teams who want consistency.")
    body = body if body is not None else (
        f"# {title}\n\nSmall front-end teams often wonder whether design tokens are worth the effort, and this "
        f"article explains when they are.\n\n## One\n{LONG} {ANCHORS}\n\n{VISUALS if visuals else ''}## Two\n{SECTION}\n\n"
        f"## Three\nCSS variables and design system. {SECTION} See [docs](https://example.com/ok).\n\n"
        f"## Frequently asked questions\n{FAQ}\n\n"
        "## Conclusion\nTokens are a small investment that pays back quickly for small teams.\n\n"
        "## References\n- [docs](https://example.com/ok)\n")
    return (f"---\ntitle: {title}\nslug: {slug}\ndescription: {desc}\nkeywords: [design tokens]\n"
            f"claims: []\n{extra_fm}---\n{body}")


def make_scores(**over):
    return {d: {"score": over.get(d, 85), "evidence": "e"} for d in DIMS}


def make_review(issues=(), failing=(), scores=None, factual=True, claim_checks=(), **extra):
    items = json.loads((SRC / "config" / "rules.json").read_text())["required_checklist"]
    cl = []
    for it in items:
        c = {"item": it, "pass": it not in failing, "evidence": "e"}
        if it in failing:
            c["issue_id"] = failing[it]
        cl.append(c)
    return {"checklist": cl, "issues": list(issues), "summary": "Summary text.",
            "scores": scores if scores is not None else make_scores(),
            "factual_correctness": {"passed": factual, "evidence": "e"}, "claim_checks": list(claim_checks), **extra}


def issue(id_="i1", sev="HIGH", cat="accuracy", anchor="claim x", desc="bad"):
    return {"id": id_, "severity": sev, "category": cat, "anchor": anchor, "description": desc}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOG_NO_LINKS", "1")
    shutil.copytree(SRC / "config", tmp_path / "config")
    (tmp_path / ".claude" / "skills" / "review").mkdir(parents=True)
    shutil.copy(SRC / ".claude" / "skills" / "review" / "SKILL.md", tmp_path / ".claude" / "skills" / "review" / "SKILL.md")
    (tmp_path / "briefs").mkdir()
    shutil.copy(SRC / "briefs" / "sample.md", tmp_path / "briefs" / "sample.md")
    (tmp_path / "runs").mkdir()
    set_visuals(tmp_path, False, legacy=False)  # the text-only delivery path; visual-stage tests turn it on with `vroot`
    return tmp_path


def legacy_visual_config(cfg):
    """The pre-MCP policy: Mermaid diagrams and IMAGE TO ADD placeholders (config/visuals.json keeps both)."""
    cfg["image_backend"] = "placeholder"
    cfg["intents"].update(cfg.get("_disabled_intents", {}))
    cfg["budget"]["max_ai_image"] = 1
    cfg["image_prompt"]["max_chars"] = 600
    return cfg


def set_visuals(root, enabled, legacy=True):
    cfg = json.loads((Path(root) / "config" / "visuals.json").read_text())
    cfg["enabled"] = enabled
    if legacy:
        legacy_visual_config(cfg)
    (Path(root) / "config" / "visuals.json").write_text(json.dumps(cfg))


@pytest.fixture
def vroot(root):
    set_visuals(root, True)
    return root


class Driver:
    def __init__(self, root, dry_run=False):
        self.root = root
        self.run = blog.cmd_init(root, root / "briefs" / "sample.md", dry_run)["run_id"]

    def next(self):
        return blog.cmd_next(self.root, self.run)

    def write(self, text):
        a = self.next()
        assert a["action"] == "WRITE", a
        Path(a["output"]).write_text(text)
        return blog.cmd_submit_draft(self.root, self.run, a["output"])

    def review(self, review):
        a = self.next()
        assert a["action"] == "REVIEW", a
        Path(a["output"]).write_text(json.dumps(review))
        return blog.cmd_submit_review(self.root, self.run, a["output"])

    def state(self):
        return blog.load_state(self.root, self.run)


@pytest.fixture
def driver(root):
    return Driver(root)
