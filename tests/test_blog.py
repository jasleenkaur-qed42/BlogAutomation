import json
from pathlib import Path

import pytest
from conftest import Driver, issue, make_draft, make_review
import blog

BAD = make_draft(title="Short")  # hard fail (title length)


def test_bad_brief_stops_before_run(root):
    (root / "briefs" / "bad.md").write_text("---\ntopic: x\n---\n")
    with pytest.raises(blog.BlogError):
        blog.cmd_init(root, root / "briefs" / "bad.md")


def test_out_of_order_rejected(driver):
    with pytest.raises(blog.BlogError):
        blog.cmd_submit_review(driver.root, driver.run, "x")
    with pytest.raises(blog.BlogError):  # before next
        blog.cmd_submit_draft(driver.root, driver.run, "x")
    a = driver.next()
    Path(a["output"]).write_text(make_draft())
    with pytest.raises(blog.BlogError):  # wrong path
        blog.cmd_submit_draft(driver.root, driver.run, str(driver.root / "other.md"))


def test_happy_path_and_delivery_states(driver):
    assert driver.write(make_draft())["result"] == "CHECKS_PASSED"
    assert driver.review(make_review([issue("m", "MEDIUM")]))["result"] == "PASSED"
    r = blog.cmd_next(driver.root, driver.run)
    assert r["action"] == "CREATE_DOC" and "[run:" in r["title"]
    with pytest.raises(blog.BlogError):
        blog.cmd_record_delivery(driver.root, driver.run, "slack_posted")
    blog.cmd_record_delivery(driver.root, driver.run, "doc_created", "id1", "https://docs/x")
    s = blog.cmd_next(driver.root, driver.run)
    assert s["action"] == "POST_SLACK"
    text = Path(s["text_path"]).read_text()
    assert "[AI draft]" not in text and "[run:" not in text and "https://docs/x" in text and "Still-open" not in text
    assert blog.cmd_record_delivery(driver.root, driver.run, "slack_failed", error="e")["state"] == "SLACK_NOTIFICATION_FAILED"
    assert blog.cmd_next(driver.root, driver.run)["action"] == "POST_SLACK"  # retry Slack only
    blog.cmd_record_delivery(driver.root, driver.run, "slack_posted")
    assert blog.cmd_next(driver.root, driver.run)["action"] == "DONE"


def test_drive_failure_no_slack(driver):
    driver.write(make_draft()); driver.review(make_review())
    blog.cmd_record_delivery(driver.root, driver.run, "doc_failed", error="x")
    a = blog.cmd_next(driver.root, driver.run)
    assert a["action"] == "CREATE_DOC" and a["search_title_first"]
    with pytest.raises(blog.BlogError):
        blog.cmd_record_delivery(driver.root, driver.run, "slack_posted")


def test_mechanical_retries_dont_consume_iteration(driver):
    r = driver.write(BAD)
    assert r["result"] == "HARD_FAIL" and driver.state()["iteration"] == 1
    assert "hard check failures" in Path(driver.next()["prompt"]).read_text().lower()
    driver.write(BAD)
    st = driver.state()
    assert st["iteration"] == 1 and st["mechanical_retries"] == 2
    r = driver.write(BAD)  # exceeds cap of 2 -> iteration fails
    assert r["result"] == "ITERATION_FAILED"
    st = driver.state()
    assert st["iteration"] == 2 and st["mechanical_retries"] == 0


def test_malformed_counter_independent_and_capped(driver):
    a = driver.next(); Path(a["output"]).write_text("garbage")
    assert blog.cmd_submit_draft(driver.root, driver.run, a["output"])["result"] == "MALFORMED"
    st = driver.state()
    assert st["iteration"] == 1 and st["mechanical_retries"] == 0 and st["malformed_retries"] == 1
    driver.write("garbage2") if False else None
    for _ in range(2):
        a = driver.next(); Path(a["output"]).write_text("garbage")
        r = blog.cmd_submit_draft(driver.root, driver.run, a["output"])
    assert r["result"] == "STOPPED"
    assert blog.cmd_next(driver.root, driver.run)["action"] == "STOP"


