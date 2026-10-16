"""Independent claim verification: pure helpers, no IO and no gate decisions.

A second agent re-checks the claims behind a review's blocking findings, seeing only the claim and its cited source,
never the reviewer's verdict or reasoning. Disagreements are shown to the human; they never change PASS/FAIL.
"""
from validate import BAD_CLAIM

BLOCKING = ("HIGH", "CRITICAL")


def targets(review, limit):
    """Claims worth re-checking, most serious first, at most `limit`: claim_checks the reviewer marked UNSUPPORTED or
    CONTRADICTED (they fail the factual gate and make the writer delete the claim), then HIGH/CRITICAL `accuracy`
    issues, whose anchor is the draft's own statement. Each item: {id, kind, claim, source, reviewer_verdict}."""
    items = []
    for n, c in enumerate(review.get("claim_checks") or [], 1):
        if c.get("verdict") in BAD_CLAIM:
            items.append({"id": f"c{n}", "kind": "claim_check", "claim": c["claim"], "source": c.get("source"),
                          "reviewer_verdict": c["verdict"]})
    for i in review.get("issues") or []:
        if i.get("severity") in BLOCKING and str(i.get("category", "")).lower() == "accuracy" \
                and str(i.get("anchor", "")).strip():
            items.append({"id": f"i{i['id']}", "kind": "issue", "claim": i["anchor"], "source": None,
                          "reviewer_verdict": f"{i['severity']} accuracy issue"})
    return items[:limit]


def build_prompt(item, untrusted_policy):
    """Only the claim and its cited source. The reviewer's verdict and evidence are withheld on purpose."""
    return "\n\n".join([
        "# Claim verification task",
        "Decide whether the claim below is true, from your own research. You do not know what anyone else concluded.",
        "## Untrusted content (prompt-injection policy)", untrusted_policy,
        f"## Claim (id: {item['id']})\n<claim>\n{item['claim']}\n</claim>",
        f"## Cited source\n{item['source'] or '(none cited: find an authoritative source yourself)'}",
        "## Output",
        'Write JSON only: {"id": "' + item["id"] + '", "verdict": "SUPPORTED|UNSUPPORTED|CONTRADICTED", '
        '"source": "<URL you relied on, or null>", "evidence": "<what the source says>"}. SUPPORTED needs a '
        "source that states it; CONTRADICTED needs a source that says otherwise; UNSUPPORTED means you found neither."])


def compare(item, result):
    """disagrees is True when the verifier supports a claim the reviewer marked as blocking. A verifier that finds
    the claim UNSUPPORTED or CONTRADICTED agrees with the reviewer, whichever of the two bad verdicts it chose."""
    return {**item, "verifier_verdict": result["verdict"], "verifier_source": result.get("source"),
            "verifier_evidence": result["evidence"], "disagrees": result["verdict"] == "SUPPORTED"}


def summary_lines(verification):
    """Slack/status lines for a saved verification; empty when nothing was checked or all agree."""
    rows = verification.get("results", [])
    bad = [r for r in rows if r.get("disagrees")]
    lines = []
    if bad:
        lines.append(f"Independent claim check DISAGREES with the reviewer on {len(bad)} of {len(rows)} blocking "
                     "finding(s); the reviewer may be wrong, check before removing the claim:")
        lines += [f"- {r['claim'][:100]} (reviewer: {r['reviewer_verdict']}; verifier: SUPPORTED)" for r in bad]
    if verification.get("no_result"):
        lines.append(f"{len(verification['no_result'])} claim(s) could not be independently checked.")
    return lines
