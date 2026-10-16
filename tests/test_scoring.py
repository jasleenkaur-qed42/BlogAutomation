import copy
import json
import shutil
from pathlib import Path

import pytest
from conftest import DIMS, SRC, LONG, SECTION, make_draft, make_review, make_scores, issue

import blog
import checks
import validate
from common import ROOT, load_json, schema_errors

RULES = load_json(ROOT / "config" / "rules.json")
TH = load_json(ROOT / "config" / "thresholds.json")
BRIEF = {"primary_keyword": "design tokens", "secondary_keywords": ["design system", "css variables"],
         "target_words": {"min": 700, "max": 1100}}
CLEAN = {"hard": [], "signals": {}}


def gate(review, checks_=CLEAN, th=TH, rules=RULES):
    return validate.validate(checks_, review, th, rules)


def dim_issue(sev="HIGH", dim="technical_accuracy", id_="i1"):
    return {**issue(id_, sev, "accuracy"), "dimension": dim}


# ---- config ----
def test_rubric_weights_sum_to_100_and_gate_dims_exist():
    assert sum(RULES["rubric"].values()) == 100
    assert set(RULES["hard_gate_dimensions"]) <= set(RULES["rubric"])
    assert validate.config_errors(TH, RULES) == []
    assert set(DIMS) == set(RULES["rubric"])


@pytest.mark.parametrize("path,value", [
    (("hard_gates", "min_total_score"), 101), (("hard_gates", "min_total_score"), -1),
    (("hard_gates", "min_dimension_percentage"), 150), (("hard_gates", "min_claim_checks"), -1),
    (("hard_gates", "min_claim_checks"), 1.5), (("hard_gates", "factual_correctness"), "yes"),
    (("max_score_with_high_issue",), 101)])
def test_threshold_ranges_validated(path, value):
    th = copy.deepcopy(TH)
    tgt = th
    for k in path[:-1]:
        tgt = tgt[k]
    tgt[path[-1]] = value
    assert validate.config_errors(thresholds=th)


def test_rules_config_errors():
    r = copy.deepcopy(RULES); r["hard_gate_dimensions"] = ["technical_correctness"]
    assert validate.config_errors(rules=r)
    r = copy.deepcopy(RULES); r["rubric"]["seo"] = 4
    assert validate.config_errors(rules=r)


def test_bad_config_raises_on_load(root):
    p = root / "config" / "thresholds.json"
    th = json.loads(p.read_text()); th["hard_gates"]["min_total_score"] = 500
    p.write_text(json.dumps(th))
    with pytest.raises(blog.BlogError):
        blog.thresholds(root)


# ---- gate semantics ----
def test_full_valid_review_passes():
    r = gate(make_review())
    assert r["status"] == "PASSED" and r["weighted_total"] == 85 and r["gate_failures"] == []


@pytest.mark.parametrize("over,expect", [
    ({"technical_accuracy": 59}, "gate:technical_accuracy:below_min"),
    ({"originality": 59}, "gate:originality:below_min")])
def test_hard_gate_dimension_fails_even_when_total_is_high(over, expect):
    r = gate(make_review(scores=make_scores(**over)))
    assert r["status"] == "FAILED" and expect in r["gate_failures"] and "gate:total" not in r["gate_failures"]
    assert r["weighted_total"] >= 75


def test_total_below_threshold_fails_even_when_gates_pass():
    scores = {d: {"score": 65, "evidence": "e"} for d in DIMS}
    scores["technical_accuracy"]["score"] = scores["originality"]["score"] = scores["seo"]["score"] = 90
    r = gate(make_review(scores=scores))
    assert r["status"] == "FAILED" and r["gate_failures"] == ["gate:total"] and r["weighted_total"] < 75


def test_borderline_total_uses_unrounded_exact_math():
    at = {d: {"score": 75, "evidence": "e"} for d in DIMS}
    th = {**TH, "hard_gates": {**TH["hard_gates"], "min_dimension_scores": {}}}   # isolate the total gate
    gate = lambda r: validate.validate(CLEAN, r, th, RULES)  # noqa: E731
    assert gate(make_review(scores=at))["status"] == "PASSED"      # exactly 75.0
    below = copy.deepcopy(at); below["technical_accuracy"]["score"] = 74.8   # 74.96
    r = gate(make_review(scores=below))
    assert r["status"] == "FAILED" and r["gate_failures"] == ["gate:total"]


