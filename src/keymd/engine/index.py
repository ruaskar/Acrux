"""index.py — build the symbol/edge graph for the active project into SQLite."""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.parsers.base import get_parser_for


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_source_files():
    exts = config.index_extensions()
    seen: set[str] = set()

    def _ok(p) -> bool:
        return (p.is_file() and any(p.name.endswith(e) for e in exts)
                and not config.is_excluded(str(p)))

    def _emit(p):
        key = config.canonical(str(p))
        if key not in seen:
            seen.add(key)
            return True
        return False

    for root in config.index_roots():
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if _ok(p) and _emit(p):
                yield p
    # top-level files directly under the project root (flat repos: app.py at root)
    try:
        for p in config.project_root().iterdir():
            if _ok(p) and _emit(p):
                yield p
    except OSError:
        pass


def iter_keymd_files():
    seen: set[str] = set()

    def _emit(p):
        key = config.canonical(str(p))
        if key not in seen:
            seen.add(key)
            return True
        return False

    for root in config.index_roots():
        if not root.exists():
            continue
        for p in root.rglob("*.key.md"):
            if not config.is_excluded(str(p)) and _emit(p):
                yield p
    try:
        for p in config.project_root().glob("*.key.md"):
            if not config.is_excluded(str(p)) and _emit(p):
                yield p
    except OSError:
        pass


_LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
}


def _lang_for(path: Path) -> str:
    # Human-readable language label, stored in files.lang and shown in the
    # .key.md header (e.g. "python", not "py"). Matches spec §2 sample header.
    return _LANG_BY_EXT.get(path.suffix) or path.suffix.lstrip(".") or "?"


def build(verbose: bool = True) -> dict:
    db_path = config.index_path()
    if db_path.exists():
        db_path.unlink()
    con = db.connect(db_path, create=True)

    files = list(iter_source_files())
    if verbose:
        print(f"Indexing {len(files)} source files…")

    n_sym = n_edge = 0
    t0 = time.time()
    for p in files:
        sp = config.canonical(str(p))
        parser = get_parser_for(p)
        if parser is None:
            continue
        try:
            sha = _file_sha(p)
            mtime = p.stat().st_mtime
        except OSError:
            continue
        result = parser.parse(p)
        sibling_key = sp[:-len(p.suffix)] + ".key.md"
        has_keymd = 1 if os.path.exists(sibling_key) else 0
        con.execute(
            "INSERT INTO files(path, lang, sha256, mtime, line_count, "
            "has_keymd, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sp, _lang_for(p), sha, mtime, result.line_count, has_keymd,
             time.time()),
        )
        con.executemany(
            "INSERT OR IGNORE INTO symbols(path, name, kind, line, signature, "
            "end_line) VALUES (?, ?, ?, ?, ?, ?)",
            [(sp, s.name, s.kind, s.line, s.signature, s.end_line)
             for s in result.symbols],
        )
        con.executemany(
            "INSERT OR IGNORE INTO edges(from_path, from_name, to_name, "
            "to_path, kind, line) VALUES (?, ?, ?, NULL, ?, ?)",
            [(sp, e.from_name, e.to_name, e.kind, e.line) for e in result.edges],
        )
        n_sym += len(result.symbols)
        n_edge += len(result.edges)
    con.commit()

    if verbose:
        print("Resolving edges…")
    con.execute("""
        UPDATE edges
        SET to_path = (
            SELECT path FROM symbols s
            WHERE s.name = edges.to_name
            GROUP BY s.name
            HAVING COUNT(DISTINCT s.path) = 1
            LIMIT 1
        )
        WHERE to_path IS NULL
    """)
    con.commit()

    n_keymd = 0
    for k in iter_keymd_files():
        ksp = config.canonical(str(k))
        stem = ksp[:-len(".key.md")]
        src_path = ""
        for ext in config.index_extensions():
            if os.path.exists(stem + ext):
                src_path = stem + ext
                break
        content = k.read_text(encoding="utf-8", errors="replace")
        sha = hashlib.sha256(content.encode()).hexdigest()
        con.execute(
            "INSERT OR REPLACE INTO keymds(path, src_path, sha256, "
            "auto_refreshed_at) VALUES (?, ?, ?, NULL)", (ksp, src_path, sha))
        con.execute("INSERT INTO keymd_fts(path, content) VALUES (?, ?)",
                    (ksp, content))
        n_keymd += 1
    con.commit()

    n_resolved = con.execute(
        "SELECT COUNT(*) FROM edges WHERE to_path IS NOT NULL").fetchone()[0]
    con.close()

    dt = time.time() - t0
    stats = {
        "files": len(files), "symbols": n_sym, "edges": n_edge,
        "resolved_edges": n_resolved, "keymds": n_keymd,
        "seconds": round(dt, 2), "db_path": str(db_path),
    }
    if verbose:
        print(f"Done in {dt:.1f}s — {stats}")
    return stats


if __name__ == "__main__":
    build(verbose=True)
