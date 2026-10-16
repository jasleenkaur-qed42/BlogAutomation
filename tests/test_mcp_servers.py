import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC / "mcp_servers"))
import drive_server, env, slack_server  # noqa: E402

CFG = {"drive_folder_name": "Blogs", "drive_parent_id": None, "slack_channel_id": "CHAN"}


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(drive_server, "delivery_config", lambda: CFG)
    monkeypatch.setattr(slack_server, "delivery_config", lambda: CFG)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(drive_server, "_log_diag", lambda entry: None)  # keep tests out of runs/_drive_diag.log


def test_slack_wrong_channel_and_empty():
    with pytest.raises(ValueError):
        slack_server.post_message("OTHER", "hi", _post=lambda *a: {"ok": True})
    with pytest.raises(ValueError):
        slack_server.post_message("CHAN", "  ", _post=lambda *a: {"ok": True})


def test_slack_ok_payload_and_errors():
    seen = {}
    def fake(token, payload):
        seen.update(token=token, **payload); return {"ok": True, "ts": "1.2", "channel": "CHAN"}
    assert slack_server.post_message("CHAN", "hello", _post=fake)["ts"] == "1.2"
    assert seen["token"] == "xoxb-test" and seen["link_names"] is False and seen["unfurl_links"] is False
    with pytest.raises(RuntimeError, match="not_in_channel"):
        slack_server.post_message("CHAN", "x", _post=lambda *a: {"ok": False, "error": "not_in_channel"})


def test_slack_missing_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN")
    with pytest.raises(RuntimeError, match="SLACK_BOT_TOKEN"):
        slack_server.post_message("CHAN", "x", _post=lambda *a: {"ok": True})


class FakeSvc:
    """Fake Drive client; `folders` is what a Blogs-folder search returns."""
    def __init__(self, folders=()):
        self.folders, self.calls = list(folders), []
    def files(self): return self
    def create(self, **kw): self.calls.append(("create", kw)); return self
    def list(self, **kw): self.calls.append(("list", kw)); return self
    def export(self, **kw): self.calls.append(("export", kw)); return self
    def execute(self):
        kind, kw = self.calls[-1]
        if kind == "create":
            return {"id": "NEWFOLDER"} if kw["body"]["mimeType"] == drive_server.FOLDER_MIME else {"id": "D1", "webViewLink": "https://docs/D1"}
        if kind == "list":
            return {"files": self.folders if drive_server.FOLDER_MIME in kw["q"] else [{"id": "D1", "name": "n"}]}
        return b"text"
    def kinds(self): return [(k, kw.get("body", {}).get("mimeType")) for k, kw in self.calls]


@pytest.fixture(autouse=True)
def clear_cache():
    drive_server._folder_cache.clear()


def test_existing_blogs_folder_is_reused():
    svc = FakeSvc(folders=[{"id": "EXIST", "name": "Blogs"}])
    drive_server.create_doc("T", "body", _service=svc)
    assert ("create", drive_server.FOLDER_MIME) not in svc.kinds()
    assert svc.calls[-1][1]["body"]["parents"] == ["EXIST"]


def test_missing_blogs_folder_is_created_once():
    svc = FakeSvc(folders=[])
    drive_server.create_doc("T1", "body", _service=svc)
    drive_server.create_doc("T2", "body", _service=svc)
    assert svc.kinds().count(("create", drive_server.FOLDER_MIME)) == 1  # cached after first
    assert svc.calls[-1][1]["body"]["parents"] == ["NEWFOLDER"]


def test_folder_name_and_parent_come_from_config(monkeypatch):
    monkeypatch.setattr(drive_server, "delivery_config", lambda: {"drive_folder_name": "It's Blogs", "drive_parent_id": "PAR"})
    svc = FakeSvc(folders=[])
    drive_server.ensure_folder(svc)
    q = svc.calls[0][1]["q"]
    assert "It\\'s Blogs" in q and "'PAR' in parents" in q
    assert svc.calls[1][1]["body"]["parents"] == ["PAR"]


def test_drive_create_builds_native_doc():
    svc = FakeSvc(folders=[{"id": "EXIST"}])
    r = drive_server.create_doc("T [run:x]", "---\ntitle: a\n---\n# H\n\nbody", _service=svc)
    kw = svc.calls[-1][1]
    assert r == {"id": "D1", "url": "https://docs/D1"}
    assert kw["body"] == {"name": "T [run:x]", "mimeType": drive_server.DOC_MIME, "parents": ["EXIST"]}
    assert kw["supportsAllDrives"] is True


class DriveErr(Exception):
    def __init__(self, status):
        self.resp = type("R", (), {"status": status})()


