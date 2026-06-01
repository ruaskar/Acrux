"""query.py — read-only structured queries over the keymd index."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.graph import callers_for_symbol, relpath


@contextmanager
def _conn():
    p = config.index_path()
    if not p.exists():
        raise SystemExit(f"error: index not built at {p}. Run `keymd build`.")
    con = db.connect(p)
    try:
        yield con
    finally:
        con.close()  # close on every path incl. exceptions (FTS-syntax errors)


def callers(symbol: str) -> dict:
    with _conn() as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT from_path, from_name FROM edges "
                    "WHERE kind='call' AND to_name=? ORDER BY from_path", (symbol,))
        exact = [(relpath(p), n) for p, n in cur.fetchall()]
        # Leaf-name fallback (matches the source query.py): a qualified symbol
        # like `Parser.parse` is invoked as `p.parse`, recorded under the leaf
        # `parse`, so exact-only matching would miss it. Keeps `keymd_callers`
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
    return {"symbol": symbol, "exact": exact, "leaf": leaf}


def callees(path: str) -> list[tuple[str, str]]:
    path = config.canonical(path)
    with _conn() as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT to_name, to_path FROM edges "
                    "WHERE from_path=? AND kind='call' AND to_path IS NOT NULL "
                    "ORDER BY to_name", (path,))
        return [(to_name, relpath(to_path)) for to_name, to_path in cur.fetchall()]


def symbols(path: str) -> list[tuple[str, str, int]]:
    path = config.canonical(path)
    with _conn() as con:
        cur = con.cursor()
        cur.execute("SELECT name, kind, line FROM symbols WHERE path=? ORDER BY line",
                    (path,))
        return [(n, k, ln) for n, k, ln in cur.fetchall()]


def impact(path: str) -> dict:
    path = config.canonical(path)
    with _conn() as con:
        cur = con.cursor()
        cur.execute("SELECT name FROM symbols WHERE path=? "        # callables only:
                    "AND kind IN ('function', 'method', 'class') "  # consts have no
                    "ORDER BY line", (path,))                        # callers
        own = sorted({r[0] for r in cur.fetchall()})
        stem = Path(path).stem
        per_symbol: dict[str, list[str]] = {}
        total: set[str] = set()
        for sym in own:
            c = {relpath(x) for x in callers_for_symbol(cur, sym, path, stem)}
            if c:
                per_symbol[sym] = sorted(c)
                total |= c
    return {"path": relpath(path), "per_symbol": per_symbol,
            "unique_files": len(total)}


def _called_by_count(cur, src_path: str) -> int:
    """How many DISTINCT other files call into a symbol defined in src_path — a
    cheap call-graph centrality score (a hit in a widely-depended-on file matters
    more than one in a leaf script)."""
    cur.execute(
        "SELECT COUNT(DISTINCT e.from_path) FROM edges e "
        "WHERE e.kind='call' AND e.from_path != ? AND e.to_name IN "
        "(SELECT name FROM symbols WHERE path=?)", (src_path, src_path))
    row = cur.fetchone()
    return row[0] if row else 0


def _top_symbol(cur, src_path: str, term: str) -> str | None:
    """The most relevant symbol in the hit file: a defined name containing the
    search term if any, else the file's first symbol — so a result is navigable
    (points at code), not just a file + snippet."""
    leaf = term.strip().strip('"').split()[0] if term.strip() else ""
    if leaf:
        cur.execute("SELECT name FROM symbols WHERE path=? AND name LIKE ? "
                    "ORDER BY line LIMIT 1", (src_path, f"%{leaf}%"))
        row = cur.fetchone()
        if row:
            return row[0]
    cur.execute("SELECT name FROM symbols WHERE path=? ORDER BY line LIMIT 1",
                (src_path,))
    row = cur.fetchone()
    return row[0] if row else None


def search(text: str, limit: int = 15) -> list[dict]:
    """Full-text search over rendered summaries, each hit enriched with call-graph
    context. Returns dicts:
      {path, snippet, symbol, called_by}
    `symbol` = the matched/first symbol in the file; `called_by` = number of other
    files that call into a symbol it defines (graph centrality). Results are sorted
    by called_by desc (stable, so FTS rank breaks ties), surfacing a hit in a
    widely-used module above one in a leaf."""
    with _conn() as con:
        cur = con.cursor()
        cur.execute("SELECT path, snippet(keymd_fts, 1, '<<', '>>', '...', 32) "
                    "FROM keymd_fts WHERE keymd_fts MATCH ? LIMIT ?", (text, limit))
        rows = cur.fetchall()
        hits = []
        for p, snip in rows:
            hits.append({
                "path": relpath(p),
                "snippet": snip,
                "symbol": _top_symbol(cur, p, text),
                "called_by": _called_by_count(cur, p),
            })
    hits.sort(key=lambda h: h["called_by"], reverse=True)
    return hits


def missing_keymds(top: int = 30) -> list[tuple[int, str]]:
    with _conn() as con:
        cur = con.cursor()
        cur.execute("SELECT path, line_count FROM files WHERE line_count>50 "
                    "ORDER BY line_count DESC")
        out = []
        for path, lc in cur.fetchall():
            sibling = path[:-len(Path(path).suffix)] + ".key.md"
            if not os.path.exists(sibling):
                out.append((lc, relpath(path)))
                if len(out) >= top:
                    break
    return out


def stats() -> dict:
    with _conn() as con:
        cur = con.cursor()
        d = {}
        for q, label in [
            ("SELECT COUNT(*) FROM files", "files"),
            ("SELECT COUNT(*) FROM symbols", "symbols"),
            ("SELECT COUNT(*) FROM edges", "edges"),
            ("SELECT COUNT(*) FROM edges WHERE to_path IS NOT NULL", "resolved_edges"),
            ("SELECT COUNT(*) FROM keymds", "keymds"),
        ]:
            d[label] = cur.execute(q).fetchone()[0]
    return d
