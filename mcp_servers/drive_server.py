#!/usr/bin/env python3
"""Local Google Drive MCP server (OAuth as the user): create_doc, search_docs, read_doc, read_doc_markdown. No share/update/copy/delete."""
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import ROOT, delivery_config, load_env  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from common import markdown_to_html  # noqa: E402
from source_import import html_to_markdown  # noqa: E402

# Full scope: the server must find a "Blogs" folder the user created by hand. Only create/search/read are exposed.
SCOPES = ["https://www.googleapis.com/auth/drive"]
DOC_MIME = "application/vnd.google-apps.document"
FOLDER_MIME = "application/vnd.google-apps.folder"
_folder_cache = {}
_STARTED = time.monotonic()
_calls = 0


def _log_diag(entry):
    """Best-effort diagnostic line per create_doc attempt (runs/ is gitignored); never raises."""
    try:
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pid": os.getpid(), **entry}
        with open(ROOT / "runs" / "_drive_diag.log", "a") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def load_credentials():
    """Load the user's OAuth token (created by drive_auth.py), refreshing and re-saving it when expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    path = ROOT / os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "secrets/google-token.json")
    if not path.exists():
        raise RuntimeError(f"{path} not found. Run: ./.venv/bin/python mcp_servers/drive_auth.py")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            raise RuntimeError("Google token is invalid and cannot be refreshed. Re-run mcp_servers/drive_auth.py")
        creds.refresh(Request())
        path.write_text(creds.to_json())
        os.chmod(path, 0o600)
    return creds


def build_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=load_credentials(), cache_discovery=False)


def _q(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def ensure_folder(svc):
    """Return the id of the configured folder (default 'Blogs'), creating it if it does not exist."""
    cfg = delivery_config()
    name, parent = cfg["drive_folder_name"], cfg.get("drive_parent_id")
    key = (name, parent)
    if key in _folder_cache:
        return _folder_cache[key]
    q = f"name = '{_q(name)}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    if parent:
        q += f" and '{_q(parent)}' in parents"
    found = svc.files().list(q=q, fields="files(id,name)", orderBy="createdTime", supportsAllDrives=True,
                             includeItemsFromAllDrives=True, pageSize=1).execute().get("files", [])
    if found:
        fid = found[0]["id"]
    else:
        body = {"name": name, "mimeType": FOLDER_MIME, **({"parents": [parent]} if parent else {})}
        fid = svc.files().create(body=body, fields="id", supportsAllDrives=True).execute()["id"]
    _folder_cache[key] = fid
    return fid


_RETRY_DELAYS = (3, 8)  # seconds to wait before retry 1 and 2 of a transient Drive error
_sleep = time.sleep


def _is_transient(e):
    return getattr(getattr(e, "resp", None), "status", None) in (429, 500, 502, 503, 504)


def _find_by_name(svc, title):
    """The Doc already in the configured folder with exactly this name, as {id, webViewLink}, else None."""
    try:
        q = f"'{_q(ensure_folder(svc))}' in parents and name = '{_q(title)}' and mimeType = '{DOC_MIME}' and trashed = false"
        found = svc.files().list(q=q, fields="files(id,webViewLink)", supportsAllDrives=True,
                                 includeItemsFromAllDrives=True, pageSize=1).execute().get("files", [])
        return found[0] if found else None
    except Exception:
        return None


def create_doc(title: str, content: str, _service=None) -> dict:
    """Create a native Google Doc from markdown in the configured folder. Returns {id, url}."""
    from googleapiclient.http import MediaIoBaseUpload
    global _calls
    _calls += 1
    t0 = time.monotonic()
    diag = {"call_no": _calls, "server_uptime_s": round(t0 - _STARTED, 1), "folder_cached": bool(_folder_cache)}
    try:
        html = markdown_to_html(content)
        diag["html_bytes"] = len(html.encode())
        svc = _service or build_service()
        diag["t_service_s"] = round(time.monotonic() - t0, 2)
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                folder_id = ensure_folder(svc)
                diag.setdefault("t_folder_s", round(time.monotonic() - t0, 2))
                media = MediaIoBaseUpload(io.BytesIO(html.encode()), mimetype="text/html", resumable=False)
                f = svc.files().create(body={"name": title, "mimeType": DOC_MIME, "parents": [folder_id]},
                                       media_body=media, fields="id,webViewLink", supportsAllDrives=True).execute()
                break
            except Exception as e:
                if attempt == len(_RETRY_DELAYS) or not _is_transient(e):
                    raise
                diag.setdefault("retries", []).append({"status": e.resp.status, "after_s": round(time.monotonic() - t0, 2)})
                _sleep(_RETRY_DELAYS[attempt])
                f = _find_by_name(svc, title)  # a 5xx can still have created the Doc; never create a duplicate
                if f:
                    break
        diag["outcome"] = "ok"
        return {"id": f["id"], "url": f.get("webViewLink", f"https://docs.google.com/document/d/{f['id']}/edit")}
    except Exception as e:
        resp = getattr(e, "resp", None)
        diag.update(outcome="error", error_type=type(e).__name__, status=getattr(resp, "status", None),
                    reason=getattr(e, "reason", None) or str(e)[:200],
                    body=(getattr(e, "content", b"") or b"")[:500].decode("utf-8", "replace"))
        raise
    finally:
        diag.update(title=title, total_s=round(time.monotonic() - t0, 2))
        _log_diag(diag)


def search_docs(title: str, _service=None) -> list:
    """Find Docs in the configured folder whose name contains `title`. Returns [{id, name, url}]."""
    svc = _service or build_service()
    q = f"'{_q(ensure_folder(svc))}' in parents and name contains '{_q(title)}' and mimeType = '{DOC_MIME}' and trashed = false"
    res = svc.files().list(q=q, fields="files(id,name,webViewLink)", supportsAllDrives=True,
                           includeItemsFromAllDrives=True, pageSize=20).execute()
    return [{"id": f["id"], "name": f["name"], "url": f.get("webViewLink")} for f in res.get("files", [])]


def read_doc(doc_id: str, _service=None) -> str:
    """Export a Doc as plain text (for the read-back check)."""
    svc = _service or build_service()
    data = svc.files().export(fileId=doc_id, mimeType="text/plain").execute()
    return data.decode() if isinstance(data, bytes) else data


def read_doc_to_file(doc_id: str, save_to: str, _service=None) -> dict:
    """Export a Doc to a file under runs/ and return only its size, keeping the text out of the model context."""
    runs = (ROOT / "runs").resolve()
    target = (ROOT / save_to).resolve()
    if runs not in target.parents:
        raise ValueError("save_to must be a path under runs/")
    text = read_doc(doc_id, _service=_service)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return {"saved_to": str(target), "chars": len(text)}


def read_doc_markdown(doc_id: str, save_to: str, _service=None) -> dict:
    """Export a Google Doc as markdown (headings, lists, code-ish text and links survive) into a file under runs/.
    Read-only. Returns only {saved_to, chars, title}; the text stays out of the model context."""
    runs = (ROOT / "runs").resolve()
    target = (ROOT / save_to).resolve()
    if not (target.parent.name == "source" and target.name == "gdoc.md" and target.parent.parent.parent == runs):
        raise ValueError("save_to must be runs/<run-id>/source/gdoc.md")
    svc = _service or build_service()
    meta = svc.files().get(fileId=doc_id, fields="name,mimeType", supportsAllDrives=True).execute()
    if meta.get("mimeType") != DOC_MIME:
        raise ValueError("the file is not a Google Doc")
    data = svc.files().export(fileId=doc_id, mimeType="text/html").execute()
    md = html_to_markdown(data.decode() if isinstance(data, bytes) else data)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md)
    return {"saved_to": str(target), "chars": len(md), "title": str(meta.get("name", ""))[:120]}


def main():
    from mcp.server.fastmcp import FastMCP
    load_env()
    mcp = FastMCP("blog-drive")

    @mcp.tool(name="create_doc")
    def blog_create_doc(title: str, content: str) -> dict:
        """Create a native Google Doc from markdown in the Blogs folder (created if missing). Returns {id, url}."""
        return create_doc(title, content)

    @mcp.tool(name="search_docs")
    def blog_search_docs(title: str) -> list:
        """Find Docs in the configured folder whose name contains `title`."""
        return search_docs(title)

    @mcp.tool(name="read_doc")
    def blog_read_doc(doc_id: str, save_to: str = "") -> str | dict:
        """Export a Doc created by this app as plain text. With `save_to` (a path under runs/), write the text
        there and return only {saved_to, chars}."""
        return read_doc_to_file(doc_id, save_to) if save_to else read_doc(doc_id)

    @mcp.tool(name="read_doc_markdown")
    def blog_read_doc_markdown(doc_id: str, save_to: str) -> dict:
        """Read any Google Doc the user can open as markdown into a file under runs/. Returns {saved_to, chars, title}."""
        return read_doc_markdown(doc_id, save_to)

    mcp.run()


if __name__ == "__main__":
    main()
