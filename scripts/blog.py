#!/usr/bin/env python3
"""State-machine authority for the blog workflow. Never launches Claude, never calls connectors.

Commands: init, next, classify, approve-failing, submit-source, submit-assessment, submit-draft, submit-review, status, render-doc, render-slack,
          allow-delivery, record-delivery, verify-doc, resume
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assess as assess_mod  # noqa: E402
import claim_verify  # noqa: E402
import checks as checks_mod  # noqa: E402
import diff_report  # noqa: E402
import notify  # noqa: E402
import source_import  # noqa: E402
import visual_checks  # noqa: E402
import visual_stage  # noqa: E402
from common import (  # noqa: E402
    ROOT, doc_match, load_json, schema_errors, split_front_matter, write_json,
)
from validate import (BAD_CLAIM, checklist_reference_problems, claim_fingerprint, config_errors,  # noqa: E402
                      consistency_section, review_problems, rubric_section, validate)

DRIVE_OK = {"AI_REVIEW_PASSED", "DRIVE_DOC_FAILED"}
SLACK_OK = {"DRIVE_DOC_CREATED", "SLACK_NOTIFICATION_FAILED"}
VISUAL_STATES = {"VISUALS_PLAN", "VISUALS_HITL"}
TERMINAL = {"AI_REVIEW_FAILED", "DELIVERED", "STOPPED", "DRY_RUN_COMPLETE", "DONE_NO_CHANGES"}
DRY_DOC_URL = "https://dry-run.invalid/doc"
RUN_MARK_RE = re.compile(r"\[run:([A-Za-z0-9_-]+)\]")


class BlogError(Exception):
    pass


# ---------- paths / io ----------
def runs_dir(root):
    return Path(root) / "runs"


def run_path(root, run_id):
    return runs_dir(root) / run_id


def load_state(root, run_id):
    p = run_path(root, run_id) / "state.json"
    if not p.exists():
        raise BlogError(f"unknown run {run_id}")
    return load_json(p)


def save_state(root, st):
    write_json(run_path(root, st["run_id"]) / "state.json", st)


def thresholds(root):
    th = load_json(Path(root) / "config" / "thresholds.json")
    errs = config_errors(thresholds=th)
    if errs:
        raise BlogError("invalid config/thresholds.json: " + "; ".join(errs))
    return th


def rules(root):
    rl = load_json(Path(root) / "config" / "rules.json")
    errs = config_errors(rules=rl)
    if errs:
        raise BlogError("invalid config/rules.json: " + "; ".join(errs))
    return rl


def out(obj):
    print(json.dumps(obj, indent=2))


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


# ---------- locks ----------
def lock_path(root, brief_path):
    return runs_dir(root) / ".locks" / (Path(brief_path).stem + ".lock")


def acquire_lock(root, brief_path, run_id, force=False):
    lp, ttl = lock_path(root, brief_path), thresholds(root)["lock_ttl_seconds"]
    if lp.exists():
        cur = load_json(lp)
        if cur["run_id"] != run_id and time.time() - cur["ts"] < ttl and not force:
            raise BlogError(f"brief is locked by run {cur['run_id']} (use --force to override)")
    write_json(lp, {"run_id": run_id, "pid": os.getpid(), "ts": time.time(),
                    "session": os.environ.get("CLAUDE_SESSION_ID", "")})


def release_lock(root, st):
    lp = lock_path(root, st["brief_path"])
    if lp.exists() and load_json(lp).get("run_id") == st["run_id"]:
        lp.unlink()


def set_state(root, st, new):
    st["state"] = new
    if new in TERMINAL:
        release_lock(root, st)
    save_state(root, st)


# ---------- init ----------
def parse_brief(path):
    fm, notes = split_front_matter(Path(path).read_text())
    return fm, notes


def brief_errors(brief, root):
    """Schema errors plus the rules JSON schema cannot express: target_words is required to create, and an improve
    brief needs a source and a goal (its word range is derived from the source when absent)."""
    errs = schema_errors(brief, "brief", root)
    mode = brief.get("mode", "create")
    if mode == "create" and "target_words" not in brief:
        errs.append("<root>: 'target_words' is a required property")
    if mode == "improve":
        if not brief.get("source"):
            errs.append("source: required when mode is improve")
        if not brief.get("goal"):
            errs.append("goal: required when mode is improve")
    tw = brief.get("target_words")
    if not errs and tw and tw["min"] > tw["max"]:
        errs.append("target_words: min > max")
    return errs


def store_source(root, st, imported, original=None):
    """Write the normalized source (and a byte copy of the original file) into the run."""
    rd = run_path(root, st["run_id"])
    (rd / "source").mkdir(exist_ok=True)
    if original:
        shutil.copyfile(original, rd / "source" / f"original{imported['ext']}")
    (rd / "source.md").write_text(imported["markdown"])
    st["source"].update(sha256=imported["sha256"], dropped=imported["dropped"], preserve=imported["preserve"])
    write_json(rd / "source" / "import_notes.json", {"dropped": imported["dropped"], "preserve": imported["preserve"]})


def cmd_init(root, brief_path, dry_run=False, force=False):
    brief_path = Path(brief_path)
    try:
        brief, notes = parse_brief(brief_path)
    except (ValueError, OSError) as e:
        raise BlogError(f"brief invalid: {e}")
    errs = brief_errors(brief, root)
    if errs:
        raise BlogError("brief invalid: " + "; ".join(errs))
    improve = brief.get("mode") == "improve"
    imported = None
    if improve:  # import before the lock so an unusable source leaves no run and no lock behind
        src = brief["source"]
        try:
            if src["kind"] == "local":
                imported = source_import.import_file(src["ref"])
            elif not source_import.parse_gdoc_url(src["ref"]):
                raise source_import.SourceError("not a Google Docs URL (docs.google.com/document/d/<id>)")
        except source_import.SourceError as e:
            raise BlogError(f"source invalid: {e}")
        brief.setdefault("visuals", {"min": 0})
        brief.setdefault("images", {"min": 0})
        if imported and "target_words" not in brief:
            brief["target_words"] = source_import.derive_target_words(imported["markdown"])
    slug = re.sub(r"[^a-z0-9]+", "-", brief_path.stem.lower()).strip("-")
    run_id = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{slug}"
    n = 1
    while run_path(root, run_id).exists():
        n += 1
        run_id = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{slug}-{n}"
    acquire_lock(root, brief_path, run_id, force)
    st = {"run_id": run_id, "brief_path": str(brief_path), "brief": brief, "brief_notes": notes,
          "dry_run": dry_run, "state": "IN_PROGRESS", "phase": "WRITE", "iteration": 1,
          "draft_submissions": 0, "review_submissions": 0,
          "mechanical_retries": 0, "malformed_retries": 0, "total_mechanical_retries": 0,
          "expected_path": None, "history": [], "last_checks": None, "delivery": {}, "needs_attention": False}
    (run_path(root, run_id) / "incoming").mkdir(parents=True)
    (run_path(root, run_id) / "prompts").mkdir()
    if improve:
        st.update(mode="improve", phase="ASSESS" if imported else "FETCH_SOURCE", assess_submissions=0,
                  source={"kind": src["kind"], "ref": src["ref"]})
        if imported:
            store_source(root, st, imported, original=src["ref"])
    save_state(root, st)
    return st


# ---------- prompts ----------
def issue_lines(issues, drop_low=False):
    if drop_low:
        issues = [i for i in issues if i["severity"] != "LOW"]
    return "\n".join(f"- [{i['severity']}] ({i['id']}) {i['category']}: {i['description']}\n  anchor: {i['anchor']!r}"
                     for i in issues) or "(none)"


def fingerprint(issue):
    return hashlib.sha1((issue["category"] + "|" + norm(issue["anchor"]).lower()).encode()).hexdigest()[:12]


def prior_review(root, st):
    for n in range(st["iteration"] - 1, 0, -1):
        p = run_path(root, st["run_id"]) / f"review-{n}.json"
        if p.exists():
            return n, load_json(p)
    return None, None


def unverified_claim_lines(review):
    return "\n".join(f"- [{c['verdict']}] {c['claim']}\n  source: {c.get('source') or '(none)'}\n  evidence: {c['evidence']}"
                     for c in review.get("claim_checks") or [] if c.get("verdict") in BAD_CLAIM)


def revision_source(root, st):
    """The draft a revision starts from: the current draft after a mechanical failure, else the previous iteration's."""
    rd = run_path(root, st["run_id"])
    if st["mechanical_retries"] and st["last_checks"] and st["last_checks"]["hard"]:
        return rd / f"draft-{st['iteration']}.md"
    if st["iteration"] > 1:
        return rd / f"draft-{st['iteration'] - 1}.md"
    if st.get("mode") == "improve":
        return rd / "source.md"  # iteration 1 starts from the author's draft
    return None


