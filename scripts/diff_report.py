"""Pure change log between the author's original and the revised draft."""
import difflib
import re

from common import split_front_matter


def _body(md):
    try:
        return split_front_matter(md)[1]
    except ValueError:
        return md


def _norm(text):
    return re.sub(r"\s+", " ", text).strip()


META_KEYS = ("title", "slug", "description", "keywords")


def _meta(md):
    try:
        fm = split_front_matter(md)[0]
    except ValueError:
        fm = {}
    return {k: fm.get(k) for k in META_KEYS}


def is_unchanged(source_md, final_md):
    """Same body, and the same value for every title, slug, description or keywords field the source already had
    (a source without front matter cannot differ there; an SEO-only edit to one that has it is still a change)."""
    sm, fm = _meta(source_md), _meta(final_md)
    return _norm(_body(source_md)) == _norm(_body(final_md)) and all(fm[k] == v for k, v in sm.items() if v is not None)


def _sections(body):
    """{heading: text} in order; text before the first H1/H2 heading is '(top)'. Repeated headings get ' (2)', ' (3)'."""
    out, cur, buf = {}, "(top)", []

    def flush():
        text = "\n".join(buf)
        if cur != "(top)" or text.strip():
            key, n = cur, 2
            while key in out:
                key, n = f"{cur} ({n})", n + 1
            out[key] = text
    for line in body.splitlines():
        m = re.match(r"^#{1,2} (.+)$", line)
        if m:
            flush()
            cur, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    flush()
    return out


def _word_delta(a, b):
    ta, tb = a.split(), b.split()
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            added += j2 - j1
        if tag in ("delete", "replace"):
            removed += i2 - i1
    return added, removed


def build(source_md, final_md, changes, claim_rows):
    a, b = _body(source_md), _body(final_md)
    sa, sb = _sections(a), _sections(b)
    rows = []
    for h in dict.fromkeys([*sa, *sb]):
        if h not in sb:
            status = "removed"
        elif h not in sa:
            status = "added"
        elif _norm(sa[h]) != _norm(sb[h]):
            status = "changed"
        else:
            continue
        add, rem = _word_delta(sa.get(h, ""), sb.get(h, ""))
        rows.append((h, status, add, rem))
    added, removed = _word_delta(a, b)
    summary = {"sections_changed": len(rows), "words_added": added, "words_removed": removed}
    lines = ["# Change log", "", "## Summary",
             f"- Sections changed: {len(rows)}; words added: {added}; words removed: {removed}" if rows
             else "- No changes were needed."]
    if changes:
        lines += ["", "## What changed and why", *[f"- **{c.get('section', '')}**: {c.get('reason', '')}" for c in changes]]
    if claim_rows:
        lines += ["", "## Claims the reviewer could not verify"]
        for r in claim_rows:
            src = r.get("source")
            kept = "yes" if src and src in final_md else "no"
            lines.append(f"- [{r['verdict']}] {r['claim']} (raised in {r['raised_in']}; "
                         f"source link still in draft: {kept})")
    if rows:
        lines += ["", "## Sections", "| Section | Status | Words added | Words removed |", "|---|---|---|---|",
                  *[f"| {h} | {s} | {x} | {y} |" for h, s, x, y in rows]]
    diff = "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), "original", "revised", n=2))
    lines += ["", "## Diff", "```diff", diff.rstrip("\n") or "(no differences)", "```", ""]
    return {"markdown": "\n".join(lines), "summary": summary}