def test_malformed_review_and_checklist_without_issue(driver):
    driver.write(make_draft())
    a = driver.next(); Path(a["output"]).write_text("{not json")
    assert blog.cmd_submit_review(driver.root, driver.run, a["output"])["result"] == "MALFORMED"
    bad = make_review(); bad["checklist"][0].update({"pass": False, "issue_id": "ghost"})
    a = driver.next(); Path(a["output"]).write_text(json.dumps(bad))
    assert blog.cmd_submit_review(driver.root, driver.run, a["output"])["result"] == "MALFORMED"
    assert driver.state()["iteration"] == 1


def test_ungrounded_anchor_is_malformed_and_retried_with_the_reason(driver):
    driver.write(make_draft())
    a = driver.next()
    Path(a["output"]).write_text(json.dumps(make_review([issue("m", "MEDIUM", "tone", "a sentence the draft never had")])))
    r = blog.cmd_submit_review(driver.root, driver.run, a["output"])
    assert r["result"] == "MALFORMED" and "not quoted from the draft" in json.dumps(r)
    a = driver.next()
    Path(a["output"]).write_text(json.dumps(make_review([issue("m", "MEDIUM", "tone", "claim x")])))
    assert blog.cmd_submit_review(driver.root, driver.run, a["output"])["result"] == "PASSED"


def fail_iter(d, i):
    d.write(make_draft(slug=f"design-tokens-small-teams-{i}"))
    return d.review(make_review([issue(f"h{i}", "HIGH", "acc", f"anchor {i}")]))


def test_cap_best_draft_and_no_delivery(driver):
    for i in range(3):
        r = fail_iter(driver, i)
    assert r["result"] == "FAILED" and r["stop_reason"] == "iteration cap reached"
    a = blog.cmd_next(driver.root, driver.run)
    assert a["action"] == "STOP" and Path(a["best_draft"]).exists()
    assert not (driver.root / "runs" / driver.run / "delivery").exists()
    with pytest.raises(blog.BlogError):
        blog.cmd_record_delivery(driver.root, driver.run, "doc_created", doc_url="u")


def test_stagnation_stops_early(driver):
    driver.write(make_draft()); driver.review(make_review([issue("a", "HIGH", "acc", "same anchor")]))
    driver.write(make_draft()); r = driver.review(make_review([issue("b", "HIGH", "acc", "  Same   ANCHOR ")]))
    assert r["result"] == "FAILED" and "stagnation" in r["stop_reason"]


def test_best_draft_ranking_ties():
    e = lambda **k: {"hard_failures": [], "critical": 0, "high": 0, "failed_checklist": 0, "medium": 0, "low": 0, **k}
    assert blog.rank_key(e(failed_checklist=1)) > blog.rank_key(e(medium=3))
    assert blog.rank_key(e(failed_checklist=1, medium=0)) > blog.rank_key(e(medium=9, low=9))
    assert blog.rank_key(e(medium=2, low=1)) > blog.rank_key(e(medium=2))
    assert blog.rank_key(e(hard_failures=[1])) > blog.rank_key(e(critical=5))
    assert blog.rank_key(e(critical=1)) > blog.rank_key(e(high=9))
    assert blog.rank_key(e(high=1)) > blog.rank_key(e(failed_checklist=9))


def test_reviewer_prompt_isolation(driver):
    driver.write(make_draft())
    wp = (driver.root / "runs" / driver.run / "prompts" / "writer-1-1.md").read_text()
    rp = Path(driver.next()["prompt"]).read_text()
    assert "Writer task" not in rp and "prompts/writer" not in rp and "incoming/draft" not in rp
    for need in ("## Brief", "## Guidelines", "## Draft to review", "## Deterministic checks", "Previous issues"):
        assert need in rp
    assert wp not in rp


