#!/usr/bin/env python3
"""Offline reviewer eval: recall on seeded defects, false-positive rate, rubric gate detection, score consistency.

Uses `claude -p` (no connectors). Usage: python evals/run_eval.py [--model sonnet]
Re-run when models, prompts, guidelines or rules change.

Each golden `<name>.md` has `<name>.expected.json`:
  {"expected_categories": [...HIGH/CRITICAL issue categories...], "expected_gate_failures": [...gate names...]}
Optional `expected_claims` maps a distinctive substring of a claim (case-insensitive) to the verdict (SUPPORTED,
CONTRADICTED or UNSUPPORTED) it must receive; keep it to claims checkable against an authoritative source or
seeded as invented. The report gives verdict accuracy (right verdicts / claims the reviewer checked) and the claims
it never checked, apart from recall. It does not affect the exit code or the gate.
Gate names are rubric dimensions (technical_accuracy, originality) or "factual_correctness". The reviewer must
fail every expected gate. Any other failed gate must be declared in `allowed_extra_gate_failures`
({gate: reason it is a legitimate consequence of the seeded defect}); an undeclared one is reported as
UNEXPLAINED and makes the run exit non-zero. `total` is implied whenever another gate fails. Good drafts expect none.

A review is accepted only if it passes the same checks `blog.py submit-review` applies (schema, checklist issue ids,
`validate.review_problems`, which rejects scores that contradict severities both ways: a HIGH/CRITICAL issue on a
dimension scored above the cap, and a hard-gate dimension scored below its minimum with no HIGH/CRITICAL issue on it).
A rejected attempt is retried with its rejection reason, up to `max_malformed_retries`
from config/thresholds.json, the workflow's own limit. A fixture still rejected after that is NOT REVIEWED: it stays
in every denominator, is reported apart from a valid review that missed its defect, and makes the run exit non-zero.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import blog  # noqa: E402
import checks  # noqa: E402
import validate  # noqa: E402
from common import load_json, schema_error_details  # noqa: E402

RAW_CAP = 20000
RULES, TH = load_json(ROOT / "config/rules.json"), load_json(ROOT / "config/thresholds.json")
MAX_ATTEMPTS = 1 + TH["max_malformed_retries"]
BRIEF = {"topic": "Why small teams should adopt design tokens", "content_type": "technical_blog",
         "audience": {"primary": "Front-end leads at small product teams", "experience_level": "intermediate"},
         "purpose": "Explain why design tokens are useful for small teams and when they are worth adopting",
         "primary_keyword": "design tokens", "secondary_keywords": ["design system", "CSS variables"],
         "tone": "practical and friendly", "target_words": {"min": 700, "max": 1100},
         "reader_takeaway": ["Understand why design tokens help even small teams",
                             "Know when adopting tokens is worth the effort"],
         "must_include": ["A short code example", "Common implementation mistakes"],
         "must_avoid": ["Vendor comparisons", "Generic AI-generated claims"],
         "technical_depth": "intermediate", "examples": {"preferred": ["React + CSS variables"], "include_code": True},
         "original_angle": "The misconception that design tokens are only useful for large organizations",
         "references": {"required": True, "preferred_sources": ["Official documentation", "W3C specifications"]}}


def gate_names(gate):
    """Map gate_failures like gate:originality:below_min / gate:factual_correctness / claim:<fp> to eval names."""
    names = set()
    for g in gate["gate_failures"]:
        if g.startswith("gate:") and g.endswith(":below_min"):
            names.add(g.split(":")[1])
        elif g in ("gate:factual_correctness", "gate:total") or g.startswith("claim:"):
            names.add("factual_correctness" if g != "gate:total" else "total")
    return names


def unexplained_gate_failures(got, expected, allowed):
    """Failed gates that the fixture neither expects nor declares as a legitimate consequence of its defect."""
    extra = set(got) - set(expected) - set(allowed)
    if got - {"total"}:
        extra.discard("total")
    return sorted(extra)


def reviewer_prompt(draft_path, feedback=None):
    reviewer = (ROOT / ".claude/agents/blog-reviewer.md").read_text().split("---", 2)[2]
    standards = "\n\n".join(blog.reviewer_standards(ROOT))
    return (f"{reviewer}\n\n## Brief\n{json.dumps(BRIEF)}\n\n## Guidelines\n{(ROOT/'config/guidelines.md').read_text()}\n\n"
            f"{standards}\n\n## Draft\n{Path(draft_path).read_text()}\n\n## Required checklist items\n"
            f"{', '.join(RULES['required_checklist'])}\n\n## Scoring rubric (score every dimension 0-100 with evidence)\n"
            f"{validate.rubric_section(RULES)}\n\n## Score consistency\n{validate.consistency_section(TH, RULES)}\n\n"
            "Return ONLY the JSON review object on stdout; do not write files."
            + (f"\n\n{feedback}" if feedback else ""))


def run_reviewer(draft_path, model, feedback=None):
    """Raw reviewer stdout. Raises on a failed process; never parses or repairs."""
    r = subprocess.run(["claude", "-p", reviewer_prompt(draft_path, feedback), "--model", model, "--allowedTools", "WebSearch,WebFetch"],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"claude exited {r.returncode}: {(r.stderr.strip() or r.stdout.strip())[:300]}")
    return r.stdout


def parse_review(raw):
    """Strict parse of a raw reviewer response -> (review or None, failure or None).

    failure = {"stage": empty|no_json|json_syntax|not_object|schema, "detail": str, "errors": [...]}.
    Only a Markdown code fence is stripped; nothing else is repaired, so prose or malformed JSON is a failure."""
    txt = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not txt:
        return None, {"stage": "empty", "detail": "reviewer returned no output", "errors": []}
    if not txt.startswith("{"):
        return None, {"stage": "no_json", "detail": f"output does not start with a JSON object: {txt[:120]!r}", "errors": []}
    try:
        rev = json.loads(txt)
    except json.JSONDecodeError as e:
        return None, {"stage": "json_syntax", "detail": f"{e.msg} at line {e.lineno} col {e.colno}", "errors": []}
    if not isinstance(rev, dict):
        return None, {"stage": "not_object", "detail": f"top level is {type(rev).__name__}", "errors": []}
    errs = schema_error_details(rev, "review")
    if errs:
        return None, {"stage": "schema", "detail": f"{len(errs)} schema error(s)", "errors": errs}
    return rev, None


def write_diagnostic(diag_dir, sample, attempt, failure, raw):
    """One file per failed attempt, kept apart from accepted reviews. The raw response is only reviewer output
    about a golden fixture (no environment, no prompt); it is capped to keep artifacts small."""
    Path(diag_dir).mkdir(parents=True, exist_ok=True)
    out = Path(diag_dir) / f"{sample}.attempt{attempt}.failed.json"
    out.write_text(json.dumps({"sample": sample, "attempt": attempt, **failure,
                               "raw_response": (raw or "")[:RAW_CAP], "raw_truncated": len(raw or "") > RAW_CAP}, indent=2))
    return out


def acceptance_problems(draft, rev):
    """What `blog.py submit-review` rejects in a schema-valid review: failed items without an issue, and
    `validate.review_problems` (missing scores, too few claim checks, HIGH issue on a dimension above the cap)."""
    signals = checks.run_checks(Path(draft).read_text(), BRIEF, RULES, check_links=False)["signals"]
    return validate.checklist_reference_problems(rev) + validate.review_problems(rev, {"signals": signals}, TH, RULES,
                                                                                            Path(draft).read_text())


def claim_verdicts(rev, expected):
    """[(key, expected verdict, reviewer verdict or None)] for each `expected_claims` entry. The reviewer verdict is
    from the first claim_checks entry whose text contains the key (case-insensitive); None when it checked no such claim."""
    checks_ = rev.get("claim_checks") or []
    out = []
    for key, want in expected.items():
        got = next((c.get("verdict") for c in checks_ if key.lower() in str(c.get("claim", "")).lower()), None)
        out.append((key, want, got))
    return out


def failure_cause(stage):
    """`process` (claude exited non-zero or timed out) is an infrastructure failure; every other stage is a rejection
    of the reviewer's own output. Both count the same toward NOT REVIEWED and the exit code; this only labels them."""
    return "infrastructure" if stage == "process" else "reviewer"