EDIT_NOTE = ("The output file is already filled with this draft. Read it once, then change it in place with targeted "
             "Edit calls. Do not rewrite the whole file with Write unless most of it must change.")


def flagged_words_line(root):
    return ", ".join(rules(root).get("flagged_words", []))


def untrusted_content_section(root):
    """Shared prompt-injection policy: retrieved text is data, never instructions."""
    return ["## Untrusted content (prompt-injection policy)", (Path(root) / "config" / "untrusted_content.md").read_text()]


def writer_standards(root):
    """QED42 writing standards plus the flagged-word list (the same list the deterministic check enforces)."""
    return ["## QED42 writing standards (the reviewer applies these checks)",
            (Path(root) / "config" / "qed42_writing.md").read_text(),
            "Flagged words (never use, in any form; code rejects them): " + flagged_words_line(root)]


def review_skill_text(root):
    """Body of the QED42 review skill, the source of truth for the reviewer's checks."""
    text = (Path(root) / ".claude" / "skills" / "review" / "SKILL.md").read_text()
    return text.split("\n---\n", 1)[1].strip() if text.startswith("---") else text


def reviewer_standards(root):
    """Raises when the skill or adapter is missing: a reviewer without the QED42 checks must never run silently."""
    return ["## QED42 blog review system (run every check below on the draft)", review_skill_text(root),
            "## How to apply the QED42 review system in this workflow (overrides the skill's interactive steps and "
            "report format)", (Path(root) / "config" / "qed42_review_adapter.md").read_text()]


IMPROVE_RULES = (
    "Start from the author's draft and change only what the goal, the assessment issues and the hard checks require "
    "(a minimal diff). Preserve the author's voice, structure, examples and facts. Never invent claims, sources, "
    "numbers, versions or personal experience. Where the checks require structure the draft lacks (FAQ, conclusion, "
    "references), add it in the author's voice, built only from what the draft already says or from sources you "
    "verified with WebSearch. Record every substantive edit in the `changes` front matter list as "
    "{section, reason}, including each removed claim; use `changes: []` only when you changed nothing.")


def wants_visuals(st):
    return st.get("mode") != "improve" or (st["brief"].get("visuals") or {}).get("min", 0) > 0


def improve_parts(root, st):
    rd = run_path(root, st["run_id"])
    goal = st["brief"]["goal"]
    parts = ["## Improve mode", IMPROVE_RULES, "Goal: " + (", ".join(goal) if isinstance(goal, list) else goal)]
    if st["brief"].get("keep"):
        parts.append("Keep unchanged (the author requires these): " + "; ".join(st["brief"]["keep"]))
    if st["source"].get("preserve"):
        parts.append("Preserve these lines verbatim (MDX imports and components):\n" + "\n".join(st["source"]["preserve"]))
    a = rd / "assessment.json"
    if a.exists():
        review = load_json(a)
        parts += ["## Assessment of the original (fix every CRITICAL and HIGH; best effort on MEDIUM)",
                  issue_lines(review["issues"], drop_low=True)]
        removals = unverified_claim_lines(review)
        if removals:
            parts += ["## Unverified claims and sources in the original: REMOVE from the draft",
                      "The reviewer could not verify these. Delete each claim, its link, its `claims` front matter "
                      "entry and any References entry. Do not reword, soften or re-source them.", removals]
    return parts


def unverified_rows(rd):
    """Every UNSUPPORTED or CONTRADICTED claim any review round raised, de-duplicated, for the change log."""
    rows, seen = [], set()
    for p in [rd / "assessment.json", *sorted(rd.glob("review-*.json"))]:
        if not p.exists():
            continue
        for c in load_json(p).get("claim_checks") or []:
            fp = claim_fingerprint(c.get("claim", ""))
            if c.get("verdict") in BAD_CLAIM and fp not in seen:
                seen.add(fp)
                rows.append({"claim": c["claim"], "verdict": c["verdict"], "source": c.get("source"),
                             "raised_in": p.stem})
    return rows


def build_writer_prompt(root, st, output=None):
    rd = run_path(root, st["run_id"])
    parts = ["# Writer task", ("Improve the existing draft described below so it meets the brief's goal, following the guidelines."
                                if st.get("mode") == "improve" else
                                "Write the blog post described by the brief, following the guidelines."),
             "Output: markdown with YAML front matter {title, slug, description, keywords, claims[{claim, source}]"
             + (", changes[{section, reason}]" if st.get("mode") == "improve" else "") + "}.",
             *([("Do not write `visual` blocks: figures are planned and added after review. Put code in fenced code "
                 "blocks with a language tag, and write the text so each section stands on its own.")]
               if visual_stage.enabled(root) else
               [f"Required: at least {(st['brief'].get('visuals') or {}).get('min', 2)} `visual` block(s) (see the writer instructions), "
                f"of which at least {(st['brief'].get('images') or {}).get('min', 1)} topic image(s) (type banner, ui_screen or cards)."]),
             "## Brief", json.dumps(st["brief"], indent=2), st.get("brief_notes", "").strip(),
             "## Guidelines", (Path(root) / "config" / "guidelines.md").read_text(), *writer_standards(root),
             *untrusted_content_section(root)]
    if st.get("mode") == "improve":
        parts += improve_parts(root, st)
    n, rev = prior_review(root, st)
    prev_draft = rd / f"draft-{st['iteration'] - 1}.md" if st["iteration"] > 1 else None
    if st["mechanical_retries"] and st["last_checks"] and st["last_checks"]["hard"]:
        cur = rd / f"draft-{st['iteration']}.md"
        parts += ["## Previous draft (fails mechanical checks)", f"Path: {output or cur}",
                  *([EDIT_NOTE] if output else []),
                  "## Hard check failures you must fix", json.dumps(st["last_checks"]["hard"], indent=2)]
    elif st.get("mode") == "improve" and st["iteration"] == 1:
        parts += ["## Source draft (the author's original)", f"Path: {output or rd / 'source.md'}",
                  *([EDIT_NOTE] if output else [])]
    elif prev_draft and prev_draft.exists():
        parts += ["## Previous draft", f"Path: {output or prev_draft}", *([EDIT_NOTE] if output else [])]
        if rev:
            parts += ["## Issues from the reviewer (fix every CRITICAL and HIGH; best effort on MEDIUM)",
                      issue_lines(rev["issues"], drop_low=True)]
        removals = unverified_claim_lines(rev) if rev else ""
        if removals:
            parts += ["## Unverified claims and sources: REMOVE from the draft",
                      "The reviewer could not verify these. Delete each claim, its link, its `claims` front matter entry "
                      "and any References entry. Do not reword, soften or re-source them; keep the article coherent "
                      "around the cut.", removals]
        hist = st["history"][-1] if st["history"] else None
        if hist and hist["hard_failures"]:
            parts += ["## Hard check failures", json.dumps(hist["hard_failures"], indent=2)]
    return "\n\n".join(p for p in parts if p)


