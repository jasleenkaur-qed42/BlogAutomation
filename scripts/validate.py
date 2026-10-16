"""Pure gate calculation. No IO, no state.

Scoring is active only when `rules["rubric"]` and `thresholds["hard_gates"]` are both configured.
`validate` is authoritative: PASS/FAIL is computed here from the review JSON, never read from it.
"""
import hashlib
import re
from fractions import Fraction

BAD_CLAIM = ("UNSUPPORTED", "CONTRADICTED")


def scoring_enabled(thresholds, rules):
    return bool(rules.get("rubric")) and bool(thresholds.get("hard_gates"))


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def weighted_total(rubric, scores):
    """Exact weighted total as a Fraction: sum(weight * score / 100). Round only for display."""
    return sum(Fraction(w) * Fraction(str(scores[d]["score"])) / 100 for d, w in rubric.items())


def claim_fingerprint(claim):
    return hashlib.sha1(re.sub(r"\s+", " ", str(claim)).strip().lower().encode()).hexdigest()[:12]


def config_errors(thresholds=None, rules=None):
    """Static config sanity so a bad config cannot silently fail (or pass) every review."""
    errs = []
    if thresholds is not None:
        g = thresholds.get("hard_gates")
        if g is not None:
            for k in ("min_total_score", "min_dimension_percentage"):
                if not (_num(g.get(k)) and 0 <= g[k] <= 100):
                    errs.append(f"hard_gates.{k} must be a number in 0..100")
            m = g.get("min_claim_checks")
            if not (isinstance(m, int) and not isinstance(m, bool) and m >= 0):
                errs.append("hard_gates.min_claim_checks must be an integer >= 0")
            if not isinstance(g.get("factual_correctness"), bool):
                errs.append("hard_gates.factual_correctness must be a boolean (enables the gate)")
            v = thresholds.get("max_score_with_high_issue")
            if not (_num(v) and 0 <= v <= 100):
                errs.append("max_score_with_high_issue must be a number in 0..100")
    if rules is not None and rules.get("rubric") is not None:
        rubric = rules["rubric"]
        if not all(_num(w) and w > 0 for w in rubric.values()) or sum(rubric.values()) != 100:
            errs.append("rubric weights must be positive and sum to 100")
        for d in rules.get("hard_gate_dimensions", []):
            if d not in rubric:
                errs.append(f"hard_gate_dimensions: {d!r} is not a rubric dimension")
    return errs


def rubric_section(rules):
    """Prompt text listing the rubric dimensions; empty when scoring is not configured."""
    rubric = rules.get("rubric")
    if not rubric:
        return ""
    return "\n".join(f"- {d} (weight {w})" for d, w in rubric.items())


def hard_gate_minimums(thresholds, rules):
    """{hard-gate dimension: the score below which score_gates fails it}."""
    gates = thresholds["hard_gates"]
    per_dim = gates.get("min_dimension_scores") or {}
    return {d: max(gates["min_dimension_percentage"], per_dim.get(d, 0)) for d in rules.get("hard_gate_dimensions", [])}


def consistency_section(thresholds, rules):
    """Prompt text stating the consistency rules review_problems enforces; empty when scoring is off. Generated from
    config so the reviewer is told every number the code rejects on: the HIGH-issue cap and each hard-gate minimum
    (a hard-gate score below its minimum must be explained by a HIGH/CRITICAL issue). min_total_score stays out."""
    if not scoring_enabled(thresholds, rules):
        return ""
    cap = thresholds["max_score_with_high_issue"]
    mins = hard_gate_minimums(thresholds, rules)
    return "\n".join([
        f"- A HIGH or CRITICAL issue on a dimension means that dimension's score is at most {cap}. A review with a "
        f"HIGH/CRITICAL issue on a dimension scored above {cap} is rejected as inconsistent.",
        f"- {', '.join(mins)} are hard gates: a low score on one fails the draft by itself, so score each on what it "
        "measures and nothing else. Their minimums: " + ", ".join(f"{d} {m}" for d, m in mins.items()) + ".",
        "- A hard-gate score below its minimum is a failing judgment, so it needs a failing finding: a HIGH or CRITICAL "
        "issue with that `dimension` that says what to fix. If the checks behind that dimension pass and its issues are "
        "MEDIUM or LOW (a flag, not a fail), its score is at or above the minimum. A review that scores a hard gate "
        "below its minimum with no HIGH/CRITICAL issue on that dimension is rejected as inconsistent.",
        "- Decide each issue's severity from the check that found it, then score. Never lower a severity to keep a "
        "score, and never move a score only to fit a severity: if they disagree, re-read the draft and fix the "
        "judgment that is wrong."])


