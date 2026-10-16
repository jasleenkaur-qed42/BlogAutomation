import json
from pathlib import Path

import pytest
from conftest import issue, make_draft, make_review

import blog
import claim_verify

BAD = {"claim": "Tokens ship features 37% faster", "source": None, "verdict": "UNSUPPORTED", "evidence": "none"}
OK = {"claim": "CSS variables cascade", "source": "https://mdn", "verdict": "SUPPORTED", "evidence": "e"}


def acc(id_="a1", sev="HIGH", anchor="claim x"):
    return issue(id_, sev, "accuracy", anchor)


def test_targets_are_bad_claim_checks_then_blocking_accuracy_issues_only():
    review = make_review([acc("a1"), issue("t1", "HIGH", "tone"), acc("a2", "MEDIUM")], claim_checks=[OK, BAD])
    got = claim_verify.targets(review, 5)
    assert [(t["id"], t["kind"]) for t in got] == [("c2", "claim_check"), ("ia1", "issue")]
    assert got[0]["claim"] == BAD["claim"] and got[1]["claim"] == "claim x"


def test_targets_are_capped_and_empty_when_nothing_blocks():
    assert len(claim_verify.targets(make_review(claim_checks=[BAD] * 4), 2)) == 2
    assert claim_verify.targets(make_review([issue("m", "MEDIUM")], claim_checks=[OK]), 5) == []


def test_prompt_withholds_the_reviewers_verdict_and_reasoning():
    item = claim_verify.targets(make_review(claim_checks=[{**BAD, "evidence": "SECRET-REASONING"}]), 5)[0]
    p = claim_verify.build_prompt(item, "policy text")
    assert BAD["claim"] in p and "policy text" in p
    assert "SECRET-REASONING" not in p and "UNSUPPORTED|" in p and "reviewer" not in p.lower().replace("reviewer's", "")
    assert "UNSUPPORTED" not in p.replace("SUPPORTED|UNSUPPORTED|CONTRADICTED", "").replace("UNSUPPORTED means", "")


@pytest.mark.parametrize("verdict,disagrees", [("SUPPORTED", True), ("UNSUPPORTED", False), ("CONTRADICTED", False)])
def test_only_a_supported_verdict_disagrees_with_a_blocking_finding(verdict, disagrees):
    item = claim_verify.targets(make_review(claim_checks=[BAD]), 5)[0]
    r = claim_verify.compare(item, {"id": "c1", "verdict": verdict, "source": None, "evidence": "e"})
    assert r["disagrees"] is disagrees


def failed_review(driver):
    driver.write(make_draft())
    return driver.review(make_review([acc("a1", "HIGH", "claim x")], claim_checks=[{**BAD, "claim": "claim x"}],
                                     factual=False))


def test_verification_round_trip_surfaces_disagreement_without_touching_state(driver):
    assert failed_review(driver)["result"] == "ITERATION_FAILED"
    before = json.dumps(driver.state(), sort_keys=True)
    r = blog.cmd_verify_claims(driver.root, driver.run)
    assert [v["id"] for v in r["verifiers"]] == ["c1", "ia1"]
    assert "claim x" in Path(r["verifiers"][0]["prompt"]).read_text()
    Path(r["verifiers"][0]["output"]).write_text(json.dumps(
        {"id": "c1", "verdict": "SUPPORTED", "source": "https://mdn", "evidence": "states it"}))
    Path(r["verifiers"][1]["output"]).write_text(json.dumps(
        {"id": "ia1", "verdict": "CONTRADICTED", "source": None, "evidence": "wrong"}))
    v = blog.cmd_submit_verification(driver.root, driver.run)
    assert v["disagreements"] == ["c1"] and v["no_result"] == [] and "DISAGREES" in v["summary"][0]
    assert json.dumps(driver.state(), sort_keys=True) == before   # advisory: no phase, count or gate change


def test_missing_or_invalid_verifier_output_is_not_checked_rather_than_agreement(driver):
    failed_review(driver)
    r = blog.cmd_verify_claims(driver.root, driver.run)
    Path(r["verifiers"][0]["output"]).write_text(json.dumps({"id": "c1", "verdict": "MAYBE"}))
    v = blog.cmd_submit_verification(driver.root, driver.run)
    assert v["results"] == [] and {n["id"] for n in v["no_result"]} == {"c1", "ia1"} and v["disagreements"] == []
    assert "could not be independently checked" in v["summary"][0]


def test_verify_needs_a_review_and_a_plan(driver):
    with pytest.raises(blog.BlogError):
        blog.cmd_verify_claims(driver.root, driver.run)
    failed_review(driver)
    with pytest.raises(blog.BlogError):
        blog.cmd_submit_verification(driver.root, driver.run)


def test_slack_text_carries_the_disagreement_for_the_final_review(driver):
    driver.write(make_draft()); driver.review(make_review([issue("m", "MEDIUM")]))
    rd = driver.root / "runs" / driver.run
    (rd / "verification-1.json").write_text(json.dumps({"iteration": 1, "no_result": [], "results": [
        {"claim": "CSS variables <!channel> cascade", "reviewer_verdict": "UNSUPPORTED", "disagrees": True}]}))
    blog.cmd_next(driver.root, driver.run)
    blog.cmd_record_delivery(driver.root, driver.run, "doc_created", "id1", "https://docs/x")
    text = Path(blog.cmd_next(driver.root, driver.run)["text_path"]).read_text()
    assert "DISAGREES with the reviewer on 1 of 1" in text and "CSS variables" in text and "<!channel>" not in text
