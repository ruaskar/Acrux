"""settings.py — optional keymd.toml project config (stdlib tomllib).

Pure: path in → Settings out. Reads NO env and NO flags; callers resolve the
precedence chain (flag > env > keymd.toml > default). Contains no secrets — API
keys ride on request headers, never this file.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from keymd.engine import config


@dataclass
class Settings:
    threshold: int = 400
    host: str = "127.0.0.1"
    port: int = 8787
    wire: str = "openai"
    upstream: str | None = None


def config_path(root: Path | None = None) -> Path:
    return (root or config.project_root()) / "keymd.toml"


def load(root: Path | None = None) -> Settings:
    p = config_path(root)
    if not p.exists():
        return Settings()
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ValueError(f"keymd.toml at {p} is malformed: {e}") from e
    km = data.get("keymd", {}) or {}
    srv = km.get("serve", {}) or {}
    return Settings(
        threshold=int(km.get("threshold", 400)),
        host=str(srv.get("host", "127.0.0.1")),
        port=int(srv.get("port", 8787)),
        wire=str(srv.get("wire", "openai")),
        upstream=srv.get("upstream"),
    )