def build_reviewer_prompt(root, st, draft_path, assess=False):
    """Contains only: brief, guidelines, saved draft path, checks result, previous issues."""
    n, rev = prior_review(root, st)
    parts = ["# Reviewer task", "Review the draft adversarially. Write JSON matching the review schema.",
             "## Brief", json.dumps(st["brief"], indent=2),
             "## Guidelines", (Path(root) / "config" / "guidelines.md").read_text(), *reviewer_standards(root),
              *untrusted_content_section(root),
             *(["## Assessment mode", ASSESS_NOTE] if assess else []),
             "## Draft to review", f"Path: {draft_path}",
             "## Deterministic checks (signals are evidence, not verdicts)", json.dumps(st["last_checks"], indent=2),
             "## Required checklist items", ", ".join(rules(root)["required_checklist"]),
             *(["## Scoring rubric (score every dimension 0-100 with evidence)", rubric_section(rules(root)),
                "## Score consistency", consistency_section(thresholds(root), rules(root))]
               if rubric_section(rules(root)) else []),
             "## Previous issues (report which are resolved and which are new)",
             issue_lines(rev["issues"]) if rev else "(none, first review)"]
    return "\n\n".join(parts)


# ---------- next ----------
def delivery_dir(root, st):
    return run_path(root, st["run_id"]) / "delivery"


def cmd_next(root, run_id):
    st = load_state(root, run_id)
    rd = run_path(root, run_id)
    s = st["state"]
    if s == "STOPPED":
        return {"action": "STOP", "reason": st.get("stop_reason", "stopped")}
    if s == "AI_REVIEW_FAILED":
        res = load_json(rd / "result.json")
        stop = {"action": "STOP", "reason": "AI review failed", "best_draft": res.get("best_draft"),
                "open_issues": res.get("open_issues")}
        if st.get("mode") == "improve":
            why = failing_delivery_problem(root, st, res)
            stop["approvable"] = why is None
            if why:
                stop["approve_blocked_reason"] = why
        return stop
    if s in ("DELIVERED", "DRY_RUN_COMPLETE"):
        return {"action": "DONE"}
    if s == "DONE_NO_CHANGES":
        return {"action": "DONE", "no_changes": True,
                "note": "The draft already met every check; nothing was changed and no Doc was created."}
    if s == "IN_PROGRESS":
        if st["phase"] == "FETCH_SOURCE":
            out_path = rd / "source" / "gdoc.md"
            st["expected_path"] = str(out_path)
            save_state(root, st)
            return {"action": "FETCH_GDOC", "doc_id": source_import.parse_gdoc_url(st["source"]["ref"]),
                    "save_to": f"runs/{run_id}/source/gdoc.md"}
        if st["phase"] == "ASSESS":
            return next_assess(root, st)
        if st["phase"] == "WRITE":
            k = st["draft_submissions"] + 1
            prompt = rd / "prompts" / f"writer-{st['iteration']}-{k}.md"
            out = rd / "incoming" / f"draft-{st['iteration']}-{k}.md"
            src = revision_source(root, st)
            if src and src.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(src.read_text())  # prefill so the writer edits in place instead of rewriting
                prompt.write_text(build_writer_prompt(root, st, output=out))
            else:
                prompt.write_text(build_writer_prompt(root, st))
            st["expected_path"] = str(out)
            save_state(root, st)
            return {"action": "WRITE", "prompt": str(prompt), "output": st["expected_path"],
                    "iteration": st["iteration"]}
        k = st["review_submissions"] + 1
        prompt = rd / "prompts" / f"reviewer-{st['iteration']}-{k}.md"
        prompt.write_text(build_reviewer_prompt(root, st, rd / f"draft-{st['iteration']}.md"))
        st["expected_path"] = str(rd / "incoming" / f"review-{st['iteration']}-{k}.json")
        save_state(root, st)
        return {"action": "REVIEW", "prompt": str(prompt), "output": st["expected_path"],
                "iteration": st["iteration"]}
    if s == "VISUALS_PLAN":
        return next_plan_visuals(root, st)
    if s == "VISUALS_HITL":
        return next_visual_hitl(root, st)
    # delivery phase
    dd = delivery_dir(root, st)
    if s in DRIVE_OK:
        if st["dry_run"]:
            return dry_run_delivery(root, st)
        return {"action": "CREATE_DOC", "title": st["delivery"]["doc_title"], "body_path": str(dd / "doc.md"),
                "folder": load_json(Path(root) / "config" / "delivery.json")["drive_folder_name"],
                "search_title_first": s == "DRIVE_DOC_FAILED",
                "exclude_doc_ids": st["delivery"].get("rejected_doc_ids", [])}
    if s in SLACK_OK:
        render_slack(root, st)
        return {"action": "POST_SLACK", "text_path": str(dd / "slack.txt"),
                "channel_id": load_json(Path(root) / "config" / "delivery.json")["slack_channel_id"]}
    raise BlogError(f"no action for state {s}")


ASSESS_NOTE = ("You are assessing the author's ORIGINAL draft against the brief's `goal`, before any rewrite. The file may "
               "lack front matter and the required outline (FAQ, conclusion, references): code adds those later, so do "
               "not raise issues only for them. Report what an editor must fix: unsupported or wrong claims, dead or "
               "unsupported sources, code errors, tone and clarity problems, and anything blocking the goal. Never "
               "invent a fix that needs facts the draft does not contain.")


def assess_signals(root, st):
    """Deterministic signals about the original, computed once per run (the link checks hit the network)."""
    p = run_path(root, st["run_id"]) / "assess-signals.json"
    if p.exists():
        return load_json(p)
    text = (run_path(root, st["run_id"]) / "source.md").read_text()
    sig = assess_mod.source_signals(text, rules(root), check_links=not os.environ.get("BLOG_NO_LINKS"))
    write_json(p, sig)
    return sig


def next_assess(root, st):
    rd = run_path(root, st["run_id"])
    k = st["assess_submissions"] + 1
    st["last_checks"] = {"hard": [], "signals": assess_signals(root, st)}
    prompt = rd / "prompts" / f"assess-{k}.md"
    prompt.write_text(build_reviewer_prompt(root, st, rd / "source.md", assess=True))
    st["expected_path"] = str(rd / "incoming" / f"assessment-{k}.json")
    save_state(root, st)
    return {"action": "REVIEW", "kind": "assess", "prompt": str(prompt), "output": st["expected_path"], "iteration": 0}


def cmd_submit_assessment(root, run_id, path):
    st = load_state(root, run_id)
    require_submission(st, "ASSESS", path)
    st["assess_submissions"] += 1
    review, why = parse_review(root, st, path, run_path(root, run_id) / "source.md")
    if why:
        return malformed(root, st, why)
    write_json(run_path(root, run_id) / "assessment.json", review)
    summary = assess_mod.summarize(review, st["last_checks"]["signals"])
    st.update(phase="WRITE", malformed_retries=0, expected_path=None, last_checks=None)
    save_state(root, st)
    return {"result": "ASSESSED", "summary": summary}


def dry_run_delivery(root, st):
    render_slack(root, st, doc_url=DRY_DOC_URL)
    dd = delivery_dir(root, st)
    set_state(root, st, "DRY_RUN_COMPLETE")
    return {"action": "DRY_RUN_DELIVERY", "would_create_doc": {"title": st["delivery"]["doc_title"],
            "body_path": str(dd / "doc.md")}, "would_post_slack": {"text_path": str(dd / "slack.txt")},
            "note": "nothing was created or posted"}


