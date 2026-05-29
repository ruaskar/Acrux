"""query.py — read-only structured queries over the keymd index."""
from __future__ import annotations

import os
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.graph import callers_for_symbol, relpath


def _con():
    p = config.index_path()
    if not p.exists():
        raise SystemExit(f"error: index not built at {p}. Run `keymd build`.")
    return db.connect(p)


def callers(symbol: str) -> dict:
    con = _con(); cur = con.cursor()
    cur.execute("SELECT DISTINCT from_path, from_name FROM edges "
                "WHERE kind='call' AND to_name=? ORDER BY from_path", (symbol,))
    exact = [(relpath(p), n) for p, n in cur.fetchall()]
    # Leaf-name fallback (matches the source query.py): a qualified symbol like
    # `Parser.parse` is invoked as `p.parse`, recorded under the leaf `parse`,
    # so exact-only matching would miss it. Keeps `keymd_callers` (Phase 3)
    # consistent with `keymd_impact`, which leaf-matches via the heuristic.
    leaf_name = symbol.rsplit(".", 1)[-1] if "." in symbol else None
    leaf: list[tuple[str, str]] = []
    if leaf_name and leaf_name != symbol:
        cur.execute("SELECT DISTINCT from_path, from_name FROM edges "
                    "WHERE kind='call' AND to_name=? ORDER BY from_path",
                    (leaf_name,))
        seen = set(exact)
        leaf = [(relpath(p), n) for p, n in cur.fetchall()
                if (relpath(p), n) not in seen]
    con.close()
    return {"symbol": symbol, "exact": exact, "leaf": leaf}


def callees(path: str) -> list[tuple[str, str]]:
    path = os.path.abspath(path)
    con = _con(); cur = con.cursor()
    cur.execute("SELECT DISTINCT to_name, to_path FROM edges "
                "WHERE from_path=? AND kind='call' AND to_path IS NOT NULL "
                "ORDER BY to_name", (path,))
    out = [(to_name, relpath(to_path)) for to_name, to_path in cur.fetchall()]
    con.close()
    return out


def symbols(path: str) -> list[tuple[str, str, int]]:
    path = os.path.abspath(path)
    con = _con(); cur = con.cursor()
    cur.execute("SELECT name, kind, line FROM symbols WHERE path=? ORDER BY line",
                (path,))
    out = [(n, k, ln) for n, k, ln in cur.fetchall()]
    con.close()
    return out


def impact(path: str) -> dict:
    path = os.path.abspath(path)
    con = _con(); cur = con.cursor()
    cur.execute("SELECT name FROM symbols WHERE path=? ORDER BY line", (path,))
    own = sorted({r[0] for r in cur.fetchall()})
    stem = Path(path).stem
    per_symbol: dict[str, list[str]] = {}
    total: set[str] = set()
    for sym in own:
        c = {relpath(x) for x in callers_for_symbol(cur, sym, path, stem)}
        if c:
            per_symbol[sym] = sorted(c)
            total |= c
    con.close()
    return {"path": relpath(path), "per_symbol": per_symbol,
            "unique_files": len(total)}


def search(text: str, limit: int = 15) -> list[tuple[str, str]]:
    con = _con(); cur = con.cursor()
    cur.execute("SELECT path, snippet(keymd_fts, 1, '«', '»', '...', 32) "
                "FROM keymd_fts WHERE keymd_fts MATCH ? LIMIT ?", (text, limit))
    out = [(relpath(p), s) for p, s in cur.fetchall()]
    con.close()
    return out


def missing_keymds(top: int = 30) -> list[tuple[int, str]]:
    con = _con(); cur = con.cursor()
    cur.execute("SELECT path, line_count FROM files WHERE line_count>50 "
                "ORDER BY line_count DESC")
    out = []
    for path, lc in cur.fetchall():
        sibling = path[:-len(Path(path).suffix)] + ".key.md"
        if not os.path.exists(sibling):
            out.append((lc, relpath(path)))
            if len(out) >= top:
                break
    con.close()
    return out


def stats() -> dict:
    con = _con(); cur = con.cursor()
    d = {}
    for q, label in [
        ("SELECT COUNT(*) FROM files", "files"),
        ("SELECT COUNT(*) FROM symbols", "symbols"),
        ("SELECT COUNT(*) FROM edges", "edges"),
        ("SELECT COUNT(*) FROM edges WHERE to_path IS NOT NULL", "resolved_edges"),
        ("SELECT COUNT(*) FROM keymds", "keymds"),
    ]:
        d[label] = cur.execute(q).fetchone()[0]
    con.close()
    return d
