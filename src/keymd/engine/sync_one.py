"""sync_one.py — incremental re-index of one file + cascade-refresh dependents."""
from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.index import _lang_for
from keymd.engine.parsers.base import get_parser_for
from keymd.engine.refresh import refresh_one


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _dependents(con, src_path: str) -> list[str]:
    """Files that have a resolved edge pointing into src_path."""
    rows = con.execute(
        "SELECT DISTINCT from_path FROM edges WHERE to_path=? AND from_path!=?",
        (src_path, src_path)).fetchall()
    return [r[0] for r in rows]


def sync_one(src_path: str) -> None:
    p = Path(src_path)
    db_path = config.index_path()
    if not db_path.exists():
        return
    parser = get_parser_for(p)
    if parser is None or not p.exists():
        return
    con = db.connect(db_path)
    # Canonical key the index uses (realpath: symlink + case). A mis-cased or
    # symlinked arg under os.path.abspath would DELETE nothing then re-INSERT a
    # DUPLICATE corrupt row; config.canonical keeps build/query/sync aligned.
    sp = config.canonical(src_path)

    # capture dependents BEFORE we mutate edges (so a removed call still cascades)
    dependents = set(_dependents(con, sp))

    con.execute("DELETE FROM symbols WHERE path=?", (sp,))
    con.execute("DELETE FROM edges WHERE from_path=?", (sp,))
    result = parser.parse(p)
    con.execute(
        "INSERT OR REPLACE INTO files(path, lang, sha256, mtime, line_count, "
        "has_keymd, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sp, _lang_for(p), _file_sha(p), p.stat().st_mtime, result.line_count,
         1 if os.path.exists(sp[:-len(p.suffix)] + ".key.md") else 0, time.time()))
    con.executemany(
        "INSERT OR IGNORE INTO symbols(path, name, kind, line, signature) "
        "VALUES (?, ?, ?, ?, ?)",
        [(sp, s.name, s.kind, s.line, s.signature) for s in result.symbols])
    con.executemany(
        "INSERT OR IGNORE INTO edges(from_path, from_name, to_name, to_path, "
        "kind, line) VALUES (?, ?, ?, NULL, ?, ?)",
        [(sp, e.from_name, e.to_name, e.kind, e.line) for e in result.edges])
    # re-resolve edges touching this file (both directions)
    con.execute("""
        UPDATE edges SET to_path = (
            SELECT path FROM symbols s WHERE s.name = edges.to_name
            GROUP BY s.name HAVING COUNT(DISTINCT s.path)=1 LIMIT 1)
        WHERE to_path IS NULL""")
    con.commit()
    dependents |= set(_dependents(con, sp))
    con.close()

    # refresh own sidecar + each dependent that already has one
    refresh_one(sp)
    for dep in dependents:
        if os.path.exists(dep[:-len(Path(dep).suffix)] + ".key.md"):
            refresh_one(dep)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        sync_one(arg)
        print(f"{arg}: synced")