def test_writer_gets_previous_issues(driver):
    fail_iter(driver, 0)
    a = driver.next()
    p = Path(a["prompt"]).read_text()
    assert "anchor 0" in p and a["output"] in p  # the output file is prefilled with draft-1


def test_lock_blocks_concurrent_and_expires(root):
    d = Driver(root)
    with pytest.raises(blog.BlogError):
        blog.cmd_init(root, root / "briefs" / "sample.md")
    blog.cmd_init(root, root / "briefs" / "sample.md", force=True)
    lp = blog.lock_path(root, "briefs/sample.md")
    lock = json.loads(lp.read_text()); lock["ts"] -= 10**6; lp.write_text(json.dumps(lock))
    lock["run_id"] = d.run; lp.write_text(json.dumps(lock))
    blog.cmd_init(root, root / "briefs" / "sample.md")  # stale -> allowed


def test_resume_continues(driver):
    driver.write(make_draft())
    r = blog.cmd_resume(driver.root, driver.run)
    assert r["action"] == "REVIEW"


def test_dry_run_full_pipeline_no_delivery(root):
    d = Driver(root, dry_run=True)
    d.write(make_draft()); d.review(make_review())
    r = blog.cmd_next(root, d.run)
    assert r["action"] == "DRY_RUN_DELIVERY" and "nothing was created" in r["note"]
    assert d.state()["state"] == "DRY_RUN_COMPLETE"
    assert "dry-run.invalid" in (root / "runs" / d.run / "delivery" / "slack.txt").read_text()
    with pytest.raises(blog.BlogError):
        blog.cmd_record_delivery(root, d.run, "doc_created", doc_url="u")


def test_result_audit_fields(driver):
    driver.write(make_draft()); driver.review(make_review())
    res = json.loads((driver.root / "runs" / driver.run / "result.json").read_text())
    for k in ("iterations", "mechanical_retries", "hashes", "models", "hard_checks", "signals", "status"):
        assert k in res


# ---- allow-delivery ----
def ready(driver):
    driver.write(make_draft()); driver.review(make_review())
    return blog.cmd_next(driver.root, driver.run)


def cfg_of(driver):
    return json.loads((driver.root / "config" / "delivery.json").read_text())


def drive_input(driver, body=None, title=None):
    st = driver.state()
    body = body if body is not None else (driver.root / "runs" / driver.run / "delivery" / "doc.md").read_text()
    return {"tool_name": "mcp__blog-drive__create_doc",
            "tool_input": {"title": title or st["delivery"]["doc_title"], "content": body}}


def test_guard_drive(driver):
    ready(driver)
    ok = lambda i: blog.cmd_allow_delivery(driver.root, i)[0]
    assert ok(drive_input(driver))
    assert not ok(drive_input(driver, body="tampered"))
    assert not ok({"tool_name": "mcp__blog-drive__create_doc", "tool_input": {"title": "no marker"}})
    assert not ok({"tool_name": "mcp__blog-drive__share_file", "tool_input": {}})


def test_guard_blocks_failed_run_and_wrong_state(driver):
    for i in range(3):
        fail_iter(driver, i)
    st = driver.state()
    ti = {"tool_name": "mcp__blog-drive__create_doc", "tool_input": {"title": f"t [run:{driver.run}]"}}
    assert not blog.cmd_allow_delivery(driver.root, ti)[0]


def test_guard_slack(driver):
    ready(driver)
    blog.cmd_record_delivery(driver.root, driver.run, "doc_created", "i", "https://docs/x")
    a = blog.cmd_next(driver.root, driver.run)
    text = Path(a["text_path"]).read_text()
    good = {"tool_name": "mcp__blog-slack__post_message",
            "tool_input": {"channel_id": cfg_of(driver)["slack_channel_id"], "text": text, "run_id": driver.run}}
    assert blog.cmd_allow_delivery(driver.root, good)[0]
    bad = json.loads(json.dumps(good)); bad["tool_input"]["text"] = text + " @channel"
    assert not blog.cmd_allow_delivery(driver.root, bad)[0]


