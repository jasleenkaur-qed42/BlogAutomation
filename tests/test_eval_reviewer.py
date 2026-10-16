"""Offline tests for the reviewer eval's strict parsing and failed-attempt diagnostics."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "scripts"))
import run_eval  # noqa: E402

VALID = {"checklist": [], "issues": [], "summary": "s"}


def test_valid_review_parses_with_fence():
    rev, fail = run_eval.parse_review("```json\n" + json.dumps(VALID) + "\n```")
    assert fail is None and rev == VALID


def test_parse_failures_are_classified_not_repaired():
    assert run_eval.parse_review("  ")[1]["stage"] == "empty"
    assert run_eval.parse_review("Here is the review: {}")[1]["stage"] == "no_json"
    assert run_eval.parse_review('{"checklist": [,]}')[1]["stage"] == "json_syntax"
    assert run_eval.parse_review("{}")[1]["stage"] == "schema"


def test_schema_failure_reports_keyword_and_path():
    bad = {**VALID, "issues": [{"id": "i1", "severity": "SEVERE", "category": "x", "anchor": "a"}]}
    _, fail = run_eval.parse_review(json.dumps(bad))
    kinds = {(e["path"], e["keyword"]) for e in fail["errors"]}
    assert ("issues/0/severity", "enum") in kinds and ("issues/0", "required") in kinds


def test_failed_attempts_are_recorded_even_when_retry_succeeds(tmp_path, monkeypatch):
    outputs = iter(["prose, not json", json.dumps(VALID)])
    monkeypatch.setattr(run_eval, "run_reviewer", lambda d, m, f=None: next(outputs))
    rev, failures = run_eval.attempt_review(tmp_path / "x.md", "sonnet", tmp_path / "diag")
    assert rev == VALID and [f["stage"] for f in failures] == ["no_json"]
    saved = json.loads((tmp_path / "diag/x.attempt1.failed.json").read_text())
    assert saved["raw_response"] == "prose, not json" and not (tmp_path / "diag/x.attempt2.failed.json").exists()


def test_retry_exhaustion_returns_all_failures(tmp_path, monkeypatch):
    def boom(d, m, f=None):
        raise RuntimeError("timeout")
    monkeypatch.setattr(run_eval, "run_reviewer", boom)
    rev, failures = run_eval.attempt_review(tmp_path / "x.md", "sonnet", tmp_path / "diag")
    # The attempt count is the workflow's policy: one try plus max_malformed_retries from thresholds.json.
    assert run_eval.MAX_ATTEMPTS == 1 + TH["max_malformed_retries"]
    assert rev is None and [f["stage"] for f in failures] == ["process"] * run_eval.MAX_ATTEMPTS
    assert (tmp_path / f"diag/x.attempt{run_eval.MAX_ATTEMPTS}.failed.json").exists()


def test_raw_response_is_capped(tmp_path):
    p = run_eval.write_diagnostic(tmp_path, "s", 1, {"stage": "no_json", "detail": "d", "errors": []}, "x" * (run_eval.RAW_CAP + 5))
    d = json.loads(p.read_text())
    assert len(d["raw_response"]) == run_eval.RAW_CAP and d["raw_truncated"]


def test_schema_still_rejects_null_issue_id():
    """Regression: reviewers emitted "issue_id": null on passing items. The fix is in the prompt; the schema stays strict."""
    bad = {**VALID, "checklist": [{"item": "x", "pass": True, "evidence": "e", "issue_id": None}]}
    _, fail = run_eval.parse_review(json.dumps(bad))
    assert [(e["path"], e["keyword"]) for e in fail["errors"]] == [("checklist/0/issue_id", "type")]


def test_reviewer_prompt_shows_passing_item_without_issue_id():
    text = (ROOT / ".claude/agents/blog-reviewer.md").read_text()
    template = text[text.index('{"checklist"'):text.index('"issues"')]
    passing = next(l for l in template.splitlines() if '"pass":true' in l)
    failing = next(l for l in template.splitlines() if '"pass":false' in l)
    assert "issue_id" not in passing and "issue_id" in failing
    assert "never `null`" in text


def test_unexplained_gate_failures():
    f = run_eval.unexplained_gate_failures
    assert f({"factual_correctness", "total"}, {"factual_correctness"}, {}) == []
    assert f({"factual_correctness", "originality", "total"}, {"factual_correctness"}, {}) == ["originality"]
    assert f({"factual_correctness", "originality"}, {"factual_correctness"}, {"originality": "why"}) == []
    assert f({"total"}, set(), {}) == ["total"]  # a good draft failing only on total is still unexplained


def test_defect_tone_fixture_seeds_only_the_intro_tone():
    golden = ROOT / "evals/golden"
    good, tone = (golden / "good-01.md").read_text().splitlines(), (golden / "defect-tone.md").read_text().splitlines()
    changed = [(g, t) for g, t in zip(good, tone) if g != t]
    assert len(good) == len(tone) and len(changed) == 1
    g, t = changed[0]
    assert t.endswith(g) and "!" in t[: len(t) - len(g)]
    exp = json.loads((golden / "defect-tone.expected.json").read_text())
    assert exp["expected_categories"] == ["tone"] and not exp["expected_gate_failures"]
    assert set(exp.get("allowed_extra_gate_failures", {})) <= {"total"}  # no accuracy or factual gate may be excused


# ---- golden fixture synchronisation: every defect differs from the baseline only by its seed ----
GOLDEN = ROOT / "evals/golden"
FAQ_SEEDLESS = ("defect-false-claim", "defect-obsolete-api", "defect-unsupported-claim", "defect-tone")


def _golden(name):
    return (GOLDEN / f"{name}.md").read_text()


def _changed_lines(name):
    import difflib
    good, other = _golden("good-01").splitlines(), _golden(name).splitlines()
    return [l for l in difflib.unified_diff(good, other, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]


def test_defect_false_claim_differs_only_by_the_invented_statistic():
    added, removed = _golden("defect-false-claim"), _golden("good-01")
    seed = "Design tokens were invented by Apple in 1987 and are now used by 99% of all websites. "
    assert seed in added and added.replace(seed, "") == removed


def test_defect_unsupported_claim_differs_only_by_the_unsourced_statistic():
    seed = "Teams that adopt design tokens ship features 37% faster and cut UI bugs by more than half. "
    assert _golden("defect-unsupported-claim").replace(seed, "") == _golden("good-01")


def test_defect_obsolete_api_differs_only_in_the_css_block():
    good, obs = _golden("good-01"), _golden("defect-obsolete-api")
    assert "token(color-primary)" in obs and "token(" not in good
    start, end = good.index("```css"), good.index("```", good.index("```css") + 6) + 3
    s2, e2 = obs.index("CSS now has a native `token()`"), obs.index("```", obs.index("```css") + 6) + 3
    assert good[:start] == obs[:s2] and good[end:] == obs[e2:]


def test_defect_tone_matches_baseline_except_the_hype_prefix():
    seed = _changed_lines("defect-tone")
    assert len(seed) == 2 and seed[0].startswith("-") and seed[1].startswith("+")
    assert seed[1][1:].endswith(seed[0][1:])


def test_no_defect_fixture_carries_stale_baseline_text():
    """Regression: three fixtures kept an old good-01 intro, description and FAQ and so differed from the baseline in ways
    no one intended. Phrases removed from the baseline must not reappear in any fixture."""
    stale = ["Design tokens have a reputation as something only large organizations need",
             "Tokens pay off earlier than most teams expect",
             "Do I need a design system to use design tokens?",
             "Design tokens are not only for large organizations. See when"]
    for p in GOLDEN.glob("*.md"):
        for s in stale:
            assert s not in p.read_text(), f"{p.name} contains stale text: {s}"


# ---- FAQ: baseline asks genuine next questions; the heuristic must still catch a FAQ that restates the body ----
def _faq(text):
    import re
    m = re.search(r"## Frequently asked questions\n(.*?)\n## ", text, re.S)
    return re.findall(r"### (.+?)\n(.+?)(?=\n###|\Z)", m.group(1).strip() + "\n", re.S)


def _body_overlap(answer, body):
    import re
    words = lambda s: set(re.findall(r"[a-z0-9]{4,}", s.lower()))
    a = words(answer)
    best = max((len(a & words(p)) / max(len(a), 1) for p in re.split(r"\n\s*\n", body)), default=0)
    return best


def _body_without_faq(text):
    return text[:text.index("## Frequently asked questions")] + text[text.index("## Conclusion"):]


def test_good_faq_adds_content_the_body_does_not_contain():
    text = _golden("good-01")
    body = _body_without_faq(text)
    faq = _faq(text)
    assert 5 <= len(faq) <= 7
    assert all(_body_overlap(a, body) < 0.6 for _, a in faq)


def test_restating_faq_is_still_detected():
    """The old baseline FAQ ('start with color and spacing', 'tokens work on their own') copies body sentences."""
    body = _body_without_faq(_golden("good-01"))
    restating = ("Start with color and spacing, because they repeat the most. Put the tokens in one file, import it at the root, "
                 "and replace hard-coded values as you touch each component.")
    assert _body_overlap(restating, body) >= 0.6


# ---- defect-no-perspective: its only seeded defect is the missing perspective ----
def test_no_perspective_fixture_has_no_checkable_benefit_claims():
    """Run 2/4/5 failed factual_correctness and technical_accuracy on 'improves efficiency', 'reduce duplicated work' and
    'most of the early benefit': unsourced benefit assertions that belong to the unsupported-claim seed, not this one."""
    text = _golden("defect-no-perspective")
    for phrase in ("improves efficiency", "reduce the amount of duplicated work", "most of the early benefit"):
        assert phrase not in text
    exp = json.loads((GOLDEN / "defect-no-perspective.expected.json").read_text())
    assert exp["expected_categories"] == ["originality"] and not exp.get("allowed_extra_gate_failures")


def test_no_perspective_faq_is_the_baseline_faq_minus_one_swapped_question():
    """The theme-flash answer is a checkable claim; with `claims: []` the reviewer flagged it UNSUPPORTED in 3 of 5 runs
    (post-sync run set 3), tripping the claim gate for a reason unrelated to the missing perspective."""
    nf, gf = dict(_faq(_golden("defect-no-perspective"))), dict(_faq(_golden("good-01")))
    assert set(gf) - set(nf) == {"Can a theme switch flash the wrong colors on load?"}
    assert all(nf[q] == gf[q] for q in set(nf) & set(gf)) and len(nf) == len(gf)
    assert "flash" not in _golden("defect-no-perspective")


def test_defect_obsolete_api_keeps_every_baseline_token_and_only_changes_syntax():
    good, obs = _golden("good-01"), _golden("defect-obsolete-api")
    block = lambda t: t[t.index("```css"):t.index("```", t.index("```css") + 6)]
    g, o = block(good), block(obs)
    # Declarations become `$name`; the three `var(--name)` uses become `token(name)`, so they carry no `$`.
    assert g.count("\n  --") == o.count("\n  $") == 5 and g.count("var(--") == o.count("token(") == 3
    assert 'data-theme="dark"' in o
    assert o.replace("$", "--").replace("token(color-primary)", "var(--color-primary)") \
        .replace("token(space-2) token(space-4)", "var(--space-2) var(--space-4)") == g


# ---- schema reliability ----
def _item(**kw):
    return {"item": "x", "pass": True, "evidence": "e", **kw}


def test_schema_accepts_passing_item_without_issue_id_and_requires_it_on_failure():
    ok = {**VALID, "checklist": [_item()]}
    assert run_eval.parse_review(json.dumps(ok))[1] is None
    bad = {**VALID, "checklist": [_item(**{"pass": False})]}
    _, fail = run_eval.parse_review(json.dumps(bad))
    assert fail["stage"] == "schema"


def test_retry_exhaustion_makes_eval_exit_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "run_reviewer", lambda d, m, f=None: "not json")
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--diag-dir", str(tmp_path)])
    assert run_eval.main() == 1
    assert list(tmp_path.glob(f"*.attempt{run_eval.MAX_ATTEMPTS}.failed.json"))


def test_first_attempt_failure_is_reported_even_when_retry_succeeds(tmp_path, monkeypatch, capsys):
    outputs = {"n": 0}

    def flaky(d, m, f=None):
        outputs["n"] += 1
        return "oops" if outputs["n"] % 2 else json.dumps(VALID)
    monkeypatch.setattr(run_eval, "run_reviewer", flaky)
    _, failures = run_eval.attempt_review(GOLDEN / "good-01.md", "sonnet", tmp_path)
    assert [f["attempt"] for f in failures] == [1]


def test_reviewer_prompt_allows_string_issue_id_on_flagged_passing_item():
    """Post-fix runs: passing items flagged by a MEDIUM issue (voice and originality checks) got "issue_id": null, 8 of 30
    first attempts. The schema accepts a string id there, so the prompt now says so instead of only saying 'omit it'."""
    text = (ROOT / ".claude/agents/blog-reviewer.md").read_text()
    assert "flagged by an issue" in text and "either a string id or absent" in text


def test_flagged_passing_item_with_string_issue_id_is_accepted():
    ok = {**VALID, "checklist": [_item(evidence="flagged in i3", issue_id="i3")]}
    assert run_eval.parse_review(json.dumps(ok))[1] is None


def test_flagged_passing_item_with_null_issue_id_is_rejected_by_schema():
    bad = {**VALID, "checklist": [_item(evidence="flagged in i3", issue_id=None)]}
    _, fail = run_eval.parse_review(json.dumps(bad))
    assert fail["stage"] == "schema" and fail["errors"][0]["keyword"] == "type"
    ok = {**VALID, "checklist": [_item(evidence="flagged in i3")]}
    assert run_eval.parse_review(json.dumps(ok))[1] is None


def test_no_perspective_body_makes_no_cross_platform_or_benefit_assertions():
    text = _golden("defect-no-perspective")
    assert "shared across platforms" not in text and "scalability" not in text


# ---- claim verdicts: an uncited but correct claim is SUPPORTED, so it cannot trip the factual gate ----
# Root cause of the intermittent defect-no-perspective failure: the reviewer passed factual_correctness and both Check 8
# checklist items, yet listed one true statement as UNSUPPORTED because the draft gave no inline citation ("a standard
# definition, but it carries no inline source"). Any UNSUPPORTED verdict fails the claim gate, which the eval maps to
# factual_correctness, an unexpected gate for this fixture. The fix is in the verdict rule; the gate stays strict.
RULES, TH = run_eval.RULES, run_eval.TH
WCAG = {"claim": "WCAG minimum contrast ratio of 4.5:1 for body text", "source": "https://www.w3.org/TR/WCAG22/#contrast-minimum",
        "verdict": "SUPPORTED", "evidence": "SC 1.4.3 requires 4.5:1."}
UNCITED_TRUE = {"claim": "Design tokens are named entities that store visual design attributes", "source": None,
                "verdict": "UNSUPPORTED", "evidence": "This is a standard definition, but it carries no inline source."}
INVENTED = {"claim": "Design tokens were invented by Apple in 1987 and are now used by 99% of all websites", "source": None,
            "verdict": "CONTRADICTED", "evidence": "No such origin; the DTCG history says otherwise."}
UNSOURCED_STAT = {"claim": "Teams that adopt design tokens ship features 37% faster", "source": None,
                  "verdict": "UNSUPPORTED", "evidence": "No study reports this figure."}


def _issue(i, category, dimension, severity="HIGH"):
    return {"id": f"i{i}", "severity": severity, "category": category, "dimension": dimension, "anchor": "a", "description": "d"}


def _review(scores=None, factual=True, claims=(WCAG,), issues=(), failed=()):
    """A schema-valid, internally consistent review: failed checklist items point at the first issue."""
    s = {d: 85 for d in RULES["rubric"]} | (scores or {})
    return {"checklist": [{"item": it, "pass": it not in failed, "evidence": "e", **({"issue_id": "i1"} if it in failed else {})}
                          for it in RULES["required_checklist"]],
            "issues": list(issues), "summary": "s", "scores": {d: {"score": v, "evidence": "e"} for d, v in s.items()},
            "factual_correctness": {"passed": factual, "evidence": "e"}, "claim_checks": list(claims)}


NO_PERSPECTIVE = dict(scores={"originality": 25, "technical_depth": 30, "practical_usefulness": 35}, issues=[_issue(1, "originality", "originality")],
                      failed=("original_insight", "beats_the_docs"))
MOCK_REVIEWS = {
    "good-01": _review(),
    "defect-no-perspective": _review(**NO_PERSPECTIVE),
    "defect-false-claim": _review(scores={"technical_accuracy": 40}, factual=False, claims=(WCAG, INVENTED),
                                  issues=[_issue(1, "accuracy", "technical_accuracy")], failed=("factual_accuracy",)),
    "defect-unsupported-claim": _review(scores={"technical_accuracy": 50}, factual=False, claims=(WCAG, UNSOURCED_STAT),
                                        issues=[_issue(1, "accuracy", "technical_accuracy")], failed=("no_unsupported_claims",)),
    "defect-obsolete-api": _review(scores={"technical_accuracy": 40}, factual=False,
                                   claims=(WCAG, {**INVENTED, "claim": "CSS now has a native token() function"}),
                                   issues=[_issue(1, "accuracy", "technical_accuracy")], failed=("code_correctness",)),
    "defect-tone": _review(scores={"structure_clarity": 65, "audience_fit": 65, "technical_depth": 65, "practical_usefulness": 65},
                           issues=[_issue(1, "tone", "audience_fit")], failed=("voice_positive_framing",)),
}


def _eval_gates(name, review):
    """Exactly the path main() takes from an accepted review to the unexplained-gate verdict."""
    exp = json.loads((GOLDEN / f"{name}.expected.json").read_text())
    signals = run_eval.checks.run_checks(_golden(name), run_eval.BRIEF, RULES, check_links=False)["signals"]
    assert run_eval.validate.review_problems(review, {"signals": signals}, TH, RULES) == []
    got = run_eval.gate_names(run_eval.validate.validate({"hard": []}, review, TH, RULES))
    return got, run_eval.unexplained_gate_failures(got, set(exp["expected_gate_failures"]), exp.get("allowed_extra_gate_failures", {}))


def test_no_perspective_with_verified_claims_fails_only_its_seeded_gate():
    got, unexplained = _eval_gates("defect-no-perspective", MOCK_REVIEWS["defect-no-perspective"])
    assert got == {"originality", "total"} and unexplained == []


def test_uncited_true_claim_marked_unsupported_is_still_reported_unexplained():
    """The recorded failing shape (post4 run 3): factual_correctness passed, Check 8 items pass, one UNSUPPORTED claim.
    The eval must keep flagging this, not excuse it."""
    rev = _review(**{**NO_PERSPECTIVE, "claims": (WCAG, UNCITED_TRUE)})
    assert rev["factual_correctness"]["passed"] and all(c["pass"] for c in rev["checklist"] if c["item"] in ("factual_accuracy", "no_unsupported_claims"))
    got, unexplained = _eval_gates("defect-no-perspective", rev)
    assert "factual_correctness" in got and unexplained == ["factual_correctness"]


def test_unsupported_claim_fails_the_gate_even_when_factual_correctness_passes():
    """The claim gate is independent of the reviewer's own factual verdict, so a contradictory review fails closed."""
    r = run_eval.validate.validate({"hard": []}, _review(claims=(WCAG, UNCITED_TRUE)), TH, RULES)
    assert r["status"] == "FAILED" and any(g.startswith("claim:") for g in r["gate_failures"])


