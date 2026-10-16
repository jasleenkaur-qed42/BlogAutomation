#!/usr/bin/env python3
"""Launcher for the vendored claude-image-gen MCP server (Gemini). Loads GEMINI_API_KEY like the other local MCP
servers, confines the output directory to runs/ so a generated image can only land inside a run, then replaces
itself with node."""
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import ROOT, load_env, require  # noqa: E402

BUNDLE = ROOT / "mcp_servers" / "claude-image-gen" / "bundle.js"


def main():
    load_env()
    require("GEMINI_API_KEY")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node (>= 20) is required for the image generation MCP server")
    os.environ["IMAGE_PROVIDER"] = "gemini"
    os.environ["IMAGE_OUTPUT_DIR"] = str(ROOT / "runs")
    os.execv(node, [node, str(BUNDLE)])


if __name__ == "__main__":
    main()