def test_guard_slack_before_doc_blocked(driver):
    ready(driver)
    ti = {"tool_name": "mcp__blog-slack__post_message",
          "tool_input": {"channel_id": cfg_of(driver)["slack_channel_id"], "text": "x", "run_id": driver.run}}
    assert not blog.cmd_allow_delivery(driver.root, ti)[0]


def test_cli_hook_exit_codes(driver):
    import subprocess, sys
    ready(driver)
    py = [sys.executable, str(Path(blog.__file__))]
    r = subprocess.run(py + ["allow-delivery"], input=json.dumps({"tool_name": "mcp__x__share_file", "tool_input": {}}),
                       capture_output=True, text=True)
    assert r.returncode == 2 and "BLOCKED" in r.stderr
    r = subprocess.run(py + ["allow-delivery"], input=json.dumps({"tool_name": "Read", "tool_input": {}}),
                       capture_output=True, text=True)
    assert r.returncode == 0


def test_guard_write_scoping():
    import guard_write
    r = guard_write.root
    assert guard_write.allowed(str(r / "runs" / "abc" / "incoming" / "draft-1-1.md"))
    assert not guard_write.allowed(str(r / "runs" / "abc" / "draft-1.md"))
    assert not guard_write.allowed(str(r / "runs" / "abc" / "incoming" / ".." / "state.json"))
    assert not guard_write.allowed(str(r / "scripts" / "blog.py"))


def test_verify_doc_accepts_rendered_google_doc_text(driver, tmp_path):
    from common import markdown_to_doc_text
    ready(driver)
    want = (driver.root / "runs" / driver.run / "delivery" / "doc.md").read_text()
    # Mimic Drive's text/plain export: BOM, CRLF, "* " bullets, no markdown syntax.
    exported = "﻿" + markdown_to_doc_text(want).replace("\n", "\r\n")
    f = tmp_path / "readback.txt"
    f.write_text(exported)
    assert blog.cmd_verify_doc(driver.root, driver.run, str(f)) == {"match": True}
    assert not driver.state()["needs_attention"]


def test_verify_doc_rejects_altered_text(driver, tmp_path):
    from common import markdown_to_doc_text
    ready(driver)
    want = (driver.root / "runs" / driver.run / "delivery" / "doc.md").read_text()
    f = tmp_path / "readback.txt"
    f.write_text(markdown_to_doc_text(want)[:-40])
    assert blog.cmd_verify_doc(driver.root, driver.run, str(f)) ["match"] is False
    assert driver.state()["needs_attention"]


def test_markdown_to_doc_text_strips_syntax():
    from common import doc_comparable_tokens, markdown_to_doc_text
    md = "---\ntitle: T\n---\n# Head\n\nA `code` and [link](https://x.y) with **bold**.\n\n- one\n- two\n\n```ts\nconst a = 1 < 2;\n```\n"
    toks = doc_comparable_tokens(markdown_to_doc_text(md))
    assert "title:" not in toks and "https://x.y" not in " ".join(toks)
    assert " ".join(toks) == "Head A code and link with bold. one two const a = 1 < 2;"
    assert doc_comparable_tokens("﻿Head\r\n* one\r\n* two") == ["Head", "one", "two"]


def test_doc_comparable_tokens_ignore_ordered_list_markers():
    from common import doc_comparable_tokens, markdown_to_doc_text
    assert doc_comparable_tokens("Head\r\n1. one\r\n2. two\r\n10. ten") == ["Head", "one", "two", "ten"]
    # Drive's text export numbers <ol> items; the HTML-derived expectation has no numbers.
    assert doc_comparable_tokens(markdown_to_doc_text("# H\n\n1. one\n2. two\n")) == ["H", "one", "two"]
    assert doc_comparable_tokens("v2. beta 3.5 1.") == ["v2.", "beta", "3.5"]


