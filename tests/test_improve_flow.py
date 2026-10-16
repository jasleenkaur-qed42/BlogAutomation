import json
from pathlib import Path

import pytest
import blog
from conftest import make_draft, make_review, set_visuals
from improve_helpers import SOURCE_MD, ImproveDriver, revised


def ready(root, **kw):
    d = ImproveDriver(root, **kw)
    d.assess(make_review())
    return d


def test_writer_prompt_carries_goal_issues_and_rules_and_prefills_the_source(root):
    d = ImproveDriver(root)
    d.assess(make_review([{"id": "m1", "severity": "MEDIUM", "category": "tone", "anchor": "tokens are worth the effort",
                           "description": "tighten this"}], claim_checks=[
        {"claim": "X is 10x faster", "source": "https://x.example/p", "verdict": "UNSUPPORTED", "evidence": "none"}],
        factual=False))
    a = d.next()
    prompt = Path(a["prompt"]).read_text()
    assert a["action"] == "WRITE" and "## Improve mode" in prompt and "Goal: clarity, tighten" in prompt
    assert "tighten this" in prompt and "X is 10x faster" in prompt and "REMOVE" in prompt
    assert "Never invent" in prompt and "`changes`" in prompt and "## Untrusted content" in prompt
    assert "Keep the author's examples." in prompt                       # the brief notes
    assert Path(a["output"]).read_text() == SOURCE_MD                    # prefilled for in-place edits
    assert "already filled" in prompt


def test_preserve_lines_and_keep_reach_the_prompt(root):
    src = "import Demo from './Demo'\n\n" + SOURCE_MD
    d = ImproveDriver(root, source_text=src, keep=["the intro paragraph"])
    st = d.state()                                                       # a .md source has no preserve list; set one
    st["source"]["preserve"] = ["import Demo from './Demo'"]
    blog.save_state(root, st)
    d.assess(make_review())
    prompt = Path(d.next()["prompt"]).read_text()
    assert "Preserve these lines verbatim" in prompt and "import Demo from './Demo'" in prompt
    assert "the intro paragraph" in prompt


def test_changes_front_matter_is_required_in_improve_mode(root):
    d = ready(root)
    a = d.next()
    Path(a["output"]).write_text(make_draft(visuals=False))              # no `changes` key
    r = blog.cmd_submit_draft(root, d.run, a["output"])
    assert r["result"] == "MALFORMED" and "changes" in r["reason"]


def test_changes_may_be_empty_but_must_be_well_formed(root):
    d = ready(root)
    a = d.next()
    Path(a["output"]).write_text(make_draft(visuals=False, extra_fm="changes: [{section: only}]\n"))
    assert blog.cmd_submit_draft(root, d.run, a["output"])["result"] == "MALFORMED"   # reason is required


def test_create_mode_ignores_changes(driver):
    assert driver.write(make_draft())["result"] == "CHECKS_PASSED"


def test_improve_happy_path_to_delivery(root):
    d = ready(root)
    assert d.write(revised())["result"] == "CHECKS_PASSED"
    assert d.review(make_review())["result"] == "PASSED"
    rd = root / "runs" / d.run
    changes = (rd / "delivery" / "changes.md").read_text()
    assert "Frequently asked questions" in changes and "added the missing FAQ" in changes
    res = json.loads((rd / "result.json").read_text())
    assert res["mode"] == "improve" and res["changes"]["sections_changed"] >= 1
    a = blog.cmd_next(root, d.run)
    assert a["action"] == "CREATE_DOC" and (rd / "delivery" / "doc.md").exists()
    blog.cmd_record_delivery(root, d.run, "doc_created", "id1", "https://docs/x")
    text = Path(blog.cmd_next(root, d.run)["text_path"]).read_text()
    assert "Revised from" in text and "section(s) changed" in text and "changes.md" in text


def test_improve_skips_the_visual_stage_unless_asked(root):
    set_visuals(root, True)
    d = ready(root)
    d.write(revised())
    d.review(make_review())
    assert d.state()["state"] == "AI_REVIEW_PASSED"                      # not VISUALS_PLAN


def test_improve_with_visuals_requested_uses_the_stage(root):
    set_visuals(root, True)
    d = ready(root, visuals={"min": 2})
    d.write(revised())
    d.review(make_review())
    assert d.state()["state"] == "VISUALS_PLAN"


def test_source_that_already_passes_ends_with_no_doc(root):
    clean = make_draft(visuals=False)
    d = ready(root, source_text=clean)
    assert d.write(revised("[]"))["result"] == "CHECKS_PASSED"
    assert d.review(make_review())["result"] == "NO_CHANGES"
    st = d.state()
    assert st["state"] == "DONE_NO_CHANGES"
    a = blog.cmd_next(root, d.run)
    assert a["action"] == "DONE" and a["no_changes"] is True
    assert not (root / "runs" / d.run / "delivery" / "doc.md").exists()
    with pytest.raises(blog.BlogError):
        blog.cmd_record_delivery(root, d.run, "doc_created", "i", "https://docs/x")


def test_removed_claims_are_listed_in_the_change_log(root):
    d = ImproveDriver(root)
    d.assess(make_review(claim_checks=[{"claim": "X is 10x faster", "source": "https://x.example/p",
                                        "verdict": "UNSUPPORTED", "evidence": "none"}], factual=False))
    d.write(revised())
    d.review(make_review())
    changes = (root / "runs" / d.run / "delivery" / "changes.md").read_text()
    assert "X is 10x faster" in changes and "source link still in draft: no" in changes


def test_dry_run_improve_never_delivers(root):
    d = ImproveDriver(root, dry_run=True)
    d.assess(make_review())
    d.write(revised()); d.review(make_review())
    assert d.next()["action"] == "DRY_RUN_DELIVERY"
    assert (root / "runs" / d.run / "delivery" / "changes.md").exists()