def render_slack(root, st, doc_url=None):
    url = doc_url or st["delivery"].get("doc_url")
    if not url:
        raise BlogError("no Doc URL recorded; Slack text cannot be rendered")
    rd = run_path(root, st["run_id"])
    res = load_json(rd / "result.json")
    review = load_json(rd / f"review-{res['final_iteration']}.json")
    extra = None
    if res.get("changes"):
        c = res["changes"]
        extra = [f"Revised from {st['source']['kind']} draft: {c['sections_changed']} section(s) changed, "
                 f"+{c['words_added']}/-{c['words_removed']} words. Change log: runs/{st['run_id']}/delivery/changes.md"]
    vp = rd / f"verification-{res['final_iteration']}.json"
    if vp.exists():
        extra = (extra or []) + [notify.sanitize(x, 160) for x in claim_verify.summary_lines(load_json(vp))]
    text = notify.render_slack(st["run_id"], res["title"], res["iterations"], res["signals"], review, url,
                               res.get("visuals"), res.get("weighted_total"), extra=extra,
                               override=st.get("gate_override"))
    p = delivery_dir(root, st) / "slack.txt"
    p.write_text(text)
    return p


# ---------- independent claim verification (advisory; never changes state or a gate) ----------
def latest_review(root, run_id):
    rd = run_path(root, run_id)
    nums = sorted(int(p.stem.split("-")[1]) for p in rd.glob("review-*.json") if p.stem.split("-")[1].isdigit())
    if not nums:
        raise BlogError("no accepted review to verify yet")
    return nums[-1], load_json(rd / f"review-{nums[-1]}.json")


def cmd_verify_claims(root, run_id):
    """Write one verifier prompt per blocking claim of the latest review. Returns the items to launch; no items when
    the review blocked on no claim. Read-only with respect to workflow state."""
    st = load_state(root, run_id)
    n, review = latest_review(root, run_id)
    rd = run_path(root, run_id)
    items = claim_verify.targets(review, thresholds(root).get("max_verifier_claims", 5))
    policy = (Path(root) / "config" / "untrusted_content.md").read_text()
    plan = []
    for it in items:
        prompt = rd / "prompts" / f"verify-{n}-{it['id']}.md"
        prompt.write_text(claim_verify.build_prompt(it, policy))
        plan.append({**it, "prompt": str(prompt), "output": str(rd / "incoming" / f"verify-{n}-{it['id']}.json")})
    write_json(rd / f"verification-plan-{n}.json", {"iteration": n, "items": plan})
    return {"result": "VERIFY_CLAIMS", "iteration": n, "verifiers": [
        {"id": p["id"], "prompt": p["prompt"], "output": p["output"]} for p in plan]}


def cmd_submit_verification(root, run_id):
    """Collect the verifier outputs for the latest plan into verification-N.json. A missing or invalid output is
    recorded as not checked, never as agreement."""
    load_state(root, run_id)
    rd = run_path(root, run_id)
    n, _ = latest_review(root, run_id)
    plan_path = rd / f"verification-plan-{n}.json"
    if not plan_path.exists():
        raise BlogError("run `verify-claims` first")
    results, no_result = [], []
    for it in load_json(plan_path)["items"]:
        out_path = Path(it["output"])
        try:
            res = json.loads(out_path.read_text())
            problems = schema_errors(res, "claim_verdict", root)
            if not problems and res["id"] != it["id"]:
                problems = ["id does not match the claim"]
        except (OSError, json.JSONDecodeError) as e:
            problems = [str(e)[:100]]
        if problems:
            no_result.append({"id": it["id"], "claim": it["claim"], "reason": "; ".join(problems)[:200]})
        else:
            results.append(claim_verify.compare(it, res))
    data = {"iteration": n, "results": results, "no_result": no_result,
            "disagreements": [r["id"] for r in results if r["disagrees"]]}
    write_json(rd / f"verification-{n}.json", data)
    return {"result": "VERIFIED", **data, "summary": claim_verify.summary_lines(data)}


# ---------- submissions ----------
def require_submission(st, phase, path):
    if st["state"] != "IN_PROGRESS" or st["phase"] != phase:
        raise BlogError(f"out of order: state={st['state']} phase={st.get('phase')}, expected {phase}")
    if not st["expected_path"]:
        raise BlogError("call `next` first")
    if Path(path).resolve() != Path(st["expected_path"]).resolve():
        raise BlogError(f"unexpected path; expected {st['expected_path']}")
    if not Path(path).exists():
        raise BlogError(f"file not found: {path}")


def malformed(root, st, why):
    st["malformed_retries"] += 1
    st["expected_path"] = None
    if st["malformed_retries"] > thresholds(root)["max_malformed_retries"]:
        st["stop_reason"] = f"malformed output exceeded cap: {why}"
        set_state(root, st, "STOPPED")
        return {"result": "STOPPED", "reason": st["stop_reason"]}
    save_state(root, st)
    return {"result": "MALFORMED", "reason": why, "retry": True}


def cmd_submit_draft(root, run_id, path):
    st = load_state(root, run_id)
    require_submission(st, "WRITE", path)
    rd = run_path(root, run_id)
    st["draft_submissions"] += 1
    text = Path(path).read_text()
    try:
        fm, _ = split_front_matter(text)
    except ValueError as e:
        return malformed(root, st, str(e))
    errs = schema_errors(fm, "writer_front_matter", root)
    if errs:
        return malformed(root, st, "; ".join(errs))
    if st.get("mode") == "improve" and "changes" not in fm:
        return malformed(root, st, "improve mode requires a `changes` front matter list ({section, reason}; "
                                   "an empty list only when nothing changed)")
    st["malformed_retries"] = 0
    (rd / f"draft-{st['iteration']}.md").write_text(text)
    res = checks_mod.run_checks(text, st["brief"], rules(root), check_links=not os.environ.get("BLOG_NO_LINKS"),
                                visuals_planned=visual_stage.enabled(root))
    st["last_checks"] = res
    write_json(rd / f"checks-{st['iteration']}.json", res)
    st["expected_path"] = None
    if res["hard"]:
        st["mechanical_retries"] += 1
        st["total_mechanical_retries"] += 1
        if st["mechanical_retries"] > thresholds(root)["max_mechanical_retries"]:
            return end_iteration(root, st, review=None)
        save_state(root, st)
        return {"result": "HARD_FAIL", "hard": res["hard"], "retry": True}
    st["phase"] = "REVIEW"
    save_state(root, st)
    return {"result": "CHECKS_PASSED", "signals": res["signals"]}


def cmd_submit_source(root, run_id, path):
    st = load_state(root, run_id)
    require_submission(st, "FETCH_SOURCE", path)
    try:
        imported = source_import.import_text(Path(path).read_text())
    except (source_import.SourceError, UnicodeDecodeError, OSError) as e:
        st["stop_reason"] = f"source invalid: {e}"  # end the run so it does not hold the brief's lock
        set_state(root, st, "STOPPED")
        raise BlogError(f"source invalid: {e}")
    store_source(root, st, imported)
    if "target_words" not in st["brief"]:
        st["brief"]["target_words"] = source_import.derive_target_words(imported["markdown"])
    st.update(phase="ASSESS", expected_path=None)
    save_state(root, st)
    return {"result": "SOURCE_READY", "words": checks_mod.word_count(source_import._body(imported["markdown"]))}


def cmd_classify(root, arg):
    return source_import.classify_arg(arg, root)


def parse_review(root, st, path, draft_path=None):
    """(review, None) when the file is a well-formed, self-consistent review whose anchors and claims are quoted from
    the draft, else (None, reason)."""
    try:
        review = json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    errs = schema_errors(review, "review", root)
    if errs:
        return None, "; ".join(errs)
    bad = checklist_reference_problems(review)
    if bad:
        return None, bad[0]
    draft = Path(draft_path).read_text() if draft_path else None
    probs = review_problems(review, st["last_checks"], thresholds(root), rules(root), draft)
    if probs:
        return None, "; ".join(probs)
    return review, None


def cmd_submit_review(root, run_id, path):
    st = load_state(root, run_id)
    require_submission(st, "REVIEW", path)
    st["review_submissions"] += 1
    review, why = parse_review(root, st, path, run_path(root, run_id) / f"draft-{st['iteration']}.md")
    if why:
        return malformed(root, st, why)
    st["malformed_retries"] = 0
    write_json(run_path(root, run_id) / f"review-{st['iteration']}.json", review)
    st["expected_path"] = None
    return end_iteration(root, st, review)