def test_factual_correctness_gate_independent():
    r = gate(make_review(factual=False))
    assert r["status"] == "FAILED" and r["gate_failures"] == ["gate:factual_correctness"]
    assert r["weighted_total"] == 85


@pytest.mark.parametrize("verdict", ["UNSUPPORTED", "CONTRADICTED"])
def test_bad_claim_fails_gate(verdict):
    cc = [{"claim": "Firebase improves startup time by 37%", "source": None, "verdict": verdict, "evidence": "e"}]
    r = gate(make_review(claim_checks=cc))
    assert r["status"] == "FAILED" and r["gate_failures"][0].startswith("claim:")
    ok = [{**cc[0], "verdict": "SUPPORTED", "source": "https://firebase.google.com/docs"}]
    assert gate(make_review(claim_checks=ok))["status"] == "PASSED"


def test_reviewer_decision_field_never_overrides_gate():
    r = gate(make_review(scores=make_scores(technical_accuracy=40), decision="PASS", verdict="PASS"))
    assert r["status"] == "FAILED"


def test_no_rubric_keeps_old_behavior():
    rules = {k: v for k, v in RULES.items() if k != "rubric"}
    review = {k: v for k, v in make_review().items() if k not in ("scores", "factual_correctness", "claim_checks")}
    assert gate(review, rules=rules)["status"] == "PASSED"
    assert validate.review_problems(review, CLEAN, TH, rules) == []


def test_gate_is_pure():
    r = make_review(scores=make_scores(originality=50))
    r0 = copy.deepcopy(r)
    assert gate(r) == gate(r) and r == r0


# ---- malformed reviews ----
def problems(review, signals=None):
    return validate.review_problems(review, {"hard": [], "signals": signals or {}}, TH, RULES)


def test_valid_review_has_no_problems():
    assert problems(make_review()) == []


def test_missing_and_out_of_range_scores_are_malformed():
    r = make_review(); del r["scores"]["seo"]
    assert any("scores.seo" in p for p in problems(r))
    r = make_review(scores=make_scores(seo=101))
    assert any("scores.seo" in p for p in problems(r))
    r = make_review(); del r["scores"]
    assert any("scores missing" in p for p in problems(r))
    r = make_review(); del r["factual_correctness"]
    assert any("factual_correctness" in p for p in problems(r))


def test_high_issue_with_dimension_and_high_score_is_malformed():
    r = make_review([dim_issue()], scores=make_scores(technical_accuracy=90))
    assert any("technical_accuracy" in p for p in problems(r))
    r = make_review([dim_issue()], scores=make_scores(technical_accuracy=50))
    assert problems(r) == []


def test_high_issue_without_dimension_is_accepted():
    r = make_review([issue("i1", "HIGH", "structure", "intro", "The introduction is too verbose.")])
    assert problems(r) == []
    assert problems(make_review([dim_issue("MEDIUM")], scores=make_scores(technical_accuracy=90))) == []


def unexplained(review, th=TH, rules=RULES):
    return [p for p in validate.review_problems(review, CLEAN, th, rules) if "hard-gate minimum" in p]


@pytest.mark.parametrize("dim", ["technical_accuracy", "originality"])
def test_hard_gate_below_minimum_needs_a_failing_issue_on_that_dimension(dim):
    low = make_scores(**{dim: 55})
    assert unexplained(make_review(scores=low))                                      # no issue at all
    assert unexplained(make_review([dim_issue("MEDIUM", dim)], scores=low))          # only a flag
    assert unexplained(make_review([dim_issue("LOW", dim)], scores=low))
    other = "originality" if dim == "technical_accuracy" else "technical_accuracy"
    assert unexplained(make_review([dim_issue("HIGH", other)], scores=low))          # blocking issue elsewhere
    assert unexplained(make_review([issue("i1", "HIGH", "originality")], scores=low))  # no dimension: cannot explain it
    for sev in ("HIGH", "CRITICAL"):
        assert problems(make_review([dim_issue(sev, dim)], scores=low)) == []