def checklist_reference_problems(review):
    """Failed checklist items must point at an issue in the same review."""
    ids = [i["id"] for i in review.get("issues", [])]
    bad = [c["item"] for c in review.get("checklist", []) if not c["pass"] and c.get("issue_id") not in ids]
    return [f"failed checklist items reference no known issue id: {bad}"] if bad else []


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def _norm_text(s):
    return re.sub(r"\s+", " ", str(s).translate(_QUOTES)).strip().casefold()


def _quoted_in(text, excerpt):
    """True when every segment of the excerpt (split at an ellipsis) appears in the normalized draft text."""
    parts = [_norm_text(p) for p in re.split(r"…|\.{3}", str(excerpt))]
    return all(p in text for p in parts if p)


def grounding_problems(review, draft):
    """Reasons an issue anchor is not quoted from the draft. An empty anchor is skipped: an issue about something
    missing from the draft has nothing to quote. `claim_checks[].claim` is deliberately not checked: reviewers
    restate claims in their own words (about 40% of recorded real claims are paraphrases), so a substring test
    would reject sound reviews; claim accuracy is measured by the eval instead."""
    text, probs = _norm_text(draft), []
    for i in review.get("issues") or []:
        a = i.get("anchor")
        if isinstance(a, str) and a.strip() and not _quoted_in(text, a):
            probs.append(f"issue {i.get('id')}: anchor is not quoted from the draft: {a[:80]!r}")
    return probs


def review_problems(review, checks, thresholds, rules, draft=None):
    """Reasons a review is malformed for the configured rubric (empty list when fine or scoring is off). When
    `draft` text is given, each issue anchor must also be quoted from it."""
    if not scoring_enabled(thresholds, rules):
        return []
    rubric, gates, probs = rules["rubric"], thresholds["hard_gates"], []
    if draft is not None:
        probs.extend(grounding_problems(review, draft))
    scores = review.get("scores")
    if not isinstance(scores, dict):
        probs.append("scores missing: provide a score and evidence for every rubric dimension")
        scores = {}
    for d in rubric:
        s = scores.get(d)
        if not isinstance(s, dict) or not _num(s.get("score")) or not 0 <= s["score"] <= 100 \
                or not str(s.get("evidence", "")).strip():
            probs.append(f"scores.{d} must be {{score: 0-100, evidence: text}}")
    fc = review.get("factual_correctness")
    if gates.get("factual_correctness") and not (isinstance(fc, dict) and isinstance(fc.get("passed"), bool)):
        probs.append("factual_correctness must be {passed: bool, evidence: text}")
    cc = review.get("claim_checks")
    if not isinstance(cc, list):
        probs.append("claim_checks missing: provide a list (empty only when no verifiable claims)")
    elif (checks or {}).get("signals", {}).get("verifiable_claims") and len(cc) < gates["min_claim_checks"]:
        probs.append(f"claim_checks needs at least {gates['min_claim_checks']} entries: the draft contains "
                     "claims, code or version-dependent statements")
    cap = thresholds["max_score_with_high_issue"]
    for i in review.get("issues", []):
        dim = i.get("dimension")
        if dim is None:
            continue
        if dim not in rubric:
            probs.append(f"issue {i.get('id')}: unknown dimension {dim!r}")
        elif i["severity"] in ("HIGH", "CRITICAL") and not any(p.startswith(f"scores.{dim}") for p in probs) \
                and scores[dim]["score"] > cap:
            probs.append(f"issue {i.get('id')} is {i['severity']} on {dim} but scores.{dim} is "
                         f"{scores[dim]['score']} (max {cap} allowed with a HIGH/CRITICAL issue)")
    # Converse of the cap: a hard-gate score that fails the draft by itself must be explained by a blocking issue on
    # that dimension (the adapter's "fail"), or the writer gets a gate failure with nothing to fix.
    blocking = {i.get("dimension") for i in review.get("issues", []) if i.get("severity") in ("HIGH", "CRITICAL")}
    for d, m in hard_gate_minimums(thresholds, rules).items():
        if any(p.startswith(f"scores.{d}") for p in probs) or d not in scores:
            continue
        if Fraction(str(scores[d]["score"])) < Fraction(str(m)) and d not in blocking:
            probs.append(f"scores.{d} is {scores[d]['score']}, below the {d} hard-gate minimum {m}, but no HIGH/CRITICAL "
                         f"issue has dimension {d!r}: a failing hard-gate score needs a failing issue on that dimension")
    return probs


