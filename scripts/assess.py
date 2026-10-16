"""Pure signals about the author's original draft, shown to the user and to the assessing reviewer."""
import checks
from common import split_front_matter
from validate import BAD_CLAIM


def source_signals(text, rules, check_links=True, link_checker=checks.default_link_checker):
    try:
        fm, body = split_front_matter(text)
    except ValueError:
        fm, body = {}, text
    links = checks.extract_links(body)
    dead, unknown = [], []
    if check_links:
        for url in links:
            verdict = link_checker(url)
            if verdict == "dead":
                dead.append(url)
            elif verdict == "unknown":
                unknown.append(url)
    prose = checks.prose_only(body)
    words = sorted({m.group(0).lower() for m in checks.flagged_word_regex(rules["flagged_words"]).finditer(prose)}) \
        if rules.get("flagged_words") else []
    found = []
    checks._check_injection(found, text, rules)
    return {"word_count": checks.word_count(body), "link_count": len(links), "dead_links": dead,
            "unverified_links": unknown, "flagged_words": words, "em_dashes": prose.count("—"),
            "injection_phrases": [f["detail"] for f in found],
            "verifiable_claims": checks.verifiable_claims(fm, body, rules)}


def summarize(review, signals):
    counts = {s: 0 for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    for i in review.get("issues", []):
        counts[i["severity"]] += 1
    return {"issues": counts,
            "unverified_claims": [c["claim"] for c in review.get("claim_checks") or [] if c.get("verdict") in BAD_CLAIM],
            "dead_links": signals.get("dead_links", []), "flagged_words": signals.get("flagged_words", []),
            "injection_phrases": signals.get("injection_phrases", [])}
