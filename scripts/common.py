"""Shared helpers: paths, JSON/YAML IO, front matter parsing, schema validation."""
import difflib
import html as html_lib
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


def load_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def split_front_matter(text):
    """Return (front_matter_dict, body). Raises ValueError if missing or invalid."""
    m = FM_RE.match(text)
    if not m:
        raise ValueError("missing YAML front matter")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML front matter: {e}")
    if not isinstance(fm, dict):
        raise ValueError("front matter must be a mapping")
    return fm, m.group(2)


def schema_errors(instance, schema_name, root=ROOT):
    schema = load_json(Path(root) / "config" / "schemas" / f"{schema_name}.json")
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
            for e in Draft202012Validator(schema).iter_errors(instance)]


def schema_error_details(instance, schema_name, root=ROOT):
    """Structured schema errors: [{path, keyword, message}], where keyword is the failed schema constraint
    (required, type, enum, additionalProperties, minimum, ...). Messages echo instance values, so callers
    that persist them should treat them as draft-derived content."""
    schema = load_json(Path(root) / "config" / "schemas" / f"{schema_name}.json")
    return [{"path": "/".join(map(str, e.path)) or "<root>", "keyword": e.validator, "message": e.message}
            for e in sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: list(map(str, e.path)))]


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
# List markers Drive's text export emits (nested bullets use other glyphs; nested numbering uses letters/romans).
_MARKER_TOKENS = frozenset("*-•◦▪▫○●■□‣⁃∙·|")
_MARKER_RE = re.compile(r"\d+\.|\d+\)|\(\d+\)|[a-z]\.|[ivx]{2,4}\.")


def doc_comparable_tokens(text):
    """Word tokens of a Doc's visible text, ignoring BOM, whitespace, list markers (bullet glyphs, ordered and
    nested numbering, table pipes) and typographic quote/dash differences. Applied to both the expectation and
    the export, so a stripped token never causes a mismatch."""
    text = unicodedata.normalize("NFKC", text.replace("﻿", "")).translate(_QUOTES)
    return [t for t in text.split() if t not in _MARKER_TOKENS and not _MARKER_RE.fullmatch(t)]