def test_hard_gate_at_or_above_minimum_with_only_a_flag_is_accepted():
    m = TH["hard_gates"]["min_dimension_percentage"]
    assert problems(make_review([dim_issue("MEDIUM", "originality")], scores=make_scores(originality=m))) == []
    assert unexplained(make_review(scores=make_scores(originality=m - 0.5)))         # exact comparison, no rounding


def test_rule_covers_only_hard_gate_dimensions():
    """seo has its own minimum (80) above the HIGH cap (70) and is not a hard gate; low non-gate scores stay legal."""
    assert problems(make_review(scores=make_scores(seo=70, technical_depth=30, audience_fit=10))) == []


def test_rule_uses_configured_gates_not_a_hardcoded_number():
    th = copy.deepcopy(TH); th["hard_gates"]["min_dimension_percentage"] = 50
    assert unexplained(make_review(scores=make_scores(originality=55)), th) == []
    th["hard_gates"]["min_dimension_scores"] = {"originality": 70}                   # stricter per-dimension minimum
    assert "minimum 70" in unexplained(make_review(scores=make_scores(originality=65)), th)[0]
    rules = {**RULES, "hard_gate_dimensions": ["technical_depth"]}
    assert unexplained(make_review(scores=make_scores(originality=10)), TH, rules) == []
    assert unexplained(make_review(scores=make_scores(technical_depth=10)), TH, rules)
    assert validate.review_problems(make_review(scores=make_scores(originality=10)), CLEAN, TH, {**RULES, "rubric": None}) == []


def test_rule_rejects_the_review_but_never_changes_the_gate():
    """The gate is still computed from the raw score: an inconsistent review is not turned into a pass."""
    r = make_review(scores=make_scores(originality=55))
    assert unexplained(r)
    g = gate(r)
    assert g["status"] == "FAILED" and "gate:originality:below_min" in g["gate_failures"]


def test_hard_gate_minimums_follow_config():
    assert validate.hard_gate_minimums(TH, RULES) == {"technical_accuracy": 60, "originality": 60}


def test_unknown_issue_dimension_is_malformed():
    assert problems(make_review([dim_issue(dim="technical_correctness")]))


def test_claim_checks_backstop():
    assert problems(make_review(), {"verifiable_claims": False}) == []           # purely conceptual: empty is fine
    assert any("claim_checks" in p for p in problems(make_review(), {"verifiable_claims": True}))
    one = [{"claim": "c", "source": "https://x.dev", "verdict": "SUPPORTED", "evidence": "e"}]
    assert problems(make_review(claim_checks=one), {"verifiable_claims": True}) == []
    th = copy.deepcopy(TH); th["hard_gates"]["min_claim_checks"] = 2
    assert validate.review_problems(make_review(claim_checks=one), {"signals": {"verifiable_claims": True}}, th, RULES)
    assert validate.review_problems(make_review(), {"signals": {"verifiable_claims": False}}, th, RULES) == []
    r = make_review(); del r["claim_checks"]
    assert any("claim_checks missing" in p for p in problems(r))


def test_review_schema_accepts_scored_review_and_rejects_bad_verdict():
    assert schema_errors(make_review(claim_checks=[{"claim": "c", "source": None, "verdict": "SUPPORTED",
                                                    "evidence": "e"}]), "review") == []
    assert schema_errors(make_review(claim_checks=[{"claim": "c", "source": None, "verdict": "MAYBE",
                                                    "evidence": "e"}]), "review")


# ---- structure and claim trigger checks ----
def ids(text, brief=BRIEF):
    return [h for h in checks.run_checks(text, brief, RULES, check_links=False)["hard"] if h["id"] == "structure"]


def test_good_draft_without_background_section_passes_structure():
    assert ids(make_draft()) == []


def test_h2_count_excludes_conclusion_and_references():
    body = ("# T\n\nA fine introduction paragraph that explains the problem and the reader benefit clearly here.\n\n"
            f"## Something\n{LONG}\n\n## Conclusion\n{SECTION}\n\n## References\n- [a](https://example.com/ok)\n")
    assert any("substantive topic H2" in h["detail"] for h in ids(make_draft(body=body)))


def test_filler_h2_sections_do_not_count():
    body = ("# T\n\nA fine introduction paragraph that explains the problem and the reader benefit clearly here.\n\n"
            f"## One\n{LONG}\n\n## More\nx\n\n## Things\ny\n\n## Conclusion\n{SECTION}\n\n## References\n- a\n")
    assert any("substantive" in h["detail"] for h in ids(make_draft(body=body)))