def test_verify_doc_accepts_ordered_list_markers_in_export(driver, tmp_path):
    from common import markdown_to_doc_text
    ready(driver)
    want = (driver.root / "runs" / driver.run / "delivery" / "doc.md").read_text()
    lines = markdown_to_doc_text(want).split("\n")
    numbered = [f"{i}. {line}" if line.strip() else line for i, line in enumerate(lines, 1)]
    f = tmp_path / "readback.txt"
    f.write_text("﻿" + "\r\n".join(numbered))
    assert blog.cmd_verify_doc(driver.root, driver.run, str(f)) == {"match": True}


def test_verify_doc_match_clears_needs_attention(driver, tmp_path):
    from common import markdown_to_doc_text
    ready(driver)
    want = (driver.root / "runs" / driver.run / "delivery" / "doc.md").read_text()
    f = tmp_path / "readback.txt"
    f.write_text("wrong")
    assert blog.cmd_verify_doc(driver.root, driver.run, str(f)) ["match"] is False
    assert driver.state()["needs_attention"]
    f.write_text(markdown_to_doc_text(want))
    assert blog.cmd_verify_doc(driver.root, driver.run, str(f)) == {"match": True}
    assert not driver.state()["needs_attention"]


def test_code_blocks_render_without_pre_and_keep_line_tokens():
    from common import doc_comparable_tokens, markdown_to_doc_text, markdown_to_html
    md = "# H\n\n```ts\nif (a < b) {\n  go();\n}\n```\n"
    html = markdown_to_html(md)
    assert "<pre" not in html and "<br>" in html and "&nbsp;&nbsp;go();" in html
    assert doc_comparable_tokens(markdown_to_doc_text(md)) == ["H", "if", "(a", "<", "b)", "{", "go();", "}"]


def test_dollar_signs_are_wrapped_but_text_is_unchanged():
    from common import markdown_to_doc_text, markdown_to_html
    md = "Cost $5 and $10.\n\n```\nget(/databases/$(database)/documents/rooms/$(roomId))\n```\n"
    html = markdown_to_html(md)
    assert "$(database)" not in html and html.count("<span") >= 4
    text = markdown_to_doc_text(md)
    assert "$(database)/documents/rooms/$(roomId)" in text and "$5 and $10" in text


def test_rejected_doc_returns_to_create_and_excludes_old_id(driver):
    driver.write(make_draft()); driver.review(make_review())
    blog.cmd_record_delivery(driver.root, driver.run, "doc_created", doc_id="old", doc_url="http://x")
    with pytest.raises(blog.BlogError):  # verify-doc has not flagged a mismatch yet
        blog.cmd_record_delivery(driver.root, driver.run, "doc_rejected")
    bad = driver.root / "bad.txt"
    bad.write_text("not the doc")
    assert blog.cmd_verify_doc(driver.root, driver.run, bad) ["match"] is False
    assert blog.cmd_record_delivery(driver.root, driver.run, "doc_rejected")["state"] == "DRIVE_DOC_FAILED"
    a = blog.cmd_next(driver.root, driver.run)
    assert a["action"] == "CREATE_DOC" and a["exclude_doc_ids"] == ["old"]
    assert not driver.state()["needs_attention"] and "doc_id" not in driver.state()["delivery"]


def test_unverified_claims_listed_for_removal():
    review = make_review(claim_checks=[
        {"claim": "Shaky stat", "source": "https://bad.example", "verdict": "UNSUPPORTED", "evidence": "no page"},
        {"claim": "Solid fact", "source": "https://ok.example", "verdict": "SUPPORTED", "evidence": "e"}])
    out = blog.unverified_claim_lines(review)
    assert "Shaky stat" in out and "https://bad.example" in out
    assert "Solid fact" not in out