def test_genuine_factual_failure_is_explained_only_by_its_declared_gates():
    got, unexplained = _eval_gates("defect-false-claim", MOCK_REVIEWS["defect-false-claim"])
    assert {"factual_correctness", "technical_accuracy"} <= got and unexplained == []
    assert run_eval.unexplained_gate_failures(got, {"factual_correctness"}, {}) == ["technical_accuracy"]  # undeclared extra still fails


def test_unsourced_statistic_still_fails_the_factual_gate():
    got, unexplained = _eval_gates("defect-unsupported-claim", MOCK_REVIEWS["defect-unsupported-claim"])
    assert "factual_correctness" in got and unexplained == []


def _run_main(monkeypatch, tmp_path, reviews):
    monkeypatch.setattr(run_eval, "run_reviewer", lambda d, m, f=None: json.dumps(reviews[Path(d).stem]))
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--diag-dir", str(tmp_path)])
    return run_eval.main()


def test_eval_passes_on_consistent_reviews_of_all_six_fixtures(monkeypatch, tmp_path, capsys):
    assert set(MOCK_REVIEWS) == {p.stem for p in GOLDEN.glob("*.md")}  # every fixture is in the set
    assert _run_main(monkeypatch, tmp_path, MOCK_REVIEWS) == 0
    out = capsys.readouterr().out
    assert "Fixtures: 6; valid reviews: 6; not reviewed: 0" in out and "recall: 5/5 (missed by a valid review: 0; not reviewed: 0)" in out
    assert "false-positive rate on good drafts: 0/1 (not reviewed: 0)" in out
    assert "Unexplained gate failures: 0 sample(s)" in out and "Not reviewed after retries: 0/6" in out


