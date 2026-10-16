#!/usr/bin/env python3
"""PreToolUse hook: stop Claude from touching secrets/ or .env files."""
import json
import os
import re
import sys

SECRETS_DIR = re.compile(r"(^|[\s/'\"=:~])secrets(/|$|[\s'\"])")
ENV_FILE = re.compile(r"(^|[\s/'\"=:])\.env(?!\.(example|sample|template)\b)(?![A-Za-z0-9_])")


def hits(text):
    return bool(text) and bool(SECRETS_DIR.search(text) or ENV_FILE.search(text))


def candidates(tool, inp):
    if tool in ("Read", "Edit", "Write", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        yield path
        if path:
            yield os.path.realpath(path)  # catch symlinks into secrets/
    elif tool in ("Grep", "Glob"):
        for key in ("path", "glob", "pattern"):
            yield inp.get(key) or ""
    elif tool == "Bash":
        yield inp.get("command") or ""


def main():
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    if any(hits(c) for c in candidates(tool, inp)):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Blocked: secrets/ and .env are off-limits to Claude.",
            }
        }))


if __name__ == "__main__":
    main()
