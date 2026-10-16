from pathlib import Path

import pytest
import source_import as si
from improve_helpers import SOURCE_MD, make_docx

WORDS = " ".join(["word"] * 150)
DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def test_parse_gdoc_url():
    assert si.parse_gdoc_url(f"https://docs.google.com/document/d/{DOC_ID}/edit?usp=sharing") == DOC_ID
    assert si.parse_gdoc_url(f"https://docs.google.com/document/u/0/d/{DOC_ID}/edit") == DOC_ID
    assert si.parse_gdoc_url("https://docs.google.com/spreadsheets/d/" + DOC_ID) is None
    assert si.parse_gdoc_url("https://evil.example/document/d/" + DOC_ID) is None
    assert si.parse_gdoc_url("") is None


def test_classify_routes(tmp_path):
    (tmp_path / "post.md").write_text(SOURCE_MD)
    (tmp_path / "brief.md").write_text("---\ntopic: x\naudience: y\n---\nnotes\n")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "k.txt").write_text(WORDS)
    c = lambda a: si.classify_arg(a, tmp_path)
    assert c("") == {"mode": "ask"}
    assert c("Why tokens matter") == {"mode": "create", "topic": "Why tokens matter"}
    assert c("brief.md") == {"mode": "create", "brief": str(tmp_path / "brief.md")}
    r = c("post.md")
    assert r["mode"] == "improve" and r["kind"] == "local" and r["suggested_topic"] == "Design tokens for small teams"
    assert r["suggested_target_words"]["max"] > r["suggested_target_words"]["min"] > 0
    g = c(f"https://docs.google.com/document/d/{DOC_ID}/edit")
    assert g["mode"] == "improve" and g["kind"] == "gdoc" and g["doc_id"] == DOC_ID
    assert c("missing/draft.md")["mode"] == "error"          # a mistyped path is not a topic
    assert c("https://example.com/post")["mode"] == "error"
    assert c("secrets/k.txt")["mode"] == "error"
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    assert c("x.pdf")["mode"] == "error"


def test_import_text_formats(tmp_path):
    for name in ("a.md", "a.txt", "a.mdx"):
        (tmp_path / name).write_text(SOURCE_MD)
        r = si.import_file(tmp_path / name)
        assert r["markdown"] == SOURCE_MD and len(r["sha256"]) == 64 and r["ext"] == Path(name).suffix


def test_mdx_preserve_lines(tmp_path):
    (tmp_path / "a.mdx").write_text("import Demo from './Demo'\n\n<Demo prop=\"1\" />\n\n" + SOURCE_MD)
    r = si.import_file(tmp_path / "a.mdx")
    assert "import Demo from './Demo'" in r["preserve"] and any(l.startswith("<Demo") for l in r["preserve"])


def test_docx_converts_headings_and_reports_drops(tmp_path):
    paras = [("Heading1", "Tokens for teams"), (None, WORDS), ("Heading2", "Why they help"), (None, "Short paragraph here.")]
    (tmp_path / "a.docx").write_bytes(make_docx(paras))
    r = si.import_file(tmp_path / "a.docx")
    assert "# Tokens for teams" in r["markdown"] and "## Why they help" in r["markdown"] and r["ext"] == ".docx"


@pytest.mark.parametrize("name,data,msg", [
    ("empty.md", b"", "empty|too short"),
    ("short.txt", b"only a few words", "too short"),
    ("bin.md", b"\xff\xfe\x00bad" + b"\x80" * 50, "UTF-8"),
    ("bad.docx", b"not a zip", "docx"),
])
def test_unusable_sources_raise(tmp_path, name, data, msg):
    (tmp_path / name).write_bytes(data)
    with pytest.raises(si.SourceError, match=msg):
        si.import_file(tmp_path / name)


def test_too_big(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "MAX_BYTES", 100)
    (tmp_path / "big.md").write_text(SOURCE_MD)
    with pytest.raises(si.SourceError, match="too large"):
        si.import_file(tmp_path / "big.md")


def test_refuses_env_and_secrets(tmp_path):
    (tmp_path / ".env").write_text(WORDS)
    with pytest.raises(si.SourceError, match="not allowed"):
        si.import_file(tmp_path / ".env")


def test_derive_target_words_leaves_room_for_a_faq():
    # same word count either way; only the FAQ heading differs
    plain = si.derive_target_words(SOURCE_MD + "\n## Alpha beta gamma\n")
    faq = si.derive_target_words(SOURCE_MD + "\n## Frequently asked questions\n")
    assert plain["max"] - faq["max"] == 350 and plain["min"] == faq["min"]
    n = plain["min"] / 0.85
    assert plain["min"] < n < plain["max"]


def test_html_to_markdown_unwraps_google_redirects_and_drops_noise():
    html = ('<html><head><style>p{color:red}</style></head><body><h1>Title</h1>'
            '<p>See <a href="https://www.google.com/url?q=https://example.com/a&amp;sa=D&amp;source=editors">docs</a>'
            '<img src="data:image/png;base64,AAAA"></p><ul><li>one</li></ul></body></html>')
    md = si.html_to_markdown(html)
    assert "# Title" in md and "[docs](https://example.com/a)" in md and "- one" in md
    assert "google.com/url" not in md and "color:red" not in md and "base64" not in md