def test_eval_fails_when_no_perspective_review_marks_an_uncited_true_claim_unsupported(monkeypatch, tmp_path, capsys):
    reviews = {**MOCK_REVIEWS, "defect-no-perspective": _review(**{**NO_PERSPECTIVE, "claims": (WCAG, UNCITED_TRUE)})}
    assert _run_main(monkeypatch, tmp_path, reviews) == 1
    assert "{'defect-no-perspective.md': ['factual_correctness']}" in capsys.readouterr().out


def test_reviewer_rule_separates_claim_truth_from_draft_citation():
    agent = (ROOT / ".claude/agents/blog-reviewer.md").read_text()
    adapter = (ROOT / "config/qed42_review_adapter.md").read_text()
    assert "not whether the draft cites it" in agent and "any such verdict means `factual_correctness.passed` is false" in agent
    assert "only when you cannot find an adequate source for it yourself" in adapter
    assert "needs a source you cannot find" not in adapter  # the ambiguous wording that read as "the draft has no link"
    prompt = run_eval.reviewer_prompt(GOLDEN / "good-01.md")
    assert "not whether the draft cites it" in prompt and "does not cite is SUPPORTED" in prompt


# ---- rejected reviews: retried under the workflow's policy, never silently dropped from the metrics ----
# Before: a review that review_problems rejected (post5 runs 2, 4, 5: defect-tone with a HIGH tone issue on a dimension
# scored 72-74) was still counted for recall, was never retried and did not affect the exit code.
RECORDED = ROOT / "tests/fixtures/eval_reviews"
TONE_REJECTED = json.loads((RECORDED / "defect-tone.rejected-post5-run2.json").read_text())
OBSOLETE_ORIG50 = json.loads((RECORDED / "defect-obsolete-api.originality50-post5-run1.json").read_text())