# ---------- iteration end ----------
def rank_key(entry):
    return (len(entry["hard_failures"]), entry["critical"], entry["high"], entry["failed_checklist"],
            len(entry.get("gate_failures", [])), entry["medium"], entry["low"], -(entry.get("weighted_total") or 0))


def entry_for(st, review, gate):
    issues = review["issues"] if review else []
    count = lambda s: sum(1 for i in issues if i["severity"] == s)
    failed_cl = sum(1 for b in gate["reviewer_blockers"] if "checklist" in b)
    sig = sorted({fingerprint(i) for i in issues if i["severity"] in ("HIGH", "CRITICAL")}
                 | {"hard:" + f["id"] for f in gate["hard_failures"]} | set(gate.get("gate_failures", [])))
    return {"iteration": st["iteration"], "hard_failures": gate["hard_failures"], "critical": count("CRITICAL"),
            "high": count("HIGH"), "medium": count("MEDIUM"), "low": count("LOW"),
            "failed_checklist": failed_cl, "gate_failures": gate.get("gate_failures", []),
            "weighted_total": gate.get("weighted_total"), "signature": sig, "draft": f"draft-{st['iteration']}.md"}


def stagnated(root, history):
    n = thresholds(root)["stagnation_patience"]
    if len(history) < n:
        return False
    tail = [tuple(h["signature"]) for h in history[-n:]]
    return len(set(tail)) == 1 and bool(tail[0])


def end_iteration(root, st, review):
    rd = run_path(root, st["run_id"])
    th, rl = thresholds(root), rules(root)
    gate = validate(st["last_checks"], review, th, rl)
    if gate["status"] == "PASSED":
        return finish_pass(root, st, review, gate)
    st["history"].append(entry_for(st, review, gate))
    stop = None
    if st["iteration"] >= th["max_iterations"]:
        stop = "iteration cap reached"
    elif stagnated(root, st["history"]):
        stop = "stagnation: same blocking issues in consecutive iterations"
    if stop:
        return finish_fail(root, st, review, gate, stop)
    st.update(iteration=st["iteration"] + 1, phase="WRITE", mechanical_retries=0, malformed_retries=0,
              expected_path=None)
    save_state(root, st)
    return {"result": "ITERATION_FAILED", "reasons": gate["reasons"], "next_iteration": st["iteration"]}


def audit_fields(root, st):
    hashes = {}
    for rel in ["config/guidelines.md", "config/rules.json", "config/thresholds.json", ".claude/agents/blog-writer.md",
                ".claude/agents/blog-reviewer.md", "config/qed42_writing.md", "config/qed42_review_adapter.md",
                ".claude/skills/review/SKILL.md"]:
        p = Path(root) / rel
        hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    models = {}
    for role in ("writer", "reviewer"):
        p = Path(root) / ".claude" / "agents" / f"blog-{role}.md"
        if p.exists():
            try:
                models[role] = split_front_matter(p.read_text())[0].get("model")
            except ValueError:
                models[role] = None
    return {"hashes": hashes, "models": models}


def finish_pass(root, st, review, gate=None):
    rd = run_path(root, st["run_id"])
    text = (rd / f"draft-{st['iteration']}.md").read_text()
    fm, _ = split_front_matter(text)
    improve = st.get("mode") == "improve"
    source_md = (rd / "source.md").read_text() if improve else None
    res = {"status": "AI_REVIEW_PASSED", "run_id": st["run_id"], "title": fm["title"],
           "iterations": st["iteration"], "final_iteration": st["iteration"],
           "mechanical_retries": st["total_mechanical_retries"], "hard_checks": st["last_checks"]["hard"],
           "signals": st["last_checks"]["signals"], "open_issues": review["issues"], "dry_run": st["dry_run"],
           "weighted_total": (gate or {}).get("weighted_total"), "scores": review.get("scores"),
           **audit_fields(root, st)}
    dd = rd / "delivery"
    dd.mkdir(exist_ok=True)
    if improve:
        rep = diff_report.build(source_md, text, fm.get("changes"), unverified_rows(rd))
        (dd / "changes.md").write_text(rep["markdown"])
        res.update(mode="improve", source=st["source"], changes=rep["summary"])
        if diff_report.is_unchanged(source_md, text):
            res["status"] = "DONE_NO_CHANGES"
            write_json(rd / "result.json", res)
            set_state(root, st, "DONE_NO_CHANGES")
            return {"result": "NO_CHANGES", "iteration": st["iteration"]}
    write_json(rd / "result.json", res)
    (dd / "doc.md").write_text(notify.render_doc(text))
    st["delivery"] = {"doc_title": notify.doc_title(fm["title"], st["run_id"])}
    if visual_stage.enabled(root) and wants_visuals(st):
        st["visuals"] = {"submissions": 0, "malformed": 0, "retries": 0, "errors": [], "prior_plan": None,
                         "results": {}, "pending": [], "pending_images": [], "blocked": {}, "dropped": {},
                         "events": []}
        set_state(root, st, "VISUALS_PLAN")
    else:
        set_state(root, st, "AI_REVIEW_PASSED")
    return {"result": "PASSED", "iteration": st["iteration"]}


def finish_fail(root, st, review, gate, stop):
    rd = run_path(root, st["run_id"])
    best = min(st["history"], key=lambda e: (rank_key(e), e["iteration"]))
    last_review = review or {"issues": []}
    res = {"status": "AI_REVIEW_FAILED", "run_id": st["run_id"], "iterations": st["iteration"],
           "stop_reason": stop, "best_draft": str(rd / best["draft"]), "best_iteration": best["iteration"],
           "mechanical_retries": st["total_mechanical_retries"], "hard_checks": gate["hard_failures"],
           "open_issues": last_review["issues"], "reasons": gate["reasons"], "history": st["history"],
           **audit_fields(root, st)}
    write_json(rd / "result.json", res)
    set_state(root, st, "AI_REVIEW_FAILED")
    return {"result": "FAILED", "stop_reason": stop, "best_draft": res["best_draft"]}


def failing_delivery_problem(root, st, res):
    """Why a failed run cannot be sent for human review, or None. Only reviewer-gate failures can be overridden."""
    if st.get("mode") != "improve":
        return "approve-failing is only for improve runs"
    if st["dry_run"]:
        return "dry-run runs never deliver"
    best = next((e for e in st["history"] if e["iteration"] == res.get("best_iteration")), None)
    if best is None:
        return "no best draft recorded"
    if best["hard_failures"]:
        ids = ", ".join(sorted({f["id"] for f in best["hard_failures"]}))
        return f"the best draft fails hard checks ({ids}); only reviewer gate failures can be overridden"
    if not (run_path(root, st["run_id"]) / f"review-{best['iteration']}.json").exists():
        return "no review exists for the best draft"
    return None


