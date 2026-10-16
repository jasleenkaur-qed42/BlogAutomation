"""Tiny .env loader and delivery-config access shared by the MCP servers."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(root=ROOT):
    p = Path(root) / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def require(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} is not set (put it in .env; see .env.example)")
    return v


def delivery_config(root=ROOT):
    return json.loads((Path(root) / "config" / "delivery.json").read_text())