def _scripted(monkeypatch, per_sample):
    """run_reviewer mock: per_sample maps a fixture stem to a list of outputs, one per attempt (the last repeats).
    Other fixtures get their consistent MOCK_REVIEWS entry. Returns the recorded (stem, feedback) calls."""
    calls = []

    def fake(d, m, f=None):
        stem = Path(d).stem
        calls.append((stem, f))
        seq = per_sample.get(stem)
        if seq is None:
            return json.dumps(MOCK_REVIEWS[stem])
        n = sum(1 for c in calls if c[0] == stem) - 1
        out = seq[min(n, len(seq) - 1)]
        return out if isinstance(out, str) else json.dumps(out)
    monkeypatch.setattr(run_eval, "run_reviewer", fake)
    return calls


def _main(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--diag-dir", str(tmp_path / "diag")])
    return run_eval.main()


def _tone_with(audience_fit):
    rev = json.loads(json.dumps(TONE_REJECTED))
    rev["scores"]["audience_fit"]["score"] = audience_fit
    return rev


def test_recorded_tone_review_is_rejected_for_its_high_issue_above_the_cap():
    """Confirmed cause: the HIGH tone issue is on audience_fit (Check 1: pitch tone) but audience_fit is 74 > 70."""
    probs = run_eval.acceptance_problems(GOLDEN / "defect-tone.md", TONE_REJECTED)
    assert probs == ["issue i1 is HIGH on audience_fit but scores.audience_fit is 74 (max 70 allowed with a HIGH/CRITICAL issue)"]
    assert run_eval.acceptance_problems(GOLDEN / "defect-tone.md", _tone_with(65)) == []


def test_inconsistent_review_is_retried_with_its_reason_and_the_recovery_is_counted(monkeypatch, tmp_path, capsys):
    calls = _scripted(monkeypatch, {"defect-tone": [TONE_REJECTED, _tone_with(65)]})
    assert _main(monkeypatch, tmp_path) == 0
    tone_calls = [f for stem, f in calls if stem == "defect-tone"]
    assert tone_calls[0] is None and len(tone_calls) == 2
    fb = tone_calls[1]
    assert "Rejected at consistency: issue i1 is HIGH on audience_fit but scores.audience_fit is 74" in fb
    assert "Do not change a judgment only to pass validation" in fb and '"audience_fit"' in fb  # rejected output included
    diag = json.loads((tmp_path / "diag/defect-tone.attempt1.failed.json").read_text())
    assert diag["stage"] == "consistency" and "max 70" in diag["detail"]
    out = capsys.readouterr().out
    assert "Rejected attempts (malformed or inconsistent, retried up to 2 times): 1 across 1/6 fixture(s)" in out
    assert "Fixtures: 6; valid reviews: 6; not reviewed: 0" in out
    row = next(json.loads(l) for l in out.splitlines() if l.startswith('{"sample": "defect-tone.md"'))
    assert row["attempts"] == 2 and row["rejected_attempts"][0].startswith("consistency: issue i1 is HIGH")


def test_review_still_inconsistent_after_retries_fails_the_eval_and_keeps_its_denominator(monkeypatch, tmp_path, capsys):
    _scripted(monkeypatch, {"defect-tone": [TONE_REJECTED]})
    assert _main(monkeypatch, tmp_path) == 1
    for k in range(1, run_eval.MAX_ATTEMPTS + 1):
        assert json.loads((tmp_path / f"diag/defect-tone.attempt{k}.failed.json").read_text())["stage"] == "consistency"
    out = capsys.readouterr().out
    assert "Fixtures: 6; valid reviews: 5; not reviewed: 1 ['defect-tone.md']" in out
    assert "recall: 4/5 (missed by a valid review: 0; not reviewed: 1)" in out and "'tone': '0/1'" in out
    assert f"defect-tone.md: NOT REVIEWED after {run_eval.MAX_ATTEMPTS} attempt(s) ({run_eval.MAX_ATTEMPTS - 1} retries)" in out
    assert "defect-tone.attempt3.failed.json" in out and "Not reviewed after retries: 1/6" in out
    row = next(json.loads(l) for l in out.splitlines() if l.startswith('{"sample": "defect-tone.md"'))
    assert row["status"] == "NOT_REVIEWED" and row["retries"] == 2 and "max 70" in row["reason"]


def test_valid_review_that_misses_the_defect_is_a_miss_not_a_failed_review(monkeypatch, tmp_path, capsys):
    missed = _review(scores={"audience_fit": 80})  # consistent, but no HIGH tone issue
    _scripted(monkeypatch, {"defect-tone": [missed]})
    assert _main(monkeypatch, tmp_path) == 0
    out = capsys.readouterr().out
    assert "recall: 4/5 (missed by a valid review: 1; not reviewed: 0)" in out and "not reviewed: 0 []" in out


def test_unreviewed_good_draft_stays_in_the_false_positive_denominator(monkeypatch, tmp_path, capsys):
    _scripted(monkeypatch, {"good-01": ["prose, not json"]})
    assert _main(monkeypatch, tmp_path) == 1
    out = capsys.readouterr().out
    assert "false-positive rate on good drafts: 0/1 (not reviewed: 1)" in out


def test_unreviewed_defect_counts_as_undetected_gate(monkeypatch, tmp_path, capsys):
    _scripted(monkeypatch, {"defect-obsolete-api": [{"checklist": [], "issues": [], "summary": "s"}]})  # schema-valid, no scores
    assert _main(monkeypatch, tmp_path) == 1
    out = capsys.readouterr().out
    assert "technical_accuracy 0/1" in out and "recall: 4/5 (missed by a valid review: 0; not reviewed: 1)" in out
    assert "scores missing" in out


def test_failed_checklist_item_without_issue_is_rejected_like_submit_review():
    rev = _review()
    rev["checklist"][0] = {"item": rev["checklist"][0]["item"], "pass": False, "evidence": "e"}
    assert run_eval.acceptance_problems(GOLDEN / "good-01.md", rev) == \
        [f"failed checklist items reference no known issue id: ['{rev['checklist'][0]['item']}']"]


# ---- score consistency is stated to the reviewer with the number the code enforces ----
def test_consistency_section_is_generated_from_thresholds():
    text = run_eval.validate.consistency_section(TH, RULES)
    assert f"at most {TH['max_score_with_high_issue']}" in text and "technical_accuracy, originality are hard gates" in text
    assert "Never lower a severity to keep a score" in text
    th = json.loads(json.dumps(TH)); th["max_score_with_high_issue"] = 65
    assert "at most 65" in run_eval.validate.consistency_section(th, RULES)
    assert run_eval.validate.consistency_section(TH, {**RULES, "rubric": None}) == ""
    gates = TH["hard_gates"]
    assert str(gates["min_total_score"]) not in text  # the total pass mark stays hidden
    # Each hard-gate minimum is a number the code now rejects on (below it needs a HIGH issue), so the reviewer is told it.
    m = gates["min_dimension_percentage"]
    assert f"technical_accuracy {m}, originality {m}." in text and "below its minimum with no HIGH/CRITICAL issue" in text
    th = json.loads(json.dumps(TH)); th["hard_gates"]["min_dimension_percentage"] = 55
    assert "technical_accuracy 55, originality 55." in run_eval.validate.consistency_section(th, RULES)


def test_eval_and_workflow_prompts_carry_the_consistency_section():
    prompt = run_eval.reviewer_prompt(GOLDEN / "good-01.md")
    assert "## Score consistency" in prompt and f"at most {TH['max_score_with_high_issue']}" in prompt
    blog_src = (ROOT / "scripts/blog.py").read_text()
    assert '"## Score consistency", consistency_section(thresholds(root), rules(root))' in blog_src


def test_adapter_maps_tone_and_words_to_a_dimension():
    """Cause of the tone rejections: the adapter mapped no dimension for tone or check 7, the reviewer improvised one
    (audience_fit / structure_clarity) and was never told the numeric cap."""
    adapter = (ROOT / "config/qed42_review_adapter.md").read_text()
    assert "Tone and voice issues keep `category: tone`; only their dimension varies" in adapter
    assert "(hype, pitch or vendor tone) → `audience_fit`" in adapter
    assert "sentence-level voice findings (V1 to V3) → `structure_clarity`" in adapter
    assert "Check 7 issues keep `category: words` → `structure_clarity`" in adapter
    # Regression (post6 runs 2-4): citing "Check 1 question 2" in the mapping moved the hype issue's category from tone
    # to audience, because categories follow the check that found the issue. The mapping must not name another check.
    tone_rule = adapter[adapter.index("Tone and voice issues"):adapter.index("Check 7 issues")]
    assert "Check 1" not in tone_rule
    skill = (ROOT / ".claude/skills/review/SKILL.md").read_text()
    assert "slip into pitch or vendor tone" in skill  # Check 1 treats pitch tone as an audience-fit concern


# ---- originality is scored independently of correctness ----
def test_obsolete_api_fixture_shares_every_originality_bearing_line_with_good_01():
    """Only the CSS example and its lead-in differ, so the article's perspective and insight are identical."""
    changed = [l[1:] for l in _changed_lines("defect-obsolete-api")]
    assert all(("token(" in l or "$" in l or l.strip() == "" or l.strip().startswith("--") or "var(--" in l) for l in changed)
    insight = "The repeat count and the planned changes decide the payoff, not the size of the company."
    assert insight in _golden("good-01") and insight in _golden("defect-obsolete-api")


def test_reviewer_rubric_separates_originality_from_correctness():
    agent = (ROOT / ".claude/agents/blog-reviewer.md").read_text()
    adapter = (ROOT / "config/qed42_review_adapter.md").read_text()
    assert "Originality and correctness are separate dimensions" in agent
    assert "lowers technical_accuracy, examples_implementation and factual_correctness, not originality" in agent
    assert "Check 10 (beats the docs) judges what the article adds beyond the reference page, not whether that addition is correct" in agent
    assert "Checks 10 and 11 judge insight, not correctness" in adapter
    prompt = run_eval.reviewer_prompt(GOLDEN / "defect-obsolete-api.md")
    assert "Originality and correctness are separate dimensions" in prompt and "never lowers `originality`" in prompt


def test_accuracy_high_issue_caps_only_its_own_dimension():
    rev = _review(scores={"technical_accuracy": 40, "originality": 70}, factual=False,
                  issues=[_issue(1, "accuracy", "technical_accuracy")], failed=("code_correctness",))
    assert run_eval.validate.review_problems(rev, {"signals": {"verifiable_claims": True}}, TH, RULES) == []


def test_obsolete_api_review_with_good_01_originality_fails_only_its_seeded_gates():
    got, unexplained = _eval_gates("defect-obsolete-api", MOCK_REVIEWS["defect-obsolete-api"])
    assert "originality" not in got and unexplained == []


def test_recorded_originality_50_review_is_rejected_not_accepted():
    """post5 run 1: originality 50 with only a MEDIUM originality issue and both originality checks passing. Before, it was
    accepted and surfaced only as an unexplained gate. Now the contradiction is rejected at acceptance and retried; the
    gate threshold and the eval's expectations are unchanged."""
    assert run_eval.acceptance_problems(GOLDEN / "defect-obsolete-api.md", OBSOLETE_ORIG50) == [
        "scores.originality is 50, below the originality hard-gate minimum 60, but no HIGH/CRITICAL issue has dimension "
        "'originality': a failing hard-gate score needs a failing issue on that dimension"]
    orig = [i for i in OBSOLETE_ORIG50["issues"] if i.get("dimension") == "originality"]
    assert [i["severity"] for i in orig] == ["MEDIUM"]
    assert {c["item"]: c["pass"] for c in OBSOLETE_ORIG50["checklist"]}["original_insight"] is True
    exp = json.loads((GOLDEN / "defect-obsolete-api.expected.json").read_text())
    assert "originality" not in exp.get("allowed_extra_gate_failures", {}) and TH["hard_gates"]["min_dimension_percentage"] == 60


# ---- hard-gate scores must be explained by a failing issue (the converse of the HIGH-issue cap) ----
# Root cause (post2-post7, 185 recorded reviews): every originality score below 60 without a HIGH originality issue
# came from a review whose originality checks passed with at most a MEDIUM flag, the same outcome as reviews of the
# same text scored 60-74. The score drifted inside the "flag" band, which straddles the gate; nothing tied it to the checks.
ORIG55_POST7 = json.loads((RECORDED / "defect-obsolete-api.originality55-post7-run3.json").read_text())
NO_PERSPECTIVE_POST7 = json.loads((RECORDED / "defect-no-perspective.originality25-post7-run3.json").read_text())
UNEXPLAINED_GATE = "below the originality hard-gate minimum 60, but no HIGH/CRITICAL issue has dimension 'originality'"


def _obsolete(originality, orig_issue_severity="MEDIUM"):
    """A defect-obsolete-api review: broken CSS (HIGH accuracy on technical_accuracy, failed code check), the article's
    insight unchanged (originality checks pass), plus one originality issue of the given severity."""
    base = MOCK_REVIEWS["defect-obsolete-api"]
    return {**base, "scores": {**base["scores"], "originality": {"score": originality, "evidence": "e"}},
            "issues": base["issues"] + [_issue(2, "originality", "originality", orig_issue_severity)]}


def test_recorded_post7_originality_55_review_is_rejected():
    """post7 run 3, the one failing run: originality 55, both originality checks pass, one MEDIUM originality issue."""
    assert {c["item"]: c["pass"] for c in ORIG55_POST7["checklist"] if c["item"] in ("beats_the_docs", "original_insight")} \
        == {"beats_the_docs": True, "original_insight": True}
    probs = run_eval.acceptance_problems(GOLDEN / "defect-obsolete-api.md", ORIG55_POST7)
    assert len(probs) == 1 and "scores.originality is 55, " + UNEXPLAINED_GATE in probs[0]


def test_technically_broken_but_original_article_keeps_a_passing_originality_and_fails_only_accuracy_gates():
    rev = _obsolete(66)
    got, unexplained = _eval_gates("defect-obsolete-api", rev)
    assert got == {"technical_accuracy", "factual_correctness", "total"} and unexplained == []
    assert run_eval.acceptance_problems(GOLDEN / "defect-obsolete-api.md", _obsolete(54)) and \
        UNEXPLAINED_GATE in run_eval.acceptance_problems(GOLDEN / "defect-obsolete-api.md", _obsolete(54))[0]


def test_genuinely_generic_article_still_fails_the_originality_gate():
    for rev in (MOCK_REVIEWS["defect-no-perspective"], NO_PERSPECTIVE_POST7):
        assert run_eval.acceptance_problems(GOLDEN / "defect-no-perspective.md", rev) == []
        gates = run_eval.gate_names(run_eval.validate.validate({"hard": []}, rev, TH, RULES))
        assert "originality" in gates
    assert NO_PERSPECTIVE_POST7["scores"]["originality"]["score"] < 60


def test_low_score_supported_by_a_failing_issue_is_accepted_and_reported_not_excused():
    """A reviewer that genuinely judges the insight a fail raises a HIGH originality issue: the review is valid, the gate
    fails, and on this fixture the eval still reports it as unexplained (a real judgment disagreement, not suppressed)."""
    rev = _obsolete(50, "HIGH")
    assert run_eval.acceptance_problems(GOLDEN / "defect-obsolete-api.md", rev) == []
    got, unexplained = _eval_gates("defect-obsolete-api", rev)
    assert "originality" in got and unexplained == ["originality"]


def test_eval_retries_an_unexplained_hard_gate_score_and_counts_the_rejection(monkeypatch, tmp_path, capsys):
    calls = _scripted(monkeypatch, {"defect-obsolete-api": [ORIG55_POST7, _obsolete(64)]})
    assert _main(monkeypatch, tmp_path) == 0
    fb = [f for stem, f in calls if stem == "defect-obsolete-api"][1]
    assert "Rejected at consistency: scores.originality is 55" in fb and "if a hard-gate score really fails" in fb
    assert "Do not change a judgment only to pass validation" in fb
    out = capsys.readouterr().out
    assert "Rejected attempts (malformed or inconsistent, retried up to 2 times): 1 across 1/6 fixture(s)" in out
    assert "Unexplained gate failures: 0 sample(s)" in out
    row = next(json.loads(l) for l in out.splitlines() if l.startswith('{"sample": "defect-obsolete-api.md"'))
    assert row["attempts"] == 2 and row["hard_gate_scores"]["originality"] == 64
    assert row["originality_checks"] == {"beats_the_docs": True, "original_insight": True}


def test_eval_fails_when_the_unexplained_low_score_persists(monkeypatch, tmp_path, capsys):
    _scripted(monkeypatch, {"defect-obsolete-api": [ORIG55_POST7]})
    assert _main(monkeypatch, tmp_path) == 1
    out = capsys.readouterr().out
    assert "Fixtures: 6; valid reviews: 5; not reviewed: 1 ['defect-obsolete-api.md']" in out
    assert "technical_accuracy 0/1" in out and "recall: 4/5 (missed by a valid review: 0; not reviewed: 1)" in out


def test_eval_fails_when_the_retry_raises_a_high_originality_issue(monkeypatch, tmp_path, capsys):
    _scripted(monkeypatch, {"defect-obsolete-api": [ORIG55_POST7, _obsolete(50, "HIGH")]})
    assert _main(monkeypatch, tmp_path) == 1
    assert "Unexplained gate failures: 1 sample(s) {'defect-obsolete-api.md': ['originality']}" in capsys.readouterr().out


def test_eval_self_check_covers_both_consistency_directions(capsys, monkeypatch, tmp_path):
    assert run_eval.self_check_consistency() is True
    _scripted(monkeypatch, {})
    _main(monkeypatch, tmp_path)
    assert "unexplained below-minimum hard-gate score correctly rejected: yes" in capsys.readouterr().out


def test_rubric_ties_originality_to_its_checks_and_excludes_missing_experience():
    prompt = run_eval.reviewer_prompt(GOLDEN / "good-01.md")
    assert "Score originality from Checks 10 and 11. When both pass" in prompt
    assert "The absence of first-hand experience, measured results or a worked example is not an originality defect" in prompt
    assert "only a fail can put a hard-gate dimension below its minimum" in prompt
    assert "A hard-gate score below its minimum is a failing judgment" in prompt
    for banned in ("token(", "design tokens", "obsolete"):  # general rubric text, nothing fixture-specific
        agent = (ROOT / ".claude/agents/blog-reviewer.md").read_text()
        assert banned not in agent.lower()


# ---- one issue per check: a passage that fails two checks gets one issue per check (post8 runs 1 and 4) ----
def test_adapter_requires_one_issue_per_failed_check():
    """post8 runs 1 and 4 filed the false token() claim only as `code`, so it failed factual_accuracy but counted as a
    recall miss for `accuracy`. The adapter now says one issue covers one check."""
    adapter = (ROOT / "config/qed42_review_adapter.md").read_text()
    rule = "One issue covers one check: when the same passage fails two checks"
    assert rule in adapter and "raise one issue per check, each with that check's category" in adapter
    assert rule in run_eval.reviewer_prompt(GOLDEN / "defect-obsolete-api.md")
    assert "token(" not in adapter  # general wording, not fixture-specific


def test_code_only_categorisation_is_still_a_recall_miss(monkeypatch, tmp_path, capsys):
    """The metric is unchanged: a review that files the false claim only under `code` misses `accuracy`."""
    code_only = json.loads(json.dumps(MOCK_REVIEWS["defect-obsolete-api"]))
    code_only["issues"][0]["category"] = "code"
    _scripted(monkeypatch, {"defect-obsolete-api": [code_only]})
    assert _main(monkeypatch, tmp_path) == 0
    assert "recall: 4/5 (missed by a valid review: 1; not reviewed: 0)" in capsys.readouterr().out


# ---- infrastructure failures are labelled apart from rejected reviewer output; the exit code is unchanged ----
def _outage(monkeypatch, per_sample):
    """run_reviewer mock: per_sample maps a stem to a list of outputs or exceptions, one per attempt."""
    seen = {}

    def fake(d, m, f=None):
        stem = Path(d).stem
        seq = per_sample.get(stem)
        if seq is None:
            return json.dumps(MOCK_REVIEWS[stem])
        n = seen[stem] = seen.get(stem, -1) + 1
        out = seq[min(n, len(seq) - 1)]
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, str) else json.dumps(out)
    monkeypatch.setattr(run_eval, "run_reviewer", fake)


