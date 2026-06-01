"""refresh.py — (re)generate one .key.md sidecar from the index.

Whole-file generation (no human region). Atomic write, idempotent excluding
the timestamp line, with realpath confinement so a symlinked path cannot write
outside the project root.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.keymd_render import render_keymd, strip_timestamp
from keymd.engine.parsers.base import get_parser_for


def _confined(path: str) -> bool:
    try:
        real = os.path.realpath(path)
        root = os.path.realpath(str(config.project_root()))
    except OSError:
        return False
    return real == root or real.startswith(root + os.sep)


def refresh_one(src_path: str) -> bool:
    """Create/refresh the sibling .key.md for src_path. True iff it changed."""
    p = Path(src_path)
    if not p.exists() or get_parser_for(p) is None:
        return False
    # Canonical key the index uses (realpath: resolves symlinks + case), so a
    # relative/mis-cased CLI arg matches the stored rows instead of writing an
    # orphan. Shared with build/query/sync/proxy/watcher via config.canonical.
    abs_src = config.canonical(src_path)
    if not _confined(abs_src):
        return False
    key_path = Path(abs_src[:-len(p.suffix)] + ".key.md")
    if key_path.exists() and not _confined(str(key_path)):
        return False
    db_path = config.index_path()
    if not db_path.exists():
        return False

    con = db.connect(db_path)
    new_content = render_keymd(con, abs_src)
    con.close()

    existing = key_path.read_text(encoding="utf-8") if key_path.exists() else ""
    if existing and strip_timestamp(new_content) == strip_timestamp(existing):
        return False

    tmp = key_path.with_suffix(key_path.suffix + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    os.replace(tmp, key_path)

    try:
        con = db.connect(db_path)
        sha = __import__("hashlib").sha256(new_content.encode()).hexdigest()
        con.execute(
            "INSERT OR REPLACE INTO keymds(path, src_path, sha256, "
            "auto_refreshed_at) VALUES (?, ?, ?, ?)",
            (str(key_path), abs_src, sha, time.time()))
        # Keep FTS current, keyed by SOURCE path (matching build()'s FTS fill) so a
        # refreshed file updates its one search row instead of creating a duplicate
        # under the sidecar path. Content is the rendered summary.
        con.execute("DELETE FROM keymd_fts WHERE path=?", (abs_src,))
        con.execute("INSERT INTO keymd_fts(path, content) VALUES (?, ?)",
                    (abs_src, new_content))
        con.commit()
        con.close()
    except sqlite3.Error:
        pass
    return True


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(f"{arg}: {'updated' if refresh_one(arg) else 'no change'}")
