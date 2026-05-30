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
    """Canonical key matching the index — delegates to config.canonical so all
    faculties (build/query/refresh/sync/proxy/watcher) share ONE normalization."""
    return config.canonical(path)


def _index_ready() -> bool:
    return config.index_path().exists()


def _con_or_none():
    return db.connect(config.index_path()) if _index_ready() else None


def _doc_text(abspath: str) -> str | None:
    """Extracted text for a binary document (PDF/DOCX), else None — so ranged reads
    slice this cache instead of the unreadable binary file."""
    con = _con_or_none()
    if con is None:
        return None
    # canonicalize so a non-canonical caller can't miss the cache and fall through to
    # decoding a binary doc as UTF-8 (config.canonical is the key build/sync store under).
    row = con.execute("SELECT text FROM doc_text WHERE path=?",
                      (config.canonical(abspath),)).fetchone()
    con.close()
    return row[0] if row else None


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
    cached = _doc_text(abspath)                  # binary doc → serve extracted text
    if cached is not None:
        text = cached
    else:
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


def read_range(abspath: str, start: int, end: int) -> str:
    """Return just lines [start, end] (1-based inclusive) of a file — the cheap
    ranged read that lets an agent pull a region without the whole file. Confined."""
    if not _confined(abspath):
        return f"(refused: {abspath} is outside the project root)"
    cached = _doc_text(abspath)                  # binary doc → slice extracted text
    if cached is not None:
        lines = cached.splitlines()
    else:
        try:
            lines = Path(abspath).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            return f"(error reading {abspath}: {e})"
    if not lines:
        return f"({Path(abspath).name} is empty)"
    start = max(1, start)
    end = max(start, min(len(lines), end or start))
    if start > len(lines):
        return f"(L{start} is past end of file — {len(lines)} lines)"
    truncated = end - start + 1 > MAX_FULL_LINES
    if truncated:
        end = start + MAX_FULL_LINES - 1
    body = "\n".join(lines[start - 1:end])
    out = f"# {Path(abspath).name}  L{start}-{end}\n{body}"
    if truncated:                                   # never silently cut a section
        out += (f"\n\n(...truncated at {MAX_FULL_LINES} lines; call "
                f"keymd_read_range(path, {end + 1}, ...) for the rest)")
    return out


def read_symbol(abspath: str, symbol: str) -> str:
    """Return the source of one symbol (function/class/method) by name, using the
    indexed line span — so the agent reads exactly the region it cares about."""
    con = _con_or_none()
    if con is None:
        return "(index not built — run `keymd build`)"
    row = con.execute("SELECT line, end_line FROM symbols WHERE path=? AND name=?",
                      (abspath, symbol)).fetchone()
    con.close()
    if row is None:
        return (f"(symbol {symbol!r} not found in {Path(abspath).name}; "
                "call keymd_read for the symbol list)")
    line, end = row
    return read_range(abspath, line, end or line)


def edit(abspath: str, old: str, new: str) -> str:
    """Replace an exact, unique `old` snippet with `new`, then re-index the file so
    the summary/anchors stay fresh. Exact-match (not line-range) is immune to stale
    line numbers. Confined to the project root."""
    if not old:
        return "(edit refused: `old` must not be empty)"
    real = os.path.realpath(abspath)            # resolve once; read+write+sync use it
    if not _confined(real):
        return f"(refused: {abspath} is outside the project root)"
    if _doc_text(real) is not None:             # can't round-trip a text edit into a binary doc
        return "(cannot edit a binary document; keymd_edit works on text/code files)"
    try:
        text = Path(real).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(error reading {abspath}: {e})"
    n = text.count(old)
    if n == 0:
        return ("(edit refused: `old` not found — read the region first via "
                "keymd_read_symbol/keymd_read_range and copy it exactly)")
    if n > 1:
        return (f"(edit refused: `old` appears {n} times — add surrounding lines "
                "to make it unique)")
    updated = text.replace(old, new, 1)
    try:
        Path(real).write_text(updated, encoding="utf-8")
    except OSError as e:
        return f"(error writing {abspath}: {e})"
    # Re-index just this file so anchors/summary reflect the edit immediately.
    try:
        from keymd.engine.sync_one import sync_one
        sync_one(real)
    except Exception as e:  # a re-index hiccup must not mask the successful write
        return f"edited {Path(abspath).name} (1 replacement); re-index warning: {e}"
    note = ""
    if new:
        head = updated.count("\n", 0, updated.find(new)) + 1
        win = "\n".join(updated.splitlines()[head - 1:head - 1 + 6])
        note = f"\nL{head}+:\n{win}"
    return f"edited {Path(abspath).name} (1 replacement) and re-indexed.{note}"


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
