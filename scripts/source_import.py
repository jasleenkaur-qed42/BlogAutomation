"""Pure input handling for improve mode: classify the /blog argument, read a draft, convert it to markdown.
No state, no network. Raises SourceError with a message fit to show the user."""
import hashlib
import html as html_lib
import re
import urllib.parse
from pathlib import Path

import checks
from common import ROOT, split_front_matter

SUFFIXES = {".md", ".mdx", ".txt", ".docx"}
MAX_BYTES = 2_000_000
MIN_WORDS = 100
FAQ_HEADING = re.compile(r"^#{2,3} .*(faq|frequently asked|common questions)", re.I | re.M)
GDOC_RE = re.compile(r"^https://docs\.google\.com/document/(?:u/\d+/)?d/([A-Za-z0-9_-]{20,})(?:[/?#].*)?$")
G_REDIRECT = re.compile(r'href="https://www\.google\.com/url\?([^"]+)"')
CODE_STYLES = "p[style-name='Code'] => pre:fresh\np[style-name='Source Code'] => pre:fresh"


class SourceError(ValueError):
    pass


def parse_gdoc_url(url):
    m = GDOC_RE.match((url or "").strip())
    return m.group(1) if m else None


def _refuse_sensitive(p):
    """Judge the typed path and where it really points (symlinks, `..`), ignoring letter case."""
    for q in (p, p.resolve()):
        if q.name.lower().startswith(".env") or "secrets" in (part.lower() for part in q.parts):
            raise SourceError(f"reading {p.name} is not allowed (secrets and .env files are off limits)")


def _body(md):
    try:
        return split_front_matter(md)[1]
    except ValueError:
        return md


def check_markdown(md):
    if not md.strip():
        raise SourceError("the draft is empty")
    words = checks.word_count(_body(md))
    if words < MIN_WORDS:
        raise SourceError(f"the draft is too short to improve ({words} words, need at least {MIN_WORDS})")


def preserve_lines(md):
    """MDX imports, exports and component lines the writer must keep verbatim."""
    pat = re.compile(r"^(?:(?:import|export)\s.+|<[A-Z][A-Za-z0-9.]*[\s/>].*)$")
    return [ln.strip() for ln in md.splitlines() if pat.match(ln.strip())][:50]


def derive_target_words(md):
    n = checks.word_count(_body(md))
    hi = int(n * 1.15) + 1 + (0 if FAQ_HEADING.search(md) else 350)  # the checks require a FAQ; leave room for one
    return {"min": max(int(n * 0.85), 1), "max": hi}


def _tidy(md):
    md = "\n".join(line.rstrip() for line in md.replace("\r\n", "\n").split("\n"))
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def html_to_markdown(html):
    """Drive/Word HTML to markdown: drop styles and images, unwrap google.com/url redirects, keep structure."""
    from markdownify import markdownify
    html = re.sub(r"(?is)<(style|script|head)\b.*?</\1>", "", html)

    def unwrap(m):
        q = urllib.parse.parse_qs(html_lib.unescape(m.group(1))).get("q")
        return f'href="{html_lib.escape(q[0], quote=True)}"' if q else m.group(0)
    html = G_REDIRECT.sub(unwrap, html)
    html = re.sub(r"(?is)<img\b[^>]*>", "", html)
    return _tidy(markdownify(html, heading_style="ATX", bullets="-"))


def docx_to_markdown(data):
    import io
    import mammoth
    res = mammoth.convert_to_html(io.BytesIO(data), style_map=CODE_STYLES)
    images = len(re.findall(r"(?i)<img\b", res.value))
    dropped = ([f"{images} image(s) dropped"] if images else []) + sorted(
        {m.message for m in res.messages if m.type == "warning"})
    return html_to_markdown(res.value), dropped


def _result(md, sha, ext, dropped=(), mdx=False):
    return {"markdown": md, "sha256": sha, "ext": ext, "dropped": list(dropped),
            "preserve": preserve_lines(md) if mdx else []}


def import_text(md):
    """Markdown already fetched from a Google Doc."""
    md = _tidy(md)
    check_markdown(md)
    return _result(md, hashlib.sha256(md.encode()).hexdigest(), ".md")


def import_file(path):
    p = Path(path)
    _refuse_sensitive(p)
    ext = p.suffix.lower()
    if ext not in SUFFIXES:
        raise SourceError(f"unsupported file type {ext or '(none)'}; use .md, .mdx, .txt or .docx")
    if not p.is_file():
        raise SourceError(f"file not found: {path}")
    data = p.read_bytes()
    if len(data) > MAX_BYTES:
        raise SourceError(f"file too large ({len(data)} bytes, limit {MAX_BYTES})")
    dropped = []
    if ext == ".docx":
        try:
            md, dropped = docx_to_markdown(data)
        except Exception as e:
            raise SourceError(f"cannot read the .docx file: {e}")
    else:
        try:
            md = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise SourceError("the file is not UTF-8 text")
        md = md.replace("\r\n", "\n")
    check_markdown(md)
    return _result(md, hashlib.sha256(data).hexdigest(), ext, dropped, mdx=ext == ".mdx")


def suggest_topic(md, fallback):
    try:
        fm, body = split_front_matter(md)
    except ValueError:
        fm, body = {}, md
    if fm.get("title"):
        return str(fm["title"])
    m = re.search(r"^# (.+)$", body, re.M)
    return m.group(1).strip() if m else fallback


def classify_arg(arg, root=ROOT):
    """Route the /blog argument: create (topic or brief file), improve (local draft or Google Doc), ask, or error."""
    arg = (arg or "").strip()
    if not arg:
        return {"mode": "ask"}
    if arg.startswith(("http://", "https://")):
        doc_id = parse_gdoc_url(arg)
        if not doc_id:
            return {"mode": "error", "reason": "only Google Docs URLs (docs.google.com/document/d/<id>) are supported"}
        return {"mode": "improve", "kind": "gdoc", "ref": arg, "doc_id": doc_id}
    p = Path(arg).expanduser()
    p = p if p.is_absolute() else Path(root) / p
    if not p.exists():
        if p.suffix.lower() in SUFFIXES:
            return {"mode": "error", "reason": f"file not found: {arg}"}
        return {"mode": "create", "topic": arg}
    if not p.is_file():
        return {"mode": "create", "topic": arg}
    try:
        _refuse_sensitive(p)
        if p.suffix.lower() == ".md":
            try:
                fm, _ = split_front_matter(p.read_text())
            except (ValueError, UnicodeDecodeError):
                fm = {}
            if fm.get("topic") and fm.get("audience"):
                return {"mode": "create", "brief": str(p)}
        imported = import_file(p)
    except SourceError as e:
        return {"mode": "error", "reason": str(e)}
    md = imported["markdown"]
    return {"mode": "improve", "kind": "local", "ref": str(p), "suggested_topic": suggest_topic(md, p.stem),
            "word_count": checks.word_count(_body(md)), "suggested_target_words": derive_target_words(md),
            "dropped": imported["dropped"], "preserve_count": len(imported["preserve"])}
