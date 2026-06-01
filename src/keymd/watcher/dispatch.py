"""dispatch.py — route a changed path to the right index update.

A source-file write triggers an incremental sync_one (re-index + cascade
refresh); a .key.md write re-indexes that sidecar into FTS. Paths are
realpath-canonicalized to match build()'s resolved keys (same class of fix as
the proxy gate)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.keymd_render import render_keymd
from keymd.engine.parsers.base import get_parser_for
from keymd.engine.sync_one import sync_one


def _reindex_keymd(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    content = p.read_text(encoding="utf-8", errors="replace")
    sha = hashlib.sha256(content.encode()).hexdigest()
    src = path[:-len(".key.md")]
    src_path = next((src + e for e in config.index_extensions()
                     if Path(src + e).exists()), "")
    con = db.connect(config.index_path())
    # FTS is keyed by SOURCE path and fed from the rendered summary (matching
    # build/refresh), so a sidecar write refreshes its source's one search row.
    # Fall back to the sidecar's own text only if the source is unknown.
    if src_path:
        con.execute("DELETE FROM keymd_fts WHERE path=?", (src_path,))
        con.execute("INSERT INTO keymd_fts(path, content) VALUES (?, ?)",
                    (src_path, render_keymd(con, config.canonical(src_path))))
    con.execute("INSERT OR REPLACE INTO keymds(path, src_path, sha256, "
                "auto_refreshed_at) VALUES (?, ?, ?, NULL)", (path, src_path, sha))
    con.commit()
    con.close()


def on_change(path: str) -> None:
    """Single entry point. Canonicalizes to the index's resolved key first."""
    if not config.index_path().exists():
        return
    path = config.canonical(path)
    if path.endswith(".key.md"):
        _reindex_keymd(path)
    elif get_parser_for(Path(path)) is not None:
        sync_one(path)
