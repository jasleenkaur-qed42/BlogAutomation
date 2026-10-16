"""Pure rendering of the Drive doc body and Slack message, with sanitizing."""
import re

MAX_NOTE = 300
MAX_SUMMARY = 800


def sanitize(text, cap=MAX_NOTE):
    t = re.sub(r"<!(channel|here|everyone)>|@(channel|here|everyone)\b", "", str(text), flags=re.I)
    t = re.sub(r"<@[^>]*>|<#[^>]*>|@\w+", "", t)
    t = t.replace("<", "‹").replace(">", "›").replace("`", "'").replace("*", "").replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:cap - 1] + "…" if len(t) > cap else t


def run_id_marker(run_id):
    return f"[run:{run_id}]"


def doc_title(title, run_id, prefix=None):
    return f"{prefix + ' ' if prefix else ''}{sanitize(title, 120)} {run_id_marker(run_id)}"


def render_doc(draft_text, banner=None):
    """The Doc body. A banner (human-approved failing delivery only) goes right after the front matter."""
    if not banner:
        return draft_text
    m = re.match(r"\A(---\s*\n.*?\n---\s*\n?)(.*)\Z", draft_text, re.S)
    head, body = (m.group(1), m.group(2)) if m else ("", draft_text)
    return f"{head.rstrip(chr(10))}\n\n{banner}\n\n{body}"


def override_banner(issues, claims, note):
    lines = ["> **This draft did not pass the automated review gate.** A person approved sending it for human review. "
             "Fix the open items below before publishing.", ">"]
    lines += [f"> - [{i['severity']}] {sanitize(i['description'], 200)}" for i in issues[:10]]
    lines += [f"> - Unverified claim: {sanitize(c['claim'], 200)}" for c in claims[:10]]
    lines += [">", f"> Approved by the user: {sanitize(note, 200)}"]
    return "\n".join(lines)


def visual_lines(visuals):
    """Tell the reviewer what still needs a human: image prompts to fill in, visuals that were dropped."""
    if not visuals:
        return []
    out = []
    if visuals.get("image_prompts"):
        out.append(f"Images: {visuals['image_prompts']} image prompt(s) to fill in the Doc (see the boxes marked IMAGE TO ADD).")
    if visuals.get("dropped"):
        out.append(f"Visuals dropped: {', '.join(sanitize(d, 20) for d in visuals['dropped'])}.")
    return out


def render_slack(run_id, title, iterations, signals, review, doc_url, visuals=None, weighted_total=None, extra=None, override=None):
    seo = ((review.get("scores") or {}).get("seo") or {}).get("score")
    return "\n".join([
        sanitize(title, 120),
        (f"DID NOT PASS the AI review gate ({len(override.get('blocking_issue_ids', []))} blocking issue(s), "
         f"{len(override.get('unverified_claims', []))} unverified claim(s)). Sent for human review at the user's "
         "request. Not approved or published." if override else
         f"Passed AI review in {iterations} iteration(s). Not yet approved or published."),
        *([f"Quality score: {weighted_total}/100"] if weighted_total is not None else []),
        *([f"SEO score: {seo}/100"] if seo is not None else []),
        f"Signals: words={signals.get('word_count')}, keyword density={signals.get('keyword_density_pct')}%, "
        f"unverified links={len(signals.get('unverified_links', []))}",
        f"Reviewer summary: {sanitize(review.get('summary', ''), MAX_SUMMARY)}",
        *visual_lines(visuals),
        *(extra or []),
        "",
        f"Draft: {doc_url}",
        "Required action: Human review, approval and publishing."])