def cmd_approve_failing(root, run_id, note, approved):
    if not approved:
        raise BlogError("approve-failing needs --approved-by-human: only the user can approve this")
    note = norm(note or "")
    if len(note) < 10:
        raise BlogError("approve-failing needs --note with the user's reason (at least 10 characters)")
    st = load_state(root, run_id)
    if st.get("mode") != "improve":
        raise BlogError("approve-failing is only for improve runs")
    if st["state"] != "AI_REVIEW_FAILED":
        raise BlogError(f"out of order: state={st['state']}, expected AI_REVIEW_FAILED")
    rd = run_path(root, run_id)
    res = load_json(rd / "result.json")
    why = failing_delivery_problem(root, st, res)
    if why:
        raise BlogError(why)
    best = next(e for e in st["history"] if e["iteration"] == res["best_iteration"])
    review = load_json(rd / f"review-{best['iteration']}.json")
    text = (rd / best["draft"]).read_text()
    fm, _ = split_front_matter(text)
    blocking = [i for i in review["issues"] if i["severity"] in ("HIGH", "CRITICAL")]
    claims = [r for r in unverified_rows(rd) if r["verdict"] in BAD_CLAIM]
    override = {"note": note, "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "gate_failures": best.get("gate_failures", []), "blocking_issue_ids": [i["id"] for i in blocking],
                "unverified_claims": [c["claim"] for c in claims],
                "draft_sha256": hashlib.sha256(text.encode()).hexdigest()}
    dd = rd / "delivery"
    dd.mkdir(exist_ok=True)
    banner = notify.override_banner(blocking, claims, note)
    (dd / "doc.md").write_text(notify.render_doc(text, banner))
    rep = diff_report.build((rd / "source.md").read_text(), text, fm.get("changes"), claims)
    (dd / "changes.md").write_text(rep["markdown"])
    checks = load_json(rd / f"checks-{best['iteration']}.json")
    res.update(status="AI_REVIEW_FAILED_HUMAN_APPROVED", title=fm["title"], final_iteration=best["iteration"],
               signals=checks["signals"], weighted_total=best.get("weighted_total"), scores=review.get("scores"),
               mode="improve", source=st["source"], changes=rep["summary"], gate_override=override)
    write_json(rd / "result.json", res)
    st["gate_override"] = override
    st["delivery"] = {"doc_title": notify.doc_title(fm["title"], run_id, prefix="[FAILED GATE]")}
    set_state(root, st, "AI_REVIEW_PASSED")
    return {"state": "AI_REVIEW_PASSED", "doc_title": st["delivery"]["doc_title"]}


# ---------- delivery ----------
def cmd_record_delivery(root, run_id, event, doc_id=None, doc_url=None, error=None):
    st = load_state(root, run_id)
    if st["dry_run"]:
        raise BlogError("dry-run runs never reach a delivery state")
    s, d = st["state"], st["delivery"]
    if event in ("doc_created", "doc_failed") and s not in DRIVE_OK:
        raise BlogError(f"out of order: {event} from {s}")
    if event in ("slack_posted", "slack_failed") and s not in SLACK_OK:
        raise BlogError(f"out of order: {event} from {s}")
    if event == "doc_rejected" and not (s == "DRIVE_DOC_CREATED" and st.get("needs_attention")):
        raise BlogError(f"doc_rejected needs state DRIVE_DOC_CREATED and a failed verify-doc, got {s}")
    if event == "doc_created":
        if not doc_url:
            raise BlogError("doc_created requires --doc-url")
        d.update(doc_id=doc_id, doc_url=doc_url)
        new = "DRIVE_DOC_CREATED"
    elif event == "doc_failed":
        d["error"], new = error, "DRIVE_DOC_FAILED"
    elif event == "doc_rejected":
        d.setdefault("rejected_doc_ids", []).append(d.pop("doc_id", None))
        d.pop("doc_url", None)
        d["error"], new = error or "Doc failed verify-doc", "DRIVE_DOC_FAILED"
        st["needs_attention"] = False
    elif event == "slack_posted":
        new = "DELIVERED"
    elif event == "slack_failed":
        d["error"], new = error, "SLACK_NOTIFICATION_FAILED"
    else:
        raise BlogError(f"unknown event {event}")
    set_state(root, st, new)
    return {"state": new}


def cmd_verify_doc(root, run_id, content_file):
    st = load_state(root, run_id)
    want = (delivery_dir(root, st) / "doc.md").read_text()
    res = doc_match(want, Path(content_file).read_text(), thresholds(root).get("verify_min_coverage", 1.0))
    ok = res["match"]
    if st.get("needs_attention") != (not ok):
        st["needs_attention"] = not ok
        save_state(root, st)
    return {"match": True} if ok else res


def string_leaves(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from string_leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from string_leaves(v)


def contains_content(leaves, want):
    w = norm(want)
    for s in leaves:
        if norm(s) == w:
            return True
        try:
            if norm(base64.b64decode(s, validate=True).decode()) == w:
                return True
        except Exception:
            pass
    return False


def cmd_allow_delivery(root, hook_input):
    """Return (allowed: bool, message). hook_input is the PreToolUse JSON from the local MCP servers."""
    tool = hook_input.get("tool_name", "")
    ti = hook_input.get("tool_input") or {}
    if tool == "mcp__blog-drive__create_doc":
        kind = "drive"
    elif tool == "mcp__blog-slack__post_message":
        kind = "slack"
    elif tool.startswith(("mcp__blog-drive__", "mcp__blog-slack__")) and tool.rsplit("__", 1)[1] in (
            "search_docs", "read_doc", "read_doc_markdown"):
        return True, "read-only tool"
    elif "share" in tool.lower() or "publish" in tool.lower() or tool.startswith(("mcp__blog-drive__", "mcp__blog-slack__")):
        return False, f"{tool} is not permitted"
    else:
        return True, "not a guarded tool"
    text_field = "content" if kind == "drive" else "text"
    m = RUN_MARK_RE.search((str(ti.get("title", "")) if kind == "drive" else f"[run:{ti.get('run_id', '')}]") + "\n" + str(ti.get(text_field, "")))
    if not m:
        return False, "no [run:<id>] marker found in tool input"
    try:
        st = load_state(root, m.group(1))
    except BlogError:
        return False, f"run {m.group(1)} does not exist"
    if st["dry_run"]:
        return False, "dry-run runs never deliver"
    cfg = load_json(Path(root) / "config" / "delivery.json")
    dd = delivery_dir(root, st)
    if kind == "drive":
        if st["state"] not in DRIVE_OK:
            return False, f"Drive creation not allowed from state {st['state']}"
        want = (dd / "doc.md").read_text()  # folder is resolved server-side by blog-drive
        if ti.get("title") != st["delivery"]["doc_title"]:
            return False, "Doc title does not match the expected title"
    else:
        if st["state"] not in SLACK_OK or not st["delivery"].get("doc_url"):
            return False, f"Slack post not allowed from state {st['state']}"
        render_slack(root, st)
        want, dest, dest_val = (dd / "slack.txt").read_text(), cfg["slack_channel_id"], ti.get("channel_id")
    if norm(str(ti.get(text_field, ""))) != norm(want):
        return False, "content does not match the delivery file exactly"
    if kind == "slack" and dest_val != dest:
        return False, "destination does not match the configured channel"
    return True, "ok"


def cmd_status(root, run_id):
    st = load_state(root, run_id)
    keys = ["run_id", "state", "phase", "iteration", "mechanical_retries", "malformed_retries", "dry_run",
            "needs_attention", "delivery"]
    return {k: st.get(k) for k in keys} | {"history": st["history"]}


def cmd_resume(root, run_id, force=False):
    st = load_state(root, run_id)
    if st["state"] == "IN_PROGRESS":
        acquire_lock(root, st["brief_path"], run_id, force)
    st["expected_path"] = None
    save_state(root, st)
    return cmd_next(root, run_id)


# ---------- visual stage ----------
def final_draft(root, st):
    res = load_json(run_path(root, st["run_id"]) / "result.json")
    return run_path(root, st["run_id"]) / f"draft-{res['final_iteration']}.md"


def load_visual_plan(root, st):
    return load_json(run_path(root, st["run_id"]) / "visual-plan.json")


def visual_event(st, **ev):
    st["visuals"]["events"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **ev})


def next_plan_visuals(root, st):
    rd, vs = run_path(root, st["run_id"]), st["visuals"]
    k = vs["submissions"] + 1
    prompt = rd / "prompts" / f"visual-planner-{k}.md"
    out = rd / "incoming" / f"visual-plan-{k}.json"
    prior = vs.get("prior_plan")
    if prior and Path(prior).exists():
        out.write_text(Path(prior).read_text())  # prefill so the planner fixes the plan in place
    prompt.write_text(visual_stage.planner_prompt(root, st, final_draft(root, st), vs["errors"], prior and str(out), out))
    st["expected_path"] = str(out)
    save_state(root, st)
    return {"action": "PLAN_VISUALS", "prompt": str(prompt), "output": st["expected_path"]}


