#!/usr/bin/env python3
"""Local Slack MCP server: one tool, post_message, restricted to the configured channel."""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import delivery_config, load_env, require  # noqa: E402

API = "https://slack.com/api/chat.postMessage"


def _http_post(token, payload):
    req = urllib.request.Request(API, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def post_message(channel_id: str, text: str, run_id: str = "", _post=_http_post) -> dict:
    """Post a standalone message to the configured review channel. No mentions, no unfurls."""
    if channel_id != delivery_config()["slack_channel_id"]:
        raise ValueError("channel_id is not the configured review channel")
    if not text.strip():
        raise ValueError("text is empty")
    resp = _post(require("SLACK_BOT_TOKEN"), {"channel": channel_id, "text": text, "link_names": False,
                                              "unfurl_links": False, "unfurl_media": False})
    if not resp.get("ok"):
        raise RuntimeError(f"Slack error: {resp.get('error', 'unknown')}")
    return {"ts": resp.get("ts"), "channel": resp.get("channel")}


def main():
    from mcp.server.fastmcp import FastMCP
    load_env()
    mcp = FastMCP("blog-slack")

    @mcp.tool(name="post_message")
    def blog_post_message(channel_id: str, text: str, run_id: str) -> dict:
        """Post a standalone message to the configured review channel. run_id is the run's id (used by the delivery guard)."""
        return post_message(channel_id, text, run_id)

    mcp.run()


if __name__ == "__main__":
    main()