def retry_feedback(failure, raw):
    """Prompt addendum for a retry: the exact rejection reason and the rejected output. It asks for a re-judgment,
    never for a score or severity change made only to pass validation."""
    if failure["stage"] == "process":
        return None
    errs = "".join(f"\n- {e.get('path') or '(root)'}: {e.get('message', e.get('keyword'))}" for e in failure["errors"])
    return ("## Your previous review was rejected\n"
            f"Rejected at {failure['stage']}: {failure['detail']}{errs}\n\n"
            "Return a complete corrected review as JSON only. Re-read the draft and fix the judgment that is wrong. "
            "Scores and severities must agree both ways: if an issue really is HIGH or CRITICAL on a dimension, that "
            "dimension's score must reflect it; if a hard-gate score really fails, a HIGH or CRITICAL issue on that "
            "dimension must say why; otherwise the score, or the issue's severity or dimension, is wrong. Do not change "
            "a judgment only to pass validation.\n\n"
            f"Your rejected output:\n{(raw or '')[:RAW_CAP]}")


def attempt_review(draft, model, diag_dir, attempts=MAX_ATTEMPTS, problems=None):
    """Run the reviewer up to `attempts` times. `problems(review)` lists acceptance problems of a parsed review (None
    checks parsing and schema only). Returns (review or None, failures), where failures lists every failed attempt,
    including ones a later retry recovered from, so first-attempt problems are never hidden."""
    failures, feedback = [], None
    for attempt in range(1, attempts + 1):
        raw = None
        try:
            raw = run_reviewer(draft, model, feedback)
            rev, failure = parse_review(raw)
            probs = problems(rev) if failure is None and problems else []
            if probs:
                rev, failure = None, {"stage": "consistency", "detail": "; ".join(probs), "errors": []}
        except Exception as e:  # process failure or timeout
            rev, failure = None, {"stage": "process", "detail": str(e)[:300], "errors": []}
        if failure is None:
            return rev, failures
        path = write_diagnostic(diag_dir, Path(draft).stem, attempt, failure, raw)
        failures.append({"attempt": attempt, **failure, "diagnostic": str(path)})
        feedback = retry_feedback(failure, raw)
        kinds = sorted({e["keyword"] for e in failure["errors"]})
        print(f"{Path(draft).name}: attempt {attempt}/{attempts} rejected at {failure['stage']}: {failure['detail']}"
              f"{' keywords=' + ','.join(kinds) if kinds else ''} -> {path}")
    return None, failures


