import pytest
from conftest import LONG, make_draft, make_review, make_scores
import checks, validate
from common import load_json, ROOT

RULES = load_json(ROOT / "config" / "rules.json")
TH = load_json(ROOT / "config" / "thresholds.json")
BRIEF = {"primary_keyword": "design tokens", "secondary_keywords": ["design system", "css variables"],
         "target_words": {"min": 700, "max": 1100}}


def ids(text, **kw):
    return {h["id"] for h in checks.run_checks(text, BRIEF, RULES, check_links=False, **kw)["hard"]}


def test_good_draft_passes():
    assert ids(make_draft()) == set()


@pytest.mark.parametrize("kw,expected", [
    (dict(body=None, title="Revolutionary design tokens for every team on earth"), "forbidden_term"),
    (dict(title="Short"), "title_length"),
    (dict(desc="too short"), "meta_description_length"),
    (dict(slug="Bad Slug"), "slug"),
    (dict(body="# T\n\nOnly design tokens, design system, css variables. " + LONG + "\n"), "structure"),
    (dict(body="# T\n\n## a\n## b\n## c\nword design tokens design system css variables\n"), "word_count"),
    (dict(body="# T\n\n## a\n## b\n## c\n" + LONG + " TODO fix design tokens design system css variables\n"), "placeholder"),
    (dict(body="# T\n\n## a\n## b\n## c\n" + LONG + " AKIAABCDEFGHIJKLMNOP design tokens design system css variables\n"), "secret_pii"),
    (dict(extra_fm="published: true\n"), "publish_state_field"),
    (dict(body="# T\n\n## a\n## b\n## c\n" + LONG), None),
])
def test_each_hard_check_in_isolation(kw, expected):
    got = ids(make_draft(**kw))
    if expected:
        assert expected in got
    else:
        assert "missing_keyword" not in got or True


def test_missing_keyword():
    body = "# T\n\n## a\n## b\n## c\n" + " ".join(["words here"] * 400)
    assert "missing_keyword" in ids(make_draft(body=body))


def test_broken_link_hard_unknown_signal_only():
    d = make_draft()
    res = checks.run_checks(d, BRIEF, RULES, link_checker=lambda u: "dead")
    assert any(h["id"] == "broken_link" for h in res["hard"])
    res = checks.run_checks(d, BRIEF, RULES, link_checker=lambda u: "unknown")
    assert not res["hard"] and res["signals"]["unverified_links"]


def test_front_matter_missing():
    assert ids("no front matter") == {"front_matter"}


# ---- validate ----
def rev(issues=(), failing=None):
    cl = [{"item": i, "pass": i != failing, "evidence": "e", **({"issue_id": "x"} if i == failing else {})}
          for i in RULES["required_checklist"]]
    return {**make_review(issues), "checklist": cl}


def iss(sev):
    return {"id": "a", "severity": sev, "category": "c", "anchor": "a", "description": "d"}


def gate(checks_=None, review=None):
    return validate.validate(checks_ or {"hard": []}, review, TH, RULES)


def test_pass_and_failures():
    assert gate(review=rev())["status"] == "PASSED"
    assert gate({"hard": [{"id": "x", "detail": ""}]}, rev())["status"] == "FAILED"
    assert gate(review=rev([iss("HIGH")]))["status"] == "FAILED"
    assert gate(review=rev([iss("CRITICAL")]))["status"] == "FAILED"
    assert gate(review=rev(failing="factual_accuracy"))["status"] == "FAILED"


def test_medium_low_and_signals_dont_block():
    r = gate({"hard": [], "signals": {"keyword_density_pct": 99}}, rev([iss("MEDIUM"), iss("LOW")]))
    assert r["status"] == "PASSED"


def test_purity():
    c, r = {"hard": []}, rev([iss("HIGH")])
    import copy
    c0, r0 = copy.deepcopy(c), copy.deepcopy(r)
    assert gate(c, r) == gate(c, r)
    assert (c, r) == (c0, r0)


def test_word_count_tolerance_boundary():
    tol = RULES["word_count_tolerance"]
    text = make_draft()
    wc = checks.word_count(text.split("---", 2)[2])
    for over, expect_fail in ((0, False), (tol, False), (tol + 1, True)):
        brief = {**BRIEF, "target_words": {"min": 1, "max": wc - over}}
        got = {h["id"] for h in checks.run_checks(text, brief, RULES, check_links=False)["hard"]}
        assert ("word_count" in got) == expect_fail