def next_visual_hitl(root, st):
    vs = st["visuals"]
    plan = load_visual_plan(root, st)
    by_id = {v["id"]: v for v in plan["visuals"]}
    if vs.get("pending_images"):
        v = by_id[vs["pending_images"][0]]
        rd = run_path(root, st["run_id"])
        out = rd / "incoming" / f"img-{v['id']}.png"
        return {"action": "GENERATE_IMAGE", "id": v["id"], "tool": "mcp__media-pipeline__create_asset",
                "prompt": visual_stage.generation_prompt(v), "aspect_ratio": v["source"]["aspect"],
                "output_path": f"{st['run_id']}/incoming/{out.name}", "out_path": str(out), "caption": v["caption"],
                "then": "submit-image after create_asset succeeds; on repeated failure ask the user, then skip-visual"}
    if vs["pending"]:
        v = by_id[vs["pending"][0]]
        src = v["source"]
        return {"action": "CAPTURE_SCREENSHOT", "id": v["id"], "url": src["url"], "steps": src.get("steps", []),
                "viewport": src.get("viewport"), "requires_login": src["requires_login"],
                "redact_note": src.get("redact_note", ""), "caption": v["caption"],
                "out_path": str(run_path(root, st["run_id"]) / "incoming" / f"shot-{v['id']}.png"),
                "has_fallback": bool(visual_stage.fallback_visual(v)),
                "then": "submit-screenshot --approved-by-human after the user confirms, or skip-visual"}
    vid, reason = next(iter(vs["blocked"].items()))
    return {"action": "VISUAL_DECISION", "id": vid, "reason": reason, "options": ["skip-visual", "stop"]}


def visual_malformed(root, st, problems):
    vs = st["visuals"]
    vs["malformed"] += 1
    vs["errors"] = problems
    st["expected_path"] = None
    if vs["malformed"] > thresholds(root)["max_malformed_retries"]:
        st["stop_reason"] = "visual plan invalid after retries: " + "; ".join(problems[:3])
        set_state(root, st, "STOPPED")
        return {"result": "STOPPED", "reason": st["stop_reason"]}
    save_state(root, st)
    return {"result": "MALFORMED", "reason": problems, "retry": True}


def cmd_submit_visual_plan(root, run_id, path):
    st = load_state(root, run_id)
    if st["state"] != "VISUALS_PLAN":
        raise BlogError(f"out of order: state={st['state']}, expected VISUALS_PLAN")
    if not st["expected_path"]:
        raise BlogError("call `next` first")
    if Path(path).resolve() != Path(st["expected_path"]).resolve():
        raise BlogError(f"unexpected path; expected {st['expected_path']}")
    if not Path(path).exists():
        raise BlogError(f"file not found: {path}")
    rd, vs = run_path(root, run_id), st["visuals"]
    vs["submissions"] += 1
    vs["prior_plan"] = str(path)
    try:
        plan = json.loads(Path(path).read_text())
    except ValueError as e:
        return visual_malformed(root, st, [f"not valid JSON: {e}"])
    problems = visual_checks.plan_errors(plan, visual_stage.split_body(final_draft(root, st).read_text()), st["brief"], root)
    if problems:
        return visual_malformed(root, st, problems)
    write_json(rd / "visual-plan.json", plan)
    results, errors, pending = visual_stage.render_plan(plan, rd / "assets", root, st["brief"])
    if errors and vs["retries"] < thresholds(root).get("max_visual_retries", 1):
        vs["retries"] += 1
        vs["errors"] = [f"{i}: {m}" for i, m in errors.items()]
        st["expected_path"] = None
        save_state(root, st)
        return {"result": "RENDER_ERRORS", "errors": vs["errors"], "retry": True}
    pending_images = [v["id"] for v in plan["visuals"] if visual_stage.needs_generation(v, root, st["brief"])]
    vs.update(results=results, pending=pending, pending_images=pending_images, blocked={}, dropped={}, errors=[])
    by_id = {v["id"]: v for v in plan["visuals"]}
    for vid, msg in errors.items():
        resolve_visual(root, st, plan, by_id[vid], msg, human=False)
    write_json(rd / "visual-plan.json", plan)
    return advance_visuals(root, st)


def resolve_visual(root, st, plan, v, reason, human):
    """Failed or declined visual: use its illustration fallback if it has one, else drop it (a required visual
    that failed on its own waits for a human decision instead)."""
    vs, vid = st["visuals"], v["id"]
    fb = visual_stage.fallback_visual(v)
    if fb:
        try:
            res = visual_stage.visual_render.render(fb, run_path(root, st["run_id"]) / "assets")
            plan["visuals"] = [fb if x["id"] == vid else x for x in plan["visuals"]]
            vs["results"][vid] = res
            visual_event(st, id=vid, event="fallback_scene", reason=reason)
            return
        except visual_stage.RenderError as e:
            reason = f"{reason}; fallback failed: {e}"
    if v.get("required") and not human:
        vs["blocked"][vid] = reason
    else:
        vs["dropped"][vid] = reason
        visual_event(st, id=vid, event="dropped", reason=reason)


def advance_visuals(root, st):
    vs = st["visuals"]
    if st["dry_run"] and vs.get("pending_images"):  # a dry run never spends image credits: it gets IMAGE TO ADD boxes
        plan = load_visual_plan(root, st)
        by_id = {v["id"]: v for v in plan["visuals"]}
        for vid in vs["pending_images"]:
            vs["results"][vid] = visual_stage.placeholder_result(by_id[vid])
            visual_event(st, id=vid, event="placeholder_dry_run")
        vs["pending_images"] = []
    if st["dry_run"] and (vs["pending"] or vs["blocked"]):  # a dry run never waits for a person
        plan = load_visual_plan(root, st)
        by_id = {v["id"]: v for v in plan["visuals"]}
        for vid in list(vs["pending"]) + list(vs["blocked"]):
            resolve_visual(root, st, plan, by_id[vid], "dry run: no human to capture it", human=True)
        vs["pending"], vs["blocked"] = [], {}
        write_json(run_path(root, st["run_id"]) / "visual-plan.json", plan)
    if vs["pending"] or vs["blocked"] or vs.get("pending_images"):
        st["expected_path"] = None
        set_state(root, st, "VISUALS_HITL")
        return {"result": "HITL", "pending_screenshots": vs["pending"], "pending_images": vs.get("pending_images", []),
                "blocked": vs["blocked"]}
    return finalize_visuals(root, st)


def cmd_submit_screenshot(root, run_id, vid, path, approved):
    st = load_state(root, run_id)
    if st["state"] != "VISUALS_HITL" or vid not in st["visuals"]["pending"]:
        raise BlogError(f"out of order: no pending screenshot {vid} in state {st['state']}")
    if not approved:
        raise BlogError("a screenshot needs --approved-by-human (the user must confirm it is correct and shows no secrets)")
    rd = run_path(root, run_id)
    if Path(path).resolve() != (rd / "incoming" / f"shot-{vid}.png").resolve():
        raise BlogError(f"unexpected path; expected {rd / 'incoming' / f'shot-{vid}.png'}")
    from PIL import Image
    try:
        with Image.open(path) as im:
            fmt = im.format
    except Exception:
        raise BlogError("screenshot is not a readable image")
    problems = ["screenshot must be a PNG"] if fmt != "PNG" else visual_stage.validate_screenshot(path, root)
    if problems:
        raise BlogError("screenshot rejected: " + "; ".join(problems))
    (rd / "assets").mkdir(exist_ok=True)
    (rd / "assets" / f"{vid}.png").write_bytes(Path(path).read_bytes())
    vs = st["visuals"]
    vs["results"][vid] = visual_stage.visual_render.image_result(rd / "assets", f"{vid}.png")
    vs["pending"].remove(vid)
    visual_event(st, id=vid, event="screenshot_approved_by_human")
    return advance_visuals(root, st)