def test_missing_intro_conclusion_references():
    base = make_draft()
    assert any("introduction" in h["detail"] for h in ids(make_draft(body=base.split("---\n", 2)[2].replace(
        "Small front-end teams often wonder whether design tokens are worth the effort, and this article "
        "explains when they are.", "Hi."))))
    assert any("conclusion" in h["detail"] for h in ids(make_draft(body=base.split("---\n", 2)[2].replace(
        "## Conclusion", "## Closing remarks"))))
    brief = {**BRIEF, "references": {"required": True}}
    no_refs = base.split("---\n", 2)[2].replace("## References", "## Appendix")
    assert any("References" in h["detail"] for h in ids(make_draft(body=no_refs), brief))
    assert not any("References" in h["detail"] for h in ids(make_draft(body=no_refs), {**BRIEF, "references": {"required": False}}))
    assert ids(make_draft(), brief) == []


@pytest.mark.parametrize("body_add,expected", [
    ("", False),
    ("There are three common approaches to naming tokens.", False),
    ("Run the build with ```npm run build``` first.", True),
    ("The v2.1 release changed the default.", True),
    ("Version 4 of the SDK changed it.", True),
    ("This is a 37% faster build on our laptops.", True),
    ("See the published benchmark for numbers.", True)])
def test_verifiable_claims_signal(body_add, expected):
    d = make_draft()
    d = d.replace("## Conclusion", f"{body_add}\n\n## Conclusion", 1)
    assert checks.run_checks(d, BRIEF, RULES, check_links=False)["signals"]["verifiable_claims"] is expected


def test_front_matter_claims_trigger_signal():
    d = make_draft(extra_fm="")
    d = d.replace("claims: []", "claims:\n  - {claim: x, source: 'https://example.com'}")
    assert checks.run_checks(d, BRIEF, RULES, check_links=False)["signals"]["verifiable_claims"] is True


# ---- workflow integration ----
def test_submit_review_rejects_inconsistent_scores(driver):
    driver.write(make_draft())
    r = driver.review(make_review([dim_issue()], scores=make_scores(technical_accuracy=90)))
    assert r["result"] == "MALFORMED" and "technical_accuracy" in r["reason"]


def test_submit_review_rejects_unexplained_hard_gate_score(driver):
    driver.write(make_draft())
    r = driver.review(make_review([dim_issue("MEDIUM", "originality")], scores=make_scores(originality=55)))
    assert r["result"] == "MALFORMED" and "originality hard-gate minimum 60" in r["reason"] and r["retry"] is True


def test_review_pass_claim_computed_by_gate(driver):
    driver.write(make_draft())
    r = driver.review(make_review([dim_issue(dim="originality")], scores=make_scores(originality=40), decision="PASS"))
    assert r["result"] == "ITERATION_FAILED" and any("originality" in x for x in r["reasons"])


def test_scores_recorded_on_pass(driver):
    driver.write(make_draft())
    assert driver.review(make_review())["result"] == "PASSED"
    res = json.loads((driver.root / "runs" / driver.run / "result.json").read_text())
    assert res["weighted_total"] == 85 and res["scores"]["seo"]["score"] == 85


def test_same_gate_failure_is_stagnation_and_total_change_alone_is_not_progress(driver):
    driver.write(make_draft())
    driver.review(make_review([dim_issue()], scores=make_scores(technical_accuracy=50)))
    driver.write(make_draft())
    r = driver.review(make_review([dim_issue()], scores=make_scores(technical_accuracy=58, seo=90)))
    assert r["result"] == "FAILED" and "stagnation" in r["stop_reason"]


def test_gate_total_only_in_signature_when_total_fails(driver):
    driver.write(make_draft())
    driver.review(make_review([dim_issue()], scores=make_scores(technical_accuracy=50)))
    sig = driver.state()["history"][-1]["signature"]
    assert "gate:technical_accuracy:below_min" in sig and "gate:total" not in sig
    driver.write(make_draft())
    low = {d: {"score": 60, "evidence": "e"} for d in DIMS}
    driver.review(make_review(scores={**low, "technical_accuracy": {"score": 90, "evidence": "e"},
                                       "originality": {"score": 90, "evidence": "e"}}))
    assert "gate:total" in driver.state()["history"][-1]["signature"]