def test_cli_outage_is_labelled_infrastructure_and_still_fails_the_run(monkeypatch, tmp_path, capsys):
    _outage(monkeypatch, {"good-01": [RuntimeError("claude exited 1: API Error: overloaded")]})
    assert _main(monkeypatch, tmp_path) == 1
    out = capsys.readouterr().out
    assert "good-01.md: NOT REVIEWED after 3 attempt(s) (2 retries), cause: infrastructure." in out
    assert ("Infrastructure failures (claude process error or timeout, not the reviewer's output): 3 attempt(s) across "
            "1/6 fixture(s) {'good-01.md': 3}; not reviewed because of infrastructure: ['good-01.md']; "
            "because of reviewer output: []") in out
    assert "false-positive rate on good drafts: 0/1 (not reviewed: 1)" in out  # denominator kept
    row = next(json.loads(l) for l in out.splitlines() if l.startswith('{"sample": "good-01.md"'))
    assert row["cause"] == "infrastructure" and row["attempt_stages"] == ["process"] * 3


def test_reviewer_output_failure_is_labelled_reviewer(monkeypatch, tmp_path, capsys):
    _outage(monkeypatch, {"good-01": ["prose, not json"]})
    assert _main(monkeypatch, tmp_path) == 1
    out = capsys.readouterr().out
    assert "cause: reviewer." in out and "0 attempt(s) across 0/6 fixture(s) {}" in out
    assert "because of reviewer output: ['good-01.md']" in out