def cmd_submit_image(root, run_id, vid, path):
    """A generated image (made by the image MCP into incoming/img-<id>.png) becomes the visual's asset."""
    st = load_state(root, run_id)
    if st["state"] != "VISUALS_HITL" or vid not in st["visuals"].get("pending_images", []):
        raise BlogError(f"out of order: no pending generated image {vid} in state {st['state']}")
    rd = run_path(root, run_id)
    src = Path(path).resolve()  # the MCP keeps the real format's extension, so .jpg and .webp are fine
    if src.parent != (rd / "incoming").resolve() or src.stem != f"img-{vid}" or src.suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise BlogError(f"unexpected path; expected {rd / 'incoming' / f'img-{vid}.png'}")
    if not Path(path).is_file():
        raise BlogError(f"file not found: {path}")
    (rd / "assets").mkdir(exist_ok=True)
    try:
        visual_stage.normalize_generated(path, rd / "assets" / f"{vid}.png", root)
    except visual_stage.RenderError as e:
        raise BlogError(f"generated image rejected: {e}")
    problems = visual_checks.asset_errors(rd / "assets" / f"{vid}.png", root)
    if problems:
        (rd / "assets" / f"{vid}.png").unlink()
        raise BlogError("generated image rejected: " + "; ".join(problems))
    vs = st["visuals"]
    vs["results"][vid] = visual_stage.visual_render.image_result(rd / "assets", f"{vid}.png")
    vs["pending_images"].remove(vid)
    visual_event(st, id=vid, event="image_generated")
    return advance_visuals(root, st)


def cmd_skip_visual(root, run_id, vid):
    st = load_state(root, run_id)
    vs = st["visuals"] if st["state"] == "VISUALS_HITL" else None
    if not vs or (vid not in vs["pending"] and vid not in vs["blocked"] and vid not in vs.get("pending_images", [])):
        raise BlogError(f"out of order: {vid} is not waiting for a decision in state {st['state']}")
    plan = load_visual_plan(root, st)
    v = next(x for x in plan["visuals"] if x["id"] == vid)
    reason = vs["blocked"].pop(vid, None) or "declined by the user"
    if vid in vs["pending"]:
        vs["pending"].remove(vid)
    if vid in vs.get("pending_images", []):
        vs["pending_images"].remove(vid)
    resolve_visual(root, st, plan, v, reason, human=True)
    write_json(run_path(root, run_id) / "visual-plan.json", plan)
    return advance_visuals(root, st)


def finalize_visuals(root, st):
    rd, vs = run_path(root, st["run_id"]), st["visuals"]
    plan = load_visual_plan(root, st)
    pngs = [rd / "assets" / r["png"] for r in vs["results"].values() if r["kind"] == "image"]
    too_big = visual_checks.total_size_errors(pngs, root)
    if too_big:
        st["stop_reason"] = "; ".join(too_big)
        set_state(root, st, "STOPPED")
        return {"result": "STOPPED", "reason": st["stop_reason"]}
    doc, prompts, report = visual_stage.apply_visuals(final_draft(root, st).read_text(), plan, vs["results"],
                                                      st["run_id"], vs["dropped"])
    dd = rd / "delivery"
    dd.mkdir(exist_ok=True)
    (dd / "doc.md").write_text(notify.render_doc(doc))
    if prompts:
        (dd / "image-prompts.md").write_text(visual_stage.image_prompts_md(st["run_id"], prompts))
    write_json(rd / "visual-report.json", {"visuals": report, "events": vs["events"]})
    res = load_json(rd / "result.json")
    res["visuals"] = {"rendered": sum(r["status"] != "dropped" for r in report), "image_prompts": len(prompts),
                      "dropped": sorted(vs["dropped"])}
    write_json(rd / "result.json", res)
    st["expected_path"] = None
    set_state(root, st, "AI_REVIEW_PASSED")
    return {"result": "VISUALS_READY", **res["visuals"]}


# ---------- CLI ----------
def main(argv=None, root=ROOT):
    ap = argparse.ArgumentParser(prog="blog.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("brief"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--force", action="store_true")
    for name in ("next", "status", "render-doc", "render-slack", "resume", "verify-doc", "submit-draft", "submit-review", "submit-assessment", "submit-source", "approve-failing", "record-delivery",
                 "submit-visual-plan", "submit-screenshot", "submit-image", "skip-visual", "verify-claims",
                 "submit-verification"):
        p = sub.add_parser(name); p.add_argument("run")
        if name in ("submit-draft", "submit-review", "submit-visual-plan", "submit-source", "submit-assessment"):
            p.add_argument("path")
        if name in ("submit-screenshot", "submit-image", "skip-visual"):
            p.add_argument("visual_id")
        if name == "submit-image":
            p.add_argument("path")
        if name == "submit-screenshot":
            p.add_argument("path"); p.add_argument("--approved-by-human", action="store_true")
        if name == "approve-failing":
            p.add_argument("--approved-by-human", action="store_true"); p.add_argument("--note", default="")
        if name == "verify-doc":
            p.add_argument("content_file")
        if name == "render-slack":
            p.add_argument("--doc-url")
        if name == "resume":
            p.add_argument("--force", action="store_true")
        if name == "record-delivery":
            p.add_argument("--event", required=True)
            p.add_argument("--doc-id"); p.add_argument("--doc-url"); p.add_argument("--error")
    sub.add_parser("allow-delivery")
    p = sub.add_parser("classify"); p.add_argument("arg", nargs="?", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "allow-delivery":
            ok, msg = cmd_allow_delivery(root, json.load(sys.stdin))
            if not ok:
                print(f"BLOCKED: {msg}", file=sys.stderr)
                return 2
            return 0
        if a.cmd == "init":
            st = cmd_init(root, a.brief, a.dry_run, a.force)
            out({"run_id": st["run_id"], "dry_run": st["dry_run"]})
        elif a.cmd == "next":
            out(cmd_next(root, a.run))
        elif a.cmd == "submit-draft":
            out(cmd_submit_draft(root, a.run, a.path))
        elif a.cmd == "submit-assessment":
            out(cmd_submit_assessment(root, a.run, a.path))
        elif a.cmd == "verify-claims":
            out(cmd_verify_claims(root, a.run))
        elif a.cmd == "submit-verification":
            out(cmd_submit_verification(root, a.run))
        elif a.cmd == "approve-failing":
            out(cmd_approve_failing(root, a.run, a.note, a.approved_by_human))
        elif a.cmd == "submit-source":
            out(cmd_submit_source(root, a.run, a.path))
        elif a.cmd == "classify":
            out(cmd_classify(root, a.arg))
        elif a.cmd == "submit-review":
            out(cmd_submit_review(root, a.run, a.path))
        elif a.cmd == "submit-visual-plan":
            out(cmd_submit_visual_plan(root, a.run, a.path))
        elif a.cmd == "submit-screenshot":
            out(cmd_submit_screenshot(root, a.run, a.visual_id, a.path, a.approved_by_human))
        elif a.cmd == "submit-image":
            out(cmd_submit_image(root, a.run, a.visual_id, a.path))
        elif a.cmd == "skip-visual":
            out(cmd_skip_visual(root, a.run, a.visual_id))
        elif a.cmd == "status":
            out(cmd_status(root, a.run))
        elif a.cmd == "render-doc":
            print(str(delivery_dir(root, load_state(root, a.run)) / "doc.md"))
        elif a.cmd == "render-slack":
            print(str(render_slack(root, load_state(root, a.run), a.doc_url)))
        elif a.cmd == "record-delivery":
            out(cmd_record_delivery(root, a.run, a.event, a.doc_id, a.doc_url, a.error))
        elif a.cmd == "verify-doc":
            out(cmd_verify_doc(root, a.run, a.content_file))
        elif a.cmd == "resume":
            out(cmd_resume(root, a.run, a.force))
    except BlogError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