def _doc_required_segments(md):
    """Text that must appear verbatim (as token runs) in the Doc: every heading, every code line and the prompt,
    alt text and caption of every image-prompt placeholder (the human works from them)."""
    class Headings(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth, self.cur, self.out = 0, [], []

        def handle_starttag(self, tag, attrs):
            if re.fullmatch(r"h[1-6]", tag):
                self.depth, self.cur = 1, []

        def handle_endtag(self, tag):
            if re.fullmatch(r"h[1-6]", tag):
                self.depth = 0
                self.out.append("".join(self.cur))

        def handle_data(self, data):
            if self.depth:
                self.cur.append(data)

    h = Headings()
    h.feed(markdown_to_html(md, render_visuals=False, code_labels=False))
    body = md.split("\n---\n", 1)[-1] if md.startswith("---\n") else md
    code = [ln for lang, blk in re.findall(r"^```([\w+#-]*)[ \t]*\n(.*?)^```", body, re.S | re.M)
            if lang != "visual" for ln in blk.split("\n")]
    import visuals
    holders = []
    for m in visuals.VISUAL_BLOCK.finditer(body):
        try:
            spec = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            continue
        if isinstance(spec, dict) and spec.get("type") == "asset" and spec.get("kind") == "placeholder":
            holders += [f"{label}: {spec[k]}" for k, label in (("prompt", "Prompt"), ("alt", "Alt text"), ("caption", "Caption"))
                        if k in spec]
    segs = (" ".join(doc_comparable_tokens(html_lib.unescape(s))) for s in h.out + code + holders)
    return [s for s in segs if s]


def doc_match(md, actual_text, min_coverage=1.0):
    """Does a Doc's exported text contain what `md` should render to? Expected tokens must appear in order
    (extra text in the Doc is tolerated) with coverage >= min_coverage, and every heading and code line must
    be present in full. Returns {match, coverage, missing[]} where `missing` shows unmatched runs in context."""
    exp = doc_comparable_tokens(markdown_to_doc_text(md))
    act = doc_comparable_tokens(actual_text)
    sm = difflib.SequenceMatcher(None, exp, act, autojunk=False)
    coverage = sum(b.size for b in sm.get_matching_blocks()) / len(exp) if exp else 1.0
    joined = " ".join(act)
    missing = [" ".join(exp[max(i1 - 3, 0):i2 + 3]) for tag, i1, i2, _, _ in sm.get_opcodes()
               if tag in ("replace", "delete")][:5]
    missing += [f"[required] {s}" for s in _doc_required_segments(md) if s not in joined][:5]
    return {"match": coverage >= min_coverage and not any(m.startswith("[required]") for m in missing),
            "coverage": round(coverage, 4), "missing": missing}


_CODE_BLOCK = re.compile(r"<pre>(.*?)</pre>", re.S)


def _code_block_to_paragraph(m, label=True):
    """Drive's HTML importer returns HTTP 500 for some documents that contain <pre> blocks, whatever
    their size, so code is sent as a monospace paragraph with <br> line breaks and &nbsp; indents."""
    lang = re.search(r'<code class="language-([\w+#-]+)"', m.group(1))
    code = re.sub(r"</?code[^>]*>", "", m.group(1)).rstrip("\n")
    lines = [re.sub(r"^ +", lambda k: "&nbsp;" * len(k.group(0)), line) for line in code.split("\n")]
    # Drive ignores a paragraph background and drops a small styled label paragraph, so the code sits in a
    # one-cell shaded table whose first line is the (bold) language name. Drive's text export does not
    # reliably keep that label, so verify-doc builds its expectation without it (label=False).
    head = f'<b>{lang.group(1).upper()}</b><br>\n' if lang and label else ""
    return ('<table style="width:100%;border-collapse:collapse"><tr><td style="background-color:#f1f3f4;padding:8px">'
            '<span style="font-family:Courier New,monospace">' + head + "<br>\n".join(lines) + "</span></td></tr></table>")


_DOLLAR = '<span style="font-family:Courier New,monospace">$</span>'


def _protect_dollars(html):
    """Drive's HTML importer silently deletes the text between two bare `$` signs (seen as
    `$(a)/x/$(b)` losing `$(a)/x/$`), so each `$` in text is wrapped in a styled span."""
    return re.sub(r"(?<=>)[^<]+", lambda m: m.group(0).replace("$", _DOLLAR), html)


ASSET_PATH = re.compile(r"runs/[A-Za-z0-9_-]+/assets/[A-Za-z0-9_.-]+\.png")


def _placeholder_to_html(spec):
    """An image-prompt placeholder: plain text in a shaded box. The same HTML is used for the upload and for
    verify-doc's expectation, because every word of it is real Doc text (nothing depends on an image)."""
    e = html_lib.escape
    lines = [f"<b>[IMAGE TO ADD \u00b7 {e(str(spec['id']))} \u00b7 {e(str(spec['label']))} \u00b7 {e(str(spec['aspect']))}]</b>",
             f"Prompt: {e(str(spec['prompt']))}", f"Alt text: {e(str(spec['alt']))}", f"Caption: {e(str(spec['caption']))}",
             "<i>Replace this box with the image, then delete this text.</i>"]
    return ('<table style="width:100%;border-collapse:collapse"><tr><td style="background-color:#fff8e1;padding:8px">'
            + "<br>\n".join(lines) + "</td></tr></table>")


def _asset_to_html(spec, render, root):
    """`type: asset` blocks are written only by `blog.py apply-visuals`; the draft checks reject them in a draft."""
    import base64
    if spec.get("kind") == "placeholder":
        return _placeholder_to_html(spec)
    alt = html_lib.escape(str(spec.get("alt", "")))
    if not render:
        return f"<p>{alt}</p>"  # Drive's text export includes an image's alt text
    path = str(spec.get("path", ""))
    full = (Path(root) / path).resolve()
    allowed = (Path(root) / "runs").resolve()
    if not ASSET_PATH.fullmatch(path) or allowed not in full.parents or full.parent.name != "assets" or not full.is_file():
        raise ValueError(f"visual asset path not allowed or missing: {path!r}")
    png = base64.b64encode(full.read_bytes()).decode()
    return f'<p><img src="data:image/png;base64,{png}" alt="{alt}" width="560"/></p>'


def _visual_to_html(m, render, root=ROOT):
    """A `visual` block becomes an inline PNG (base64 data URI, which Drive's importer keeps). Invalid specs
    are dropped here; the `visuals` hard check rejects them before delivery."""
    import base64
    import visuals
    try:
        raw = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        raw = None
    if isinstance(raw, dict) and raw.get("type") == "asset":
        return _asset_to_html(raw, render, root)
    spec = visuals.parse_blocks(m.group(0))[0][0]
    if not spec:
        return ""
    if not render:
        return f"<p>{html_lib.escape(spec['title'])}</p>"  # Drive's text export includes an image's alt text
    png = base64.b64encode(visuals.render_png(spec)).decode()
    return f'<p><img src="data:image/png;base64,{png}" alt="{html_lib.escape(spec["title"])}" width="560"/></p>'


def markdown_to_html(md, render_visuals=True, code_labels=True, root=ROOT):
    """The HTML uploaded to Drive for `md` (front matter dropped). Used by drive_server.create_doc
    and, via markdown_to_doc_text, by verify-doc, so the two cannot drift apart."""
    import markdown
    import visuals
    body = md.split("\n---\n", 1)[-1] if md.startswith("---\n") else md
    body = visuals.VISUAL_BLOCK.sub(lambda m: "\n\n" + _visual_to_html(m, render_visuals, root) + "\n\n", body)
    html = markdown.markdown(body, extensions=["tables", "fenced_code"])
    return _protect_dollars(_CODE_BLOCK.sub(lambda m: _code_block_to_paragraph(m, code_labels), html))


def markdown_to_doc_text(md):
    """Visible text a Google Doc should show for `md`: markdown_to_html with the tags stripped and without
    the decorative code-language label (Drive's text export does not reliably keep it)."""
    p = _TextExtractor()
    p.feed(markdown_to_html(md, render_visuals=False, code_labels=False))
    return html_lib.unescape("".join(p.parts))
