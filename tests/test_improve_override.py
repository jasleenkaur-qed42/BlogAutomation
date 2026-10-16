import json
from pathlib import Path

import pytest
import blog
import notify
from conftest import issue, make_draft, make_review, make_scores
from improve_helpers import ImproveDriver, revised

NOTE = "The 10x figure comes from our internal benchmark and the client wants it kept."
FAIL = make_review([{**issue("h1", "HIGH", "accuracy", "claim x", "unsupported claim"), "dimension": "technical_accuracy"}],
                   scores=make_scores(technical_accuracy=40), failing={"factual_accuracy": "h1"}, factual=False,
                   claim_checks=[{"claim": "X is 10x faster", "source": None, "verdict": "UNSUPPORTED", "evidence": "none"}])


def failed_run(root, **kw):
    d = ImproveDriver(root, **kw)
    d.assess(make_review())
    d.write(revised()); d.review(FAIL)          # iteration 1 fails
    d.write(revised()); d.review(FAIL)          # same blockers again: stagnation stops the run
    assert d.state()["state"] == "AI_REVIEW_FAILED"
    return d


def test_stop_action_says_whether_the_failure_is_approvable(root):
    d = failed_run(root)
    a = blog.cmd_next(root, d.run)
    assert a["action"] == "STOP" and a["approvable"] is True and "approve_blocked_reason" not in a


def test_approval_requires_a_human_note_improve_mode_and_the_failed_state(root, driver):
    d = failed_run(root)
    with pytest.raises(blog.BlogError, match="approved-by-human"):
        blog.cmd_approve_failing(root, d.run, NOTE, False)
    with pytest.raises(blog.BlogError, match="note"):
        blog.cmd_approve_failing(root, d.run, "ok", True)
    ok = ImproveDriver(root)
    with pytest.raises(blog.BlogError, match="AI_REVIEW_FAILED"):
        blog.cmd_approve_failing(root, ok.run, NOTE, True)
    with pytest.raises(blog.BlogError, match="improve"):
        blog.cmd_approve_failing(driver.root, driver.run, NOTE, True)   # a create-mode run


def test_approved_failing_draft_is_labelled_everywhere(root):
    d = failed_run(root)
    r = blog.cmd_approve_failing(root, d.run, NOTE, True)
    assert r["state"] == "AI_REVIEW_PASSED" and r["doc_title"].startswith("[FAILED GATE] ")
    rd = root / "runs" / d.run
    doc = (rd / "delivery" / "doc.md").read_text()
    assert "did not pass the automated review gate" in doc and "unsupported claim" in doc and "X is 10x faster" in doc
    assert doc.index("did not pass") < doc.index("# Why small teams")          # banner first, after the front matter
    st = d.state()
    assert st["gate_override"]["note"] == NOTE and st["gate_override"]["unverified_claims"] == ["X is 10x faster"]
    assert json.loads((rd / "result.json").read_text())["gate_override"]["note"] == NOTE
    assert (rd / "delivery" / "changes.md").exists()
    a = blog.cmd_next(root, d.run)
    assert a["action"] == "CREATE_DOC" and a["title"].startswith("[FAILED GATE] ") and "[run:" in a["title"]
    blog.cmd_record_delivery(root, d.run, "doc_created", "id1", "https://docs/x")
    slack = Path(blog.cmd_next(root, d.run)["text_path"]).read_text()
    assert "did not pass" in slack.lower() and "not approved or published" in slack.lower()
    assert "Passed AI review" not in slack


def test_hook_accepts_exactly_the_labelled_delivery(root):
    d = failed_run(root)
    blog.cmd_approve_failing(root, d.run, NOTE, True)
    a = blog.cmd_next(root, d.run)
    body = Path(a["body_path"]).read_text()
    ok, _ = blog.cmd_allow_delivery(root, {"tool_name": "mcp__blog-drive__create_doc",
                                           "tool_input": {"title": a["title"], "content": body}})
    assert ok
    ok, _ = blog.cmd_allow_delivery(root, {"tool_name": "mcp__blog-drive__create_doc",
                                           "tool_input": {"title": a["title"], "content": body.replace("did not pass", "passed")}})
    assert not ok


def test_failed_run_is_not_deliverable_without_approval(root):
    d = failed_run(root)
    ok, _ = blog.cmd_allow_delivery(root, {"tool_name": "mcp__blog-drive__create_doc",
                                           "tool_input": {"title": f"T [run:{d.run}]", "content": "x"}})
    assert not ok


def test_hard_check_failures_cannot_be_overridden(root):
    d = ImproveDriver(root)
    d.assess(make_review())
    bad = make_draft(visuals=False, title="Short", extra_fm="changes: []\n")      # title length: a hard check
    for _ in range(12):                    # 3 mechanical attempts per iteration, 3 iterations at most
        if d.state()["state"] != "IN_PROGRESS":
            break
        d.write(bad)
    assert d.state()["state"] == "AI_REVIEW_FAILED"
    a = blog.cmd_next(root, d.run)
    assert a["approvable"] is False and "hard" in a["approve_blocked_reason"]
    with pytest.raises(blog.BlogError, match="hard"):
        blog.cmd_approve_failing(root, d.run, NOTE, True)


def test_dry_run_cannot_be_approved(root):
    d = ImproveDriver(root, dry_run=True)
    d.assess(make_review())
    d.write(revised()); d.review(FAIL); d.write(revised()); d.review(FAIL)
    with pytest.raises(blog.BlogError, match="dry"):
        blog.cmd_approve_failing(root, d.run, NOTE, True)


def test_notify_helpers():
    assert notify.doc_title("My post", "r1", prefix="[FAILED GATE]") == "[FAILED GATE] My post [run:r1]"
    assert notify.doc_title("My post", "r1") == "My post [run:r1]"
    draft = "---\ntitle: T\n---\n# T\nbody\n"
    assert notify.render_doc(draft) == draft
    out = notify.render_doc(draft, banner="> BANNER")
    assert out == "---\ntitle: T\n---\n\n> BANNER\n\n# T\nbody\n"
    b = notify.override_banner([{"severity": "HIGH", "description": "bad *claim*"}],
                               [{"claim": "X is 10x faster"}], "client wants it")
    assert "[HIGH] bad claim" in b and "X is 10x faster" in b and "client wants it" in b and b.startswith("> ")
