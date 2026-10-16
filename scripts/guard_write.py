#!/usr/bin/env python3
"""PreToolUse hook for blog subagents: Write and Edit are allowed only inside runs/<id>/incoming/."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent


def allowed(file_path):
    try:
        rel = Path(file_path).resolve().relative_to(root / "runs")
    except (ValueError, OSError):
        return False
    return len(rel.parts) == 3 and rel.parts[1] == "incoming"


if __name__ == "__main__":
    target = (json.load(sys.stdin).get("tool_input") or {}).get("file_path", "")
    if not target or not allowed(target):
        print(f"BLOCKED: subagents may only write runs/<id>/incoming/<file> (got {target!r})", file=sys.stderr)
        sys.exit(2)
