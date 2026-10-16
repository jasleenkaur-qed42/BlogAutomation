#!/usr/bin/env python3
"""One-time Google OAuth login. Opens a browser, then saves a refresh token for drive_server.py.

Usage: ./.venv/bin/python mcp_servers/drive_auth.py
Needs an OAuth client of type "Desktop app" saved at GOOGLE_OAUTH_CLIENT_FILE (default secrets/google-oauth-client.json).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drive_server import ROOT, SCOPES  # noqa: E402
from env import load_env  # noqa: E402


def main():
    from google_auth_oauthlib.flow import InstalledAppFlow
    load_env()
    client = ROOT / os.environ.get("GOOGLE_OAUTH_CLIENT_FILE", "secrets/google-oauth-client.json")
    token = ROOT / os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "secrets/google-token.json")
    if not client.exists():
        sys.exit(f"{client} not found. Download the Desktop-app OAuth client JSON from Google Cloud and save it there.")
    creds = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES).run_local_server(port=0)
    token.parent.mkdir(exist_ok=True)
    token.write_text(creds.to_json())
    os.chmod(token, 0o600)
    print(f"Saved token to {token}")


if __name__ == "__main__":
    main()