def test_mixed_failure_reports_every_attempt_stage_and_the_final_cause(monkeypatch, tmp_path, capsys):
    """post8 run 9 shape: malformed JSON first, then the CLI failed on both retries."""
    _outage(monkeypatch, {"defect-unsupported-claim": ['{"checklist": [', RuntimeError("claude exited 1: ")]})
    assert _main(monkeypatch, tmp_path) == 1
    out = capsys.readouterr().out
    row = next(json.loads(l) for l in out.splitlines() if l.startswith('{"sample": "defect-unsupported-claim.md"'))
    assert row["attempt_stages"] == ["json_syntax", "process", "process"] and row["cause"] == "infrastructure"
    assert "{'defect-unsupported-claim.md': 2}" in out


def test_process_failure_detail_falls_back_to_stdout(monkeypatch):
    """post8's outage left stderr empty ("claude exited 1: "); the CLI's stdout explains it."""
    monkeypatch.setattr(run_eval.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "API Error: 529", ""))
    with pytest.raises(RuntimeError, match="claude exited 1: API Error: 529"):
        run_eval.run_reviewer(GOLDEN / "good-01.md", "sonnet")


# ---- claim verdict accuracy ----
def test_expected_claims_are_matched_by_substring_and_reported_with_the_reviewers_verdict():
    rev = {"claim_checks": [
        {"claim": "WCAG minimum contrast ratio of 4.5:1 for body text", "verdict": "SUPPORTED"},
        {"claim": "CSS now has a native `token()` function", "verdict": "SUPPORTED"}]}
    exp = {"wcag MINIMUM contrast": "SUPPORTED", "native `token()`": "CONTRADICTED", "37% faster": "UNSUPPORTED"}
    assert run_eval.claim_verdicts(rev, exp) == [("wcag MINIMUM contrast", "SUPPORTED", "SUPPORTED"),
                                                 ("native `token()`", "CONTRADICTED", "SUPPORTED"),
                                                 ("37% faster", "UNSUPPORTED", None)]
    assert run_eval.claim_verdicts({}, exp)[0][2] is None


def test_every_expected_claim_key_occurs_in_its_golden_draft_and_uses_a_known_verdict():
    for exp_path in GOLDEN.glob("*.expected.json"):
        draft = (GOLDEN / exp_path.name.replace(".expected.json", ".md")).read_text().lower()
        for key, verdict in json.loads(exp_path.read_text()).get("expected_claims", {}).items():
            assert key.lower() in draft, (exp_path.name, key)
            assert verdict in ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED")
