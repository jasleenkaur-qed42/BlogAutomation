import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC / "mcp_servers"))
import blog  # noqa: E402
import drive_server  # noqa: E402

HTML = ('<html><body><h1>Post</h1><p>Read <a href="https://www.google.com/url?q=https://example.com/x&amp;sa=D">this</a>'
        "</p></body></html>")


class Req:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class Files:
    def __init__(self, mime="application/vnd.google-apps.document", name="My post"):
        self.mime, self.name, self.exported = mime, name, None

    def get(self, **kw):
        return Req({"name": self.name, "mimeType": self.mime})

    def export(self, **kw):
        self.exported = kw
        return Req(HTML.encode())


class Svc:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


def test_read_doc_markdown_saves_markdown_under_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_server, "ROOT", tmp_path)
    files = Files()
    out = drive_server.read_doc_markdown("D1", "runs/r1/source/gdoc.md", _service=Svc(files))
    text = (tmp_path / "runs/r1/source/gdoc.md").read_text()
    assert "# Post" in text and "[this](https://example.com/x)" in text
    assert out == {"saved_to": str(tmp_path / "runs/r1/source/gdoc.md"), "chars": len(text), "title": "My post"}
    assert files.exported["mimeType"] == "text/html"


def test_read_doc_markdown_rejects_bad_targets_and_non_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_server, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        drive_server.read_doc_markdown("D1", "../evil.md", _service=Svc(Files()))
    with pytest.raises(ValueError):
        drive_server.read_doc_markdown("D1", "config/x.md", _service=Svc(Files()))
    with pytest.raises(ValueError, match="Google Doc"):
        drive_server.read_doc_markdown("D1", "runs/r1/source/gdoc.md", _service=Svc(Files(mime="application/pdf")))


def test_hook_treats_read_doc_markdown_as_read_only(root):
    ok, _ = blog.cmd_allow_delivery(root, {"tool_name": "mcp__blog-drive__read_doc_markdown", "tool_input": {}})
    assert ok


def test_settings_allow_the_new_tool():
    import json
    allow = json.loads((SRC / ".claude" / "settings.json").read_text())["permissions"]["allow"]
    assert "mcp__blog-drive__read_doc_markdown" in allow