def test_issue_lines_can_drop_low():
    import blog
    issues = [{"severity": "LOW", "id": "a", "category": "c", "description": "d", "anchor": "x"},
              {"severity": "HIGH", "id": "b", "category": "c", "description": "d", "anchor": "y"}]
    assert "(a)" in blog.issue_lines(issues)
    out = blog.issue_lines(issues, drop_low=True)
    assert "(a)" not in out and "(b)" in out
    assert blog.issue_lines([issues[0]], drop_low=True) == "(none)"


def test_revisions_prefill_output_with_previous_draft(driver):
    first = driver.next()
    assert not Path(first["output"]).exists()  # first draft is written from scratch
    assert "Edit calls" not in Path(first["prompt"]).read_text()
    driver.write(BAD)
    a = driver.next()  # mechanical retry: edit the failing draft in place
    assert Path(a["output"]).read_text() == BAD
    assert "Edit calls" in Path(a["prompt"]).read_text()
    good = make_draft()
    Path(a["output"]).write_text(good)
    blog.cmd_submit_draft(driver.root, driver.run, a["output"])
    driver.review(make_review(issues=[issue("i1", "HIGH"), issue("i2", "LOW")]))
    b = driver.next()  # iteration 2 starts from iteration 1's draft
    assert driver.state()["iteration"] == 2
    assert Path(b["output"]).read_text() == good
    prompt = Path(b["prompt"]).read_text()
    assert b["output"] in prompt and "(i1)" in prompt and "(i2)" not in prompt


FIXTURES = Path(__file__).parent / "fixtures" / "verify_doc"


def test_verify_doc_real_export_without_code_language_label():
    # Captured from a real run: Drive's export dropped the bold `YAML` label line above a code block.
    from common import doc_match
    md = (FIXTURES / "pr-review.doc.md").read_text()
    res = doc_match(md, (FIXTURES / "pr-review.readback.txt").read_text(), 0.99)
    assert res["match"] and res["coverage"] == 1.0 and res["missing"] == []


def test_doc_match_tolerates_nested_list_glyphs_quotes_and_pipes():
    from common import doc_match
    md = "# Head\n\n- one\n  - nested “quoted” item\n\n| a | b |\n|---|---|\n| x | y |\n"
    export = "Head\n● one\n   ○ nested \"quoted\" item\n a\tb\n x\ty\n"
    assert doc_match(md, export)["match"]
    assert doc_match("1. a\n    1. b\n", "1. a\n   a. b\n")["match"]


def test_doc_match_reports_missing_tokens_and_requires_headings_and_code():
    from common import doc_match
    md = "# Setup guide\n\n" + "word " * 400 + "\n\n```py\nx = compute(1)\n```\n"
    ok = "Setup guide\n" + "word " * 400 + "\nx = compute(1)\n"
    assert doc_match(md, ok, 0.99)["match"]
    # One wrong word in 400 is within coverage, but a wrong heading or code line is never tolerated.
    assert not doc_match(md, ok.replace("Setup guide", "Setup gide"), 0.99)["match"]
    bad_code = doc_match(md, ok.replace("compute(1)", "compute(2)"), 0.99)
    assert not bad_code["match"] and any("compute" in m for m in bad_code["missing"])
    assert not doc_match(md, ok[: len(ok) // 2], 0.99)["match"]


def test_code_language_label_is_formatting_not_verified_content():
    from common import doc_match, markdown_to_html
    md = "# H\n\n```yaml\nname: ai-review\non: push\n```\n"
    assert "<b>YAML</b>" in markdown_to_html(md)             # still shown in the Doc
    assert doc_match(md, "H\nname: ai-review\non: push")["match"]        # export without the label passes
    assert doc_match(md, "H\nYAML\nname: ai-review\non: push")["match"]  # export with the label passes
    assert not doc_match(md, "H\nYAML\nname: ai-review\non: pull")["match"]  # code content must round-trip