def score_gates(review, thresholds, rules):
    """Return (weighted_total or None, gate failure names, reasons). Pure; assumes a well-formed review."""
    rubric, gates = rules["rubric"], thresholds["hard_gates"]
    scores = review.get("scores") or {}
    fails, reasons = [], []
    if not all(isinstance(scores.get(d), dict) and _num(scores[d].get("score")) for d in rubric):
        return None, ["gate:scores_missing"], ["rubric scores missing"]
    total = weighted_total(rubric, scores)
    if total < Fraction(str(gates["min_total_score"])):
        fails.append("gate:total")
        reasons.append(f"weighted score {float(total):.2f} < {gates['min_total_score']}")
    for d in rules.get("hard_gate_dimensions", []):
        if Fraction(str(scores[d]["score"])) < Fraction(str(gates["min_dimension_percentage"])):
            fails.append(f"gate:{d}:below_min")
            reasons.append(f"{d} score {scores[d]['score']} < {gates['min_dimension_percentage']}")
    for d, m in (gates.get("min_dimension_scores") or {}).items():
        if d in scores and Fraction(str(scores[d]["score"])) < Fraction(str(m)):
            fails.append(f"gate:{d}:below_min_score")
            reasons.append(f"{d} score {scores[d]['score']} < {m}")
    fc = review.get("factual_correctness") or {}
    if gates.get("factual_correctness") and fc.get("passed") is not True:
        fails.append("gate:factual_correctness")
        reasons.append("factual correctness gate failed")
    for c in review.get("claim_checks") or []:
        if c.get("verdict") in BAD_CLAIM:
            fails.append(f"claim:{claim_fingerprint(c.get('claim', ''))}")
            reasons.append(f"claim {c.get('verdict')}: {str(c.get('claim', ''))[:80]}")
    return float(total), sorted(set(fails)), reasons


def validate(checks, review, thresholds, rules):
    """checks: {"hard": [...]}; review: parsed review dict or None (mechanical stage); returns gate result."""
    hard = list(checks.get("hard", []))
    blockers, reasons, gate_failures, total = [], [], [], None
    if hard:
        reasons.append(f"{len(hard)} hard check failure(s)")
    if review is not None:
        issues = review.get("issues", [])
        sev = lambda s: [i for i in issues if i["severity"] == s]
        if len(sev("CRITICAL")) > thresholds["max_critical"]:
            blockers += sev("CRITICAL")
            reasons.append(f"{len(sev('CRITICAL'))} CRITICAL issue(s) > {thresholds['max_critical']}")
        if len(sev("HIGH")) > thresholds["max_high"]:
            blockers += sev("HIGH")
            reasons.append(f"{len(sev('HIGH'))} HIGH issue(s) > {thresholds['max_high']}")
        passed = {c["item"]: c["pass"] for c in review.get("checklist", [])}
        for item in rules.get("required_checklist", []):
            if not passed.get(item, False):
                reasons.append(f"required checklist item failed or missing: {item}")
                blockers.append({"checklist": item})
        if scoring_enabled(thresholds, rules):
            total, gate_failures, gate_reasons = score_gates(review, thresholds, rules)
            reasons += gate_reasons
            blockers += [{"gate": g} for g in gate_failures]
    else:
        reasons.append("no review supplied")
    ok = not hard and review is not None and not blockers
    return {"status": "PASSED" if ok else "FAILED", "reasons": reasons,
            "hard_failures": hard, "reviewer_blockers": blockers,
            "weighted_total": None if total is None else round(total, 2), "gate_failures": gate_failures}
