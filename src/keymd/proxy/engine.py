"""engine.py — thin façade over the Phase-1 engine for the proxy layer.

Consumes only the Shared Contracts (query.*, render_keymd, the files table).
Hardened per the Phase-3a adversarial review:
  - canon(): realpath canonicalization matching build()'s resolved storage
    (fixes symlinked-root / Windows-casing gate bypass).
  - full(): project-root confinement (reuses the engine's _confined guard) +
    a line cap so the escape hatch can't exfiltrate arbitrary files or dump
    an unbounded blob.
  - every structure query degrades gracefully when no index exists (no
    SystemExit escaping into the ASGI worker) and keymd_search survives
    arbitrary FTS5 syntax.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from keymd.engine import config, db, query
from keymd.engine.keymd_render import render_keymd
from keymd.engine.refresh import _confined

# Cap on keymd_read_full so the model-advertised full-read escape hatch cannot
# dump a huge file (token/cost/memory) and silently undo the gate's savings.
MAX_FULL_LINES = 800


def canon(path: str) -> str:
    """Canonical key matching build()'s resolved storage. realpath resolves
    symlinks and normalizes to the on-disk case, so a model-supplied path
    (relative, symlinked, or mis-cased) matches files.path."""
    return os.path.realpath(path)


def _index_ready() -> bool:
    return config.index_path().exists()


def _con_or_none():
    return db.connect(config.index_path()) if _index_ready() else None


def summary(abspath: str) -> str | None:
    con = _con_or_none()
    if con is None:
        return None
    row = con.execute("SELECT 1 FROM files WHERE path=?", (abspath,)).fetchone()
    if row is None:
        con.close()
        return None
    text = render_keymd(con, abspath)
    con.close()
    return text


def is_indexed_large(abspath: str, threshold: int) -> bool:
    con = _con_or_none()
    if con is None:
        return False
    row = con.execute("SELECT line_count FROM files WHERE path=?",
                      (abspath,)).fetchone()
    con.close()
    return bool(row) and row[0] > threshold


def full(abspath: str) -> str:
    # Confinement: never read outside the project root (confused-deputy guard).
    if not _confined(abspath):
        return f"(refused: {abspath} is outside the project root)"
    try:
        text = Path(abspath).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(error reading {abspath}: {e})"
    lines = text.splitlines()
    if len(lines) > MAX_FULL_LINES:
        head = "\n".join(lines[:MAX_FULL_LINES])
        return (head + f"\n\n(...truncated {len(lines) - MAX_FULL_LINES} lines; "
                "call keymd_read for the summary or keymd_search to locate a region)")
    return text


def impact(abspath: str) -> dict:
    if not _index_ready():
        return {"error": "index not built — run `keymd build`"}
    return query.impact(abspath)


def callers(symbol: str) -> dict:
    if not _index_ready():
        return {"error": "index not built — run `keymd build`"}
    return query.callers(symbol)


def callees(abspath: str) -> list:
    if not _index_ready():
        return []
    return query.callees(abspath)


def search(text: str, limit: int = 15) -> list:
    if not _index_ready():
        return []
    try:
        return query.search(text, limit)
    except sqlite3.OperationalError:
        # Model text isn't valid FTS5 (e.g. "a AND b", "foo:bar") — retry it as
        # a single quoted literal phrase; give up gracefully if still invalid.
        try:
            return query.search('"' + text.replace('"', '""') + '"', limit)
        except sqlite3.OperationalError:
            return []
