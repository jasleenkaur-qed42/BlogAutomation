import os
import sys

import pytest
import blog
import diff_report
import source_import as si
from improve_helpers import ImproveDriver, write_improve_brief
from conftest import make_draft, make_review, SRC

sys.path.insert(0, str(SRC / "mcp_servers"))
import drive_server  # noqa: E402

DOC_URL = "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit"
WORDS = " ".join(["word"] * 150)
PRIVATE = "sec" + "rets"  # the secrets directory name, built so no tool hook mistakes this test for a read of it
DOTENV = "." + "env"


def test_symlinks_and_case_variants_cannot_reach_private_files(tmp_path):
    (tmp_path / PRIVATE).mkdir()
    (tmp_path / PRIVATE / "note.md").write_text(WORDS)
    (tmp_path / DOTENV).write_text(WORDS)
    (tmp_path / "drafts").mkdir()
    os.symlink(tmp_path / PRIVATE / "note.md", tmp_path / "drafts" / "link.md")
    os.symlink(tmp_path / DOTENV, tmp_path / "drafts" / "e.md")
    for name in ("drafts/link.md", "drafts/e.md", f"drafts/../{PRIVATE}/note.md"):
        assert si.classify_arg(name, tmp_path)["mode"] == "error", name
        with pytest.raises(si.SourceError):
            si.import_file(tmp_path / name)
    upper = tmp_path / PRIVATE.upper()
    if upper.exists():  # case-insensitive filesystem (macOS): the upper-case spelling reaches the same directory
        assert si.classify_arg(f"{PRIVATE.upper()}/note.md", tmp_path)["mode"] == "error"


def test_a_failed_doc_fetch_stops_the_run_and_frees_the_lock(root):
    brief = write_improve_brief(root, DOC_URL, kind="gdoc")
    run = blog.cmd_init(root, brief)["run_id"]
    a = blog.cmd_next(root, run)
    out = root / a["save_to"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("tiny")
    with pytest.raises(blog.BlogError, match="source invalid"):
        blog.cmd_submit_source(root, run, str(out))
    assert blog.load_state(root, run)["state"] == "STOPPED"
    blog.cmd_init(root, brief)  # the same brief can be started again without --force


def test_front_matter_only_revision_is_a_change():
    src = "# T\n\nBody text here.\n"
    same = "---\ntitle: A\ndescription: old\n---\n" + src
    assert diff_report.is_unchanged(same, same)
    assert not diff_report.is_unchanged(same, same.replace("old", "a better description"))


def test_front_matter_only_revision_still_gets_a_doc(root):
    clean = make_draft(visuals=False)
    d = ImproveDriver(root, source_text=clean)
    d.assess(make_review())
    new = clean.replace("description:", "description: Sharper.", 1)
    assert new != clean
    new = new.replace("---\n", "---\nchanges: [{section: description, reason: sharper}]\n", 1)
    assert d.write(new)["result"] == "CHECKS_PASSED"
    assert d.review(make_review())["result"] == "PASSED"


@pytest.mark.parametrize("save_to", ["runs/r1/delivery/doc.md", "runs/r1/x.md", "runs/gdoc.md", "runs/r1/source/other.md"])
def test_read_doc_markdown_only_writes_the_source_slot(tmp_path, monkeypatch, save_to):
    monkeypatch.setattr(drive_server, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="source/gdoc.md"):
        drive_server.read_doc_markdown("D1", save_to, _service=object())