class FlakySvc(FakeSvc):
    """Doc creation fails with `status` for the first `fails` attempts; `landed` = the failed create still made the Doc."""
    def __init__(self, fails, status=500, landed=False):
        super().__init__(folders=[{"id": "EXIST"}])
        self.fails, self.status, self.landed, self.doc_creates = fails, status, landed, 0
    def execute(self):
        kind, kw = self.calls[-1]
        if kind == "create" and kw["body"]["mimeType"] == drive_server.DOC_MIME:
            self.doc_creates += 1
            if self.doc_creates <= self.fails:
                raise DriveErr(self.status)
        if kind == "list" and drive_server.FOLDER_MIME not in kw["q"]:
            return {"files": [{"id": "LANDED", "webViewLink": "https://docs/LANDED"}] if self.landed else []}
        return super().execute()


@pytest.fixture
def delays(monkeypatch):
    slept = []
    monkeypatch.setattr(drive_server, "_sleep", slept.append)
    return slept


def test_create_doc_retries_transient_5xx_then_succeeds(delays):
    svc = FlakySvc(fails=1)
    assert drive_server.create_doc("T", "body", _service=svc)["id"] == "D1"
    assert svc.doc_creates == 2 and delays == [drive_server._RETRY_DELAYS[0]]


def test_create_doc_reuses_doc_that_a_failed_attempt_created(delays):
    svc = FlakySvc(fails=1, landed=True)
    assert drive_server.create_doc("T", "body", _service=svc) == {"id": "LANDED", "url": "https://docs/LANDED"}
    assert svc.doc_creates == 1  # no duplicate Doc


def test_create_doc_gives_up_after_bounded_retries(delays):
    svc = FlakySvc(fails=99)
    with pytest.raises(DriveErr):
        drive_server.create_doc("T", "body", _service=svc)
    assert svc.doc_creates == len(drive_server._RETRY_DELAYS) + 1 and delays == list(drive_server._RETRY_DELAYS)


def test_create_doc_does_not_retry_client_errors(delays):
    svc = FlakySvc(fails=99, status=403)
    with pytest.raises(DriveErr):
        drive_server.create_doc("T", "body", _service=svc)
    assert svc.doc_creates == 1 and delays == []


def test_drive_search_escapes_and_read():
    svc = FakeSvc(folders=[{"id": "EXIST"}])
    drive_server.search_docs("it's [run:x]", _service=svc)
    q = svc.calls[-1][1]["q"]
    assert "it\\'s" in q and "trashed = false" in q and "'EXIST' in parents" in q
    assert drive_server.read_doc("D1", _service=svc) == "text"


def test_read_doc_save_to_stays_under_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_server, "ROOT", tmp_path)
    svc = FakeSvc(folders=[{"id": "EXIST"}])
    out = drive_server.read_doc_to_file("D1", "runs/r1/delivery/rb.txt", _service=svc)
    assert out["chars"] == 4 and (tmp_path / "runs/r1/delivery/rb.txt").read_text() == "text"
    with pytest.raises(ValueError):
        drive_server.read_doc_to_file("D1", "../evil.txt", _service=svc)
    with pytest.raises(ValueError):
        drive_server.read_doc_to_file("D1", "config/x.txt", _service=svc)


def test_no_dangerous_surface():
    names = " ".join(dir(drive_server) + dir(slack_server)).lower()
    for bad in ("share", "delete", "permission", "trash", "update_doc", "copy"):
        assert bad not in names


def test_env_loader(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# c\nFOO_X='bar'\n")
    monkeypatch.delenv("FOO_X", raising=False)
    env.load_env(tmp_path)
    assert env.require("FOO_X") == "bar"
    with pytest.raises(RuntimeError):
        env.require("NOPE_X")


def test_missing_token_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_server, "ROOT", tmp_path)
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", "nope.json")
    with pytest.raises(RuntimeError, match="drive_auth.py"):
        drive_server.load_credentials()


def test_expired_token_refreshed_and_saved(tmp_path, monkeypatch):
    import google.oauth2.credentials as gc
    monkeypatch.setattr(drive_server, "ROOT", tmp_path)
    (tmp_path / "t.json").write_text("{}")
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", "t.json")

    class FakeCreds:
        valid, expired, refresh_token = False, True, "r"
        def refresh(self, req): FakeCreds.valid = True
        def to_json(self): return '{"refreshed": true}'
    monkeypatch.setattr(gc.Credentials, "from_authorized_user_file", staticmethod(lambda *a, **k: FakeCreds()))
    assert drive_server.load_credentials().valid
    assert (tmp_path / "t.json").read_text() == '{"refreshed": true}'


def test_unrefreshable_token_errors(tmp_path, monkeypatch):
    import google.oauth2.credentials as gc
    monkeypatch.setattr(drive_server, "ROOT", tmp_path)
    (tmp_path / "t.json").write_text("{}")
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", "t.json")

    class Dead:
        valid, expired, refresh_token = False, True, None
    monkeypatch.setattr(gc.Credentials, "from_authorized_user_file", staticmethod(lambda *a, **k: Dead()))
    with pytest.raises(RuntimeError, match="Re-run"):
        drive_server.load_credentials()