def test_rank_key_prefers_higher_total_and_fewer_gate_failures():
    e = lambda **k: {"hard_failures": [], "critical": 0, "high": 0, "failed_checklist": 0, "medium": 0,
                     "low": 0, **k}
    assert blog.rank_key(e(weighted_total=70)) > blog.rank_key(e(weighted_total=80))
    assert blog.rank_key(e(gate_failures=["gate:total"])) > blog.rank_key(e())


def test_reviewer_prompt_lists_rubric(driver):
    driver.write(make_draft())
    rp = Path(driver.next()["prompt"]).read_text()
    assert "## Scoring rubric" in rp and "technical_accuracy (weight 20)" in rp
    assert "min_total_score" not in rp and "75" not in rp.split("## Scoring rubric")[1].split("##")[0]


def _init_brief(root, text, name):
    p = root / "briefs" / name
    p.write_text(text)
    return blog.cmd_init(root, p)


def test_new_brief_fields_and_audience_forms(root):
    fm = (SRC / "briefs" / "firebase-flutter.md")
    st = blog.cmd_init(root, fm)   # mapping audience, original_angle null, reader_takeaway
    assert st["brief"]["original_angle"] is None and st["brief"]["reader_takeaway"]
    str_aud = "---\ntopic: x topic\naudience: Front-end leads\nprimary_keyword: design tokens\ntone: t\n" \
              "target_words: {min: 700, max: 1100}\n---\n"
    assert _init_brief(root, str_aud, "plain.md")["brief"]["audience"] == "Front-end leads"
    bad = str_aud.replace("audience: Front-end leads", "audience: {experience_level: x}")
    with pytest.raises(blog.BlogError):
        _init_brief(root, bad, "bad-aud.md")


def test_example_briefs_pass_schema():
    for name in ("sample.md", "firebase-flutter.md"):
        brief, _ = blog.parse_brief(SRC / "briefs" / name)
        assert schema_errors(brief, "brief") == [], name


def test_seo_minimum_gate_fails_even_when_total_is_high():
    r = gate(make_review(scores=make_scores(seo=79)))
    assert r["status"] == "FAILED" and r["gate_failures"] == ["gate:seo:below_min_score"]
    assert gate(make_review(scores=make_scores(seo=80)))["status"] == "PASSED"


def test_slack_shows_scores_and_required_action():
    import notify
    review = make_review(scores=make_scores(seo=88))
    t = notify.render_slack("r1", "T", 2, {}, review, "https://x", None, 91.5)
    assert "Quality score: 91.5/100" in t and "SEO score: 88/100" in t and "Required action" in t


# ---- grounding: issue anchors must be quoted from the draft ----
DRAFT = "Tokens name each design decision once.\n\nThe team’s “ship it” rule   works.\nA second paragraph follows."


def grounding(anchor, draft=DRAFT):
    return validate.review_problems(make_review([issue(anchor=anchor)]), CLEAN, TH, RULES, draft)


def test_anchor_missing_from_the_draft_is_rejected():
    probs = grounding("Tokens remove all drift")
    assert len(probs) == 1 and "not quoted from the draft" in probs[0] and "i1" in probs[0]


def test_anchor_matches_across_whitespace_case_and_smart_quotes():
    assert grounding("tokens name   each design\ndecision once.") == []
    assert grounding("The team's \"ship it\" rule works.") == []


def test_anchor_with_an_ellipsis_needs_every_segment_in_the_draft():
    assert grounding("Tokens name each… decision once.") == []
    assert grounding("Tokens name each... works.") == []
    assert grounding("Tokens name each... invented ending")


def test_empty_anchor_is_not_a_grounding_failure():
    assert grounding("") == [] and grounding("   ") == []


def test_grounding_is_skipped_without_draft_text_and_does_not_check_claim_wording():
    review = make_review([issue(anchor="not in any draft")], claim_checks=[
        {"claim": "paraphrase of the draft", "source": None, "verdict": "SUPPORTED", "evidence": "e"}])
    assert validate.review_problems(review, CLEAN, TH, RULES) == []
    assert validate.review_problems({**review, "issues": []}, CLEAN, TH, RULES, DRAFT) == []