def self_check_consistency():
    """Offline, both directions: a HIGH issue on a dimension with a high score, and a hard-gate dimension below its
    minimum with only a MEDIUM issue, must each be rejected as malformed."""
    def rev(sev, score):
        d = RULES["hard_gate_dimensions"][0]
        scores = {k: {"score": score if k == d else 85, "evidence": "e"} for k in RULES["rubric"]}
        return {"checklist": [], "summary": "s", "scores": scores, "claim_checks": [],
                "factual_correctness": {"passed": True, "evidence": "e"},
                "issues": [{"id": "i1", "severity": sev, "category": "accuracy", "dimension": d,
                            "anchor": "a", "description": "d"}]}
    low = min(validate.hard_gate_minimums(TH, RULES).values()) - 1
    return all(validate.review_problems(r, {"signals": {}}, TH, RULES) for r in (rev("HIGH", 85), rev("MEDIUM", low)))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--model", default="sonnet")
    ap.add_argument("--diag-dir", default=str(ROOT / "runs/eval-diagnostics"),
                    help="where failed-attempt raw responses and structured errors are saved (separate from --dump)")
    ap.add_argument("--dump", help="directory to save each raw review JSON (for debugging)")
    a = ap.parse_args()
    tp = fn = good = good_nr = fp = gate_fp = 0
    per, per_gate, rows, all_failures, not_reviewed = {}, {}, [], {}, {}
    all_unexplained, good_failed = {}, {}
    claim_rows = []
    fixtures = sorted((ROOT / "evals/golden").glob("*.md"))
    for d in fixtures:
        exp_file = load_json(d.with_suffix(".expected.json"))
        exp, exp_gates = exp_file["expected_categories"], set(exp_file.get("expected_gate_failures", []))
        allowed = exp_file.get("allowed_extra_gate_failures", {})
        rev, failures = attempt_review(d, a.model, a.diag_dir, problems=lambda r, d=d: acceptance_problems(d, r))
        all_failures[d.name] = failures
        sha = hashlib.sha256(d.read_bytes()).hexdigest()[:12]
        if not exp:
            good += 1
        if rev is None:
            # Failed to review: stays in every denominator as a miss, but is never counted as a reviewer miss.
            last = failures[-1]
            not_reviewed[d.name] = {"attempts": len(failures), "retries": len(failures) - 1, "stage": last["stage"],
                                    "cause": failure_cause(last["stage"]), "reason": last["detail"],
                                    "attempt_stages": [f["stage"] for f in failures],
                                    "diagnostics": [f["diagnostic"] for f in failures]}
            for c in exp:
                per.setdefault(c, []).append(False)
            good_nr += not exp
            for g in exp_gates:
                per_gate.setdefault(g, []).append(False)
            rows.append({"sample": d.name, "draft_sha256": sha, "status": "NOT_REVIEWED", **not_reviewed[d.name]})
            print(f"{d.name}: NOT REVIEWED after {len(failures)} attempt(s) ({len(failures) - 1} retries), "
                  f"cause: {failure_cause(last['stage'])}. "
                  f"Last rejection at {last['stage']}: {last['detail']} -> {last['diagnostic']}")
            continue
        if a.dump:
            Path(a.dump).mkdir(parents=True, exist_ok=True)
            (Path(a.dump) / f"{d.stem}.review.json").write_text(json.dumps(rev, indent=2))
        claim_rows += [(d.name, *v) for v in claim_verdicts(rev, exp_file.get("expected_claims", {}))]
        gate = validate.validate({"hard": []}, rev, TH, RULES)
        got_gates = gate_names(gate)
        found = {i["category"] for i in rev["issues"] if i["severity"] in ("HIGH", "CRITICAL")}
        if exp:
            for c in exp:
                hit = c in found
                per.setdefault(c, []).append(hit)
                tp += hit; fn += not hit
        else:
            fp += bool(found)
            if gate["status"] != "PASSED":
                good_failed[d.name] = gate["reasons"]
        for g in exp_gates:
            per_gate.setdefault(g, []).append(g in got_gates)
        if not exp_gates and not exp:
            gate_fp += bool(got_gates)
        unexplained = unexplained_gate_failures(got_gates, exp_gates, allowed)
        if unexplained:
            all_unexplained[d.name] = unexplained
        scores = rev.get("scores") or {}
        rows.append({"sample": d.name, "draft_sha256": sha, "status": "REVIEWED", "attempts": len(failures) + 1,
                     "rejected_attempts": [f"{f['stage']}: {f['detail']}" for f in failures],
                     "originality": scores.get("originality", {}).get("score"),
                     "hard_gate_scores": {g: scores.get(g, {}).get("score") for g in RULES["hard_gate_dimensions"]},
                     "originality_checks": {c["item"]: c["pass"] for c in rev["checklist"]
                                            if c["item"] in ("beats_the_docs", "original_insight")},
                     "high_issue_dims": sorted({f"{i['category']}->{i.get('dimension')}" for i in rev["issues"]
                                                if i["severity"] in ("HIGH", "CRITICAL")}),
                     "total_score": gate["weighted_total"], "min_score": TH["hard_gates"]["min_total_score"],
                     "gate_failures": sorted(got_gates), "expected_gate_failures": sorted(exp_gates),
                     "unexplained_gate_failures": unexplained, "passed": gate["status"] == "PASSED"})
        print(f"{d.name}: expected={exp} found_high={sorted(found)}")
    for r in rows:
        print(json.dumps(r))
    n_exp = sum(len(v) for v in per.values())
    nr_exp = n_exp - tp - fn
    rejected = {k: [f["stage"] for f in f_] for k, f_ in all_failures.items() if f_}
    print(f"\nFixtures: {len(fixtures)}; valid reviews: {len(fixtures) - len(not_reviewed)}; "
          f"not reviewed: {len(not_reviewed)} {sorted(not_reviewed)}")
    print(f"recall: {tp}/{n_exp} (missed by a valid review: {fn}; not reviewed: {nr_exp}); "
          f"per defect: { {k: f'{sum(v)}/{len(v)}' for k, v in sorted(per.items())} }")
    checked = [r for r in claim_rows if r[3] is not None]
    wrong = [f"{r[0]}: {r[1]!r} expected {r[2]}, got {r[3]}" for r in checked if r[3] != r[2]]
    unchecked = [f"{r[0]}: {r[1]!r}" for r in claim_rows if r[3] is None]
    print(f"claim verdict accuracy: {len(checked) - len(wrong)}/{len(checked)} checked claims right; wrong: {wrong}; "
          f"expected claims the reviewer never checked: {len(unchecked)} {unchecked}")
    print(f"false-positive rate on good drafts: {fp}/{good} (not reviewed: {good_nr})")
    print("Gate detection: " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(per_gate.items())))
    print(f"Gate false alarms on good drafts: {gate_fp}; good drafts failing overall validation: "
          f"{len(good_failed)}/{good} {good_failed}")
    print(f"Rejected attempts (malformed or inconsistent, retried up to {MAX_ATTEMPTS - 1} times): "
          f"{sum(len(v) for v in rejected.values())} across {len(rejected)}/{len(fixtures)} fixture(s) {rejected}")
    print(f"Not reviewed after retries: {len(not_reviewed)}/{len(fixtures)} {not_reviewed}")
    infra = {k: n for k, f_ in all_failures.items() if (n := sum(failure_cause(f["stage"]) == "infrastructure" for f in f_))}
    print(f"Infrastructure failures (claude process error or timeout, not the reviewer's output): "
          f"{sum(infra.values())} attempt(s) across {len(infra)}/{len(fixtures)} fixture(s) {infra}; "
          "not reviewed because of infrastructure: "
          f"{sorted(k for k, v in not_reviewed.items() if v['cause'] == 'infrastructure')}; "
          f"because of reviewer output: {sorted(k for k, v in not_reviewed.items() if v['cause'] == 'reviewer')}")
    print(f"Unexplained gate failures: {len(all_unexplained)} sample(s) {all_unexplained}")
    print("Score consistency: HIGH issue / high score and unexplained below-minimum hard-gate score correctly rejected: "
          f"{'yes' if self_check_consistency() else 'NO'}")
    return 1 if all_unexplained or not_reviewed else 0


if __name__ == "__main__":
    sys.exit(main())
