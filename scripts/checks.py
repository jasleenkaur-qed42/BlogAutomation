"""Deterministic draft checks -> {"hard": [{"id", "detail"}], "signals": {...}}."""
import re
import urllib.error
import urllib.request

import visuals
from common import split_front_matter

LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)|(?<![\(\"'])\bhttps?://[^\s)>\"']+")
PUBLISH_KEYS = {"published", "publish", "status", "draft", "publish_date", "publishdate", "date_published"}


def word_count(body):
    return len(re.findall(r"\b[\w'-]+\b", re.sub(r"```.*?```", "", body, flags=re.S)))


def _fail(hard, id_, detail):
    hard.append({"id": id_, "detail": detail})


def _sections(body):
    """Return (intro_text, [(heading, text)]) for the body: intro is the text between the H1 and the first H2."""
    parts = re.split(r"^## ([^\n]+)\n?", body, flags=re.M)
    intro = re.sub(r"^# [^\n]+\n?", "", parts[0], flags=re.M)
    return intro, list(zip(parts[1::2], parts[2::2]))


def _check_faq(hard, sections, st):
    faq = re.compile(st["faq_pattern"], re.I)
    found = [t for h, t in sections if faq.search(h)]
    if not found:
        _fail(hard, "structure", "missing FAQ section (an H2 such as 'Frequently asked questions')")
        return
    n = len(re.findall(r"^#{3,4} [^\n]*\?\s*$", found[0], flags=re.M))
    lo, hi = st.get("min_faq_questions", 5), st.get("max_faq_questions", 7)
    if not lo <= n <= hi:
        _fail(hard, "structure", f"FAQ has {n} question heading(s) (H3 ending in '?'), need {lo}-{hi}")


def _check_sections(hard, body, brief, st):
    """Mechanical structure rules. Only the keys present in rules['required_structure'] are enforced."""
    intro, sections = _sections(body)
    if st.get("require_introduction") and word_count(intro) < st.get("min_intro_words", 10):
        _fail(hard, "structure", f"missing introduction (need {st.get('min_intro_words', 10)}+ words before the first H2)")
    conc, refs, faq = (re.compile(st.get(k, "$^"), re.I) for k in ("conclusion_pattern", "references_pattern", "faq_pattern"))
    topic = [(h, t) for h, t in sections if not conc.search(h) and not refs.search(h) and not faq.search(h)]
    if st.get("require_faq"):
        _check_faq(hard, sections, st)
    if "min_h2_count" in st:
        real = [h for h, t in topic if word_count(t) >= st.get("min_h2_words", 20)]
        if len(real) < st["min_h2_count"]:
            _fail(hard, "structure", f"{len(real)} substantive topic H2 section(s) (excluding conclusion and "
                                     f"references), need at least {st['min_h2_count']}")
    if st.get("require_conclusion") and not any(conc.search(h) for h, _ in sections):
        _fail(hard, "structure", "missing conclusion section")
    if st.get("require_references_when_required") and (brief.get("references") or {}).get("required") \
            and not any(refs.search(h) and word_count(t) > 0 for h, t in sections):
        _fail(hard, "structure", "references are required by the brief but the draft has no References section")


def flagged_word_regex(words):
    """One case-insensitive regex for the flagged words in every form (enable -> enabling, leveraged...)."""
    def stem(w):
        w = re.escape(w).replace(r"\ ", r"\s+")
        return w[:-1] if w.endswith("e") else w
    return re.compile(r"\b(?:" + "|".join(stem(w) for w in words) + r")\w*", re.I)


def prose_only(text):
    """Text a reader sees: no fenced or inline code, no link targets, no bare URLs."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    return re.sub(r"https?://\S+", "", text)


def _check_voice(hard, signals, title, desc, body, rules):
    prose = prose_only("\n".join((title, desc, body)))
    if rules.get("ban_em_dash") and "—" in prose:
        _fail(hard, "em_dash", f"{prose.count(chr(0x2014))} em dash(es); use commas, periods or semicolons")
    if rules.get("flagged_words"):
        hits = sorted({m.group(0).lower() for m in flagged_word_regex(rules["flagged_words"]).finditer(prose)})
        if hits:
            _fail(hard, "flagged_word", ", ".join(hits))
    # Signal for the reviewer: headings and titles should be sentence case (proper nouns and acronyms excepted).
    caps = []
    for h in [title, *re.findall(r"^#{1,4} ([^\n]+)", body, flags=re.M)]:
        words = [w for w in re.findall(r"[A-Za-z][\w'-]*", h)[1:] if len(w) > 3 and w[0].isupper() and not w.isupper()]
        if len(words) >= 2:
            caps.append(h)
    signals["title_case_headings"] = caps


def _check_injection(hard, draft_text, rules):
    """Instruction-like text aimed at the AI pipeline. Scans the whole draft (front matter and HTML comments included,
    where hidden text lives) but not code, so a post about prompt injection can still quote examples in code."""
    patterns = rules.get("injection_patterns")
    if not patterns:
        return
    text = prose_only(draft_text)
    hits = sorted({m.group(0).lower() for m in re.finditer("|".join(f"(?:{p})" for p in patterns), text, re.I)})
    if hits:
        _fail(hard, "injection_phrase", "; ".join(hits) + " (instruction-like text aimed at an AI; remove it or put "
              "any quoted example in a code block)")


def verifiable_claims(fm, body, rules):
    """Conservative trigger for the reviewer's minimum claim_checks: claims front matter, code blocks, or
    version/benchmark/performance/security statements. Bare numbers do not count."""
    if fm.get("claims") or "```" in visuals.VISUAL_BLOCK.sub("", body):
        return True
    return any(re.search(p, body) for p in rules.get("claim_patterns", []))


def default_link_checker(url, retries=2, timeout=10):
    """Return 'ok', 'dead' (404/410) or 'unknown' (timeout, bot-block, other)."""
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 blog-checks"})
            with urllib.request.urlopen(req, timeout=timeout):
                return "ok"
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return "dead"
        except Exception:
            pass
    return "unknown"


def extract_links(body):
    return sorted({(m.group(1) or m.group(0)).rstrip(".,;") for m in LINK_RE.finditer(body)})


def run_checks(draft_text, brief, rules, link_checker=default_link_checker, check_links=True, visuals_planned=False):
    hard, signals = [], {}
    try:
        fm, body = split_front_matter(draft_text)
    except ValueError as e:
        return {"hard": [{"id": "front_matter", "detail": str(e)}], "signals": {}}

    title, desc, slug = str(fm.get("title", "")), str(fm.get("description", "")), str(fm.get("slug", ""))
    lower = (title + "\n" + body).lower()

    for t in rules.get("forbidden_terms", []):
        if t.lower() in lower:
            _fail(hard, "forbidden_term", t)
    for t in rules.get("required_terms", []):
        if t.lower() not in lower:
            _fail(hard, "required_term", t)

    for name, val, key in (("title", title, "title"), ("meta_description", desc, "meta_description")):
        lim = rules.get(key, {})
        if not (lim.get("min", 0) <= len(val) <= lim.get("max", 10**9)):
            _fail(hard, f"{name}_length", f"{len(val)} chars, allowed {lim.get('min')}-{lim.get('max')}")

    kws = [brief["primary_keyword"], *brief.get("secondary_keywords", [])]
    for kw in kws:
        if kw.lower() not in lower:
            _fail(hard, "missing_keyword", kw)

    _check_voice(hard, signals, title, desc, body, rules)
    _check_injection(hard, draft_text, rules)

    if not re.match(rules.get("slug_pattern", ".*"), slug):
        _fail(hard, "slug", repr(slug))

    st = rules.get("required_structure", {})
    h1 = len(re.findall(r"^# [^\n]+", body, flags=re.M))
    h2 = len(re.findall(r"^## [^\n]+", body, flags=re.M))
    if "h1_count" in st and h1 != st["h1_count"]:
        _fail(hard, "structure", f"{h1} H1, expected {st['h1_count']}")
    if h2 < st.get("min_h2", 0):
        _fail(hard, "structure", f"{h2} H2, need at least {st['min_h2']}")
    for k in ("intro_marker", "cta_marker"):
        if st.get(k) and st[k].lower() not in body.lower():
            _fail(hard, "structure", f"missing {k} {st[k]!r}")
    _check_sections(hard, body, brief, st)

    wc = word_count(body)
    tw = brief["target_words"]
    tol = rules.get("word_count_tolerance", 0)
    if not (tw["min"] - tol <= wc <= tw["max"] + tol):
        _fail(hard, "word_count", f"{wc} words, target {tw['min']}-{tw['max']} (tolerance ±{tol})")

    if visuals_planned:
        # A separate planner adds figures after review (see visual_checks.plan_errors), so the writer writes none.
        n = len(visuals.VISUAL_BLOCK.findall(body))
        signals["visual_count"] = signals["image_count"] = 0
        if n:
            _fail(hard, "visuals", f"{n} `visual` block(s) found; remove them (figures are added after review by the "
                                   "visual planner). Code stays in fenced code blocks.")
    else:
        need = (brief.get("visuals") or {}).get("min", 2)
        valid, bad_specs = visuals.count_valid(body)
        signals["visual_count"] = valid
        for err in bad_specs:
            _fail(hard, "visuals", f"invalid visual block: {err}")
        if valid < need:
            _fail(hard, "visuals", f"{valid} valid visual block(s), brief needs at least {need}")
        need_img = (brief.get("images") or {}).get("min", 1)
        signals["image_count"] = visuals.count_scenes(body)
        if signals["image_count"] < need_img:
            _fail(hard, "visuals", f"{signals['image_count']} topic image block(s) (type banner, ui_screen or cards), "
                                   f"brief needs at least {need_img}")

    for pat in rules.get("placeholder_patterns", []):
        if re.search(pat, title + "\n" + body):
            _fail(hard, "placeholder", pat)
    for pat in rules.get("secret_pii_patterns", []):
        if re.search(pat, title + "\n" + body):
            _fail(hard, "secret_pii", pat)
    bad = PUBLISH_KEYS & {str(k).lower() for k in fm}
    if bad:
        _fail(hard, "publish_state_field", ",".join(sorted(bad)))
    for term in brief.get("must_avoid", []):
        if term.lower() in lower:
            _fail(hard, "must_avoid", term)

    links = extract_links(body)
    signals["link_count"] = len(links)
    if check_links:
        unknown = []
        for url in links:
            r = link_checker(url)
            if r == "dead":
                _fail(hard, "broken_link", url)
            elif r == "unknown":
                unknown.append(url)
        signals["unverified_links"] = unknown

    prim = brief["primary_keyword"].lower()
    signals["word_count"] = wc
    signals["keyword_density_pct"] = round(100 * body.lower().count(prim) * len(prim.split()) / max(wc, 1), 2)
    sents = max(len(re.findall(r"[.!?]+(\s|$)", body)), 1)
    signals["avg_sentence_words"] = round(wc / sents, 1)
    signals["verifiable_claims"] = verifiable_claims(fm, body, rules)
    return {"hard": hard, "signals": signals}
