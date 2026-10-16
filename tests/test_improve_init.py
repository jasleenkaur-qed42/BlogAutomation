import json

import pytest
import blog
from improve_helpers import SOURCE_MD, ImproveDriver, make_docx, write_improve_brief

DOC_URL = "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit"


def test_local_init_stores_source_and_starts_in_assess(root):
    d = ImproveDriver(root)
    st = d.state()
    rd = root / "runs" / d.run
    assert st["mode"] == "improve" and st["phase"] == "ASSESS" and st["state"] == "IN_PROGRESS"
    assert (rd / "source.md").read_text() == SOURCE_MD
    assert (rd / "source" / "original.md").read_text() == SOURCE_MD
    assert len(st["source"]["sha256"]) == 64
    assert st["brief"]["visuals"] == {"min": 0} and st["brief"]["images"] == {"min": 0}


def test_word_range_is_derived_when_the_brief_has_none(root):
    d = ImproveDriver(root, target_words=None)
    tw = d.state()["brief"]["target_words"]
    assert 0 < tw["min"] < tw["max"]


def test_docx_source(root):
    docx = root / "drafts" / "post.docx"
    docx.parent.mkdir()
    docx.write_bytes(make_docx([("Heading1", "Tokens"), (None, "word " * 150)]))
    run = blog.cmd_init(root, write_improve_brief(root, docx))["run_id"]
    assert "# Tokens" in (root / "runs" / run / "source.md").read_text()
    assert (root / "runs" / run / "source" / "original.docx").exists()


@pytest.mark.parametrize("make", [
    lambda r: r / "missing.md",                       # no such file
    lambda r: (r / "short.md", (r / "short.md").write_text("too short"))[0],
])
def test_bad_local_source_creates_no_run_and_no_lock(root, make):
    src = make(root)
    with pytest.raises(blog.BlogError, match="source invalid"):
        blog.cmd_init(root, write_improve_brief(root, src))
    assert not [p for p in (root / "runs").iterdir() if p.name != ".locks"]
    assert not (root / "runs" / ".locks").exists() or not list((root / "runs" / ".locks").iterdir())


def test_gdoc_init_waits_for_the_fetch(root):
    run = blog.cmd_init(root, write_improve_brief(root, DOC_URL, kind="gdoc", target_words=None))["run_id"]
    st = blog.load_state(root, run)
    assert st["phase"] == "FETCH_SOURCE" and "target_words" not in st["brief"]
    a = blog.cmd_next(root, run)
    assert a["action"] == "FETCH_GDOC" and a["doc_id"] == "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    assert a["save_to"] == f"runs/{run}/source/gdoc.md"
    out = root / a["save_to"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(SOURCE_MD)
    r = blog.cmd_submit_source(root, run, str(out))
    assert r["result"] == "SOURCE_READY" and r["words"] > 100
    st = blog.load_state(root, run)
    assert st["phase"] == "ASSESS" and st["brief"]["target_words"]["max"] > 0
    assert (root / "runs" / run / "source.md").read_text() == SOURCE_MD
    assert blog.cmd_next(root, run)["action"] == "REVIEW"


def test_gdoc_bad_url_and_bad_content(root):
    with pytest.raises(blog.BlogError, match="Google Docs URL"):
        blog.cmd_init(root, write_improve_brief(root, "https://example.com/x", kind="gdoc"))
    run = blog.cmd_init(root, write_improve_brief(root, DOC_URL, kind="gdoc"))["run_id"]
    a = blog.cmd_next(root, run)
    out = root / a["save_to"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("tiny")
    with pytest.raises(blog.BlogError, match="source invalid"):
        blog.cmd_submit_source(root, run, str(out))


def test_submit_source_out_of_order_and_wrong_path(root):
    d = ImproveDriver(root)
    with pytest.raises(blog.BlogError):
        blog.cmd_submit_source(root, d.run, "x")  # a local run is already past FETCH_SOURCE
    run = blog.cmd_init(root, write_improve_brief(root, DOC_URL, kind="gdoc"), force=True)["run_id"]
    with pytest.raises(blog.BlogError):
        blog.cmd_submit_source(root, run, "x")    # before next
    blog.cmd_next(root, run)
    with pytest.raises(blog.BlogError, match="unexpected path"):
        blog.cmd_submit_source(root, run, str(root / "other.md"))


def test_resume_mid_fetch_returns_the_fetch_again(root):
    run = blog.cmd_init(root, write_improve_brief(root, DOC_URL, kind="gdoc"))["run_id"]
    blog.cmd_next(root, run)
    assert blog.cmd_resume(root, run)["action"] == "FETCH_GDOC"


def test_create_runs_have_no_mode(driver):
    assert "mode" not in driver.state()


def test_classify_cli(root, capsys):
    (root / "drafts").mkdir()
    (root / "drafts" / "post.md").write_text(SOURCE_MD)
    assert blog.main(["classify", "drafts/post.md"], root=root) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "improve" and out["kind"] == "local"
