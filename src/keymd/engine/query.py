"""query.py — read-only structured queries over the keymd index."""
from __future__ import annotations

import ast
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.graph import callers_for_symbol, relpath
from keymd.engine.redact import redact_secrets


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
    """The defined symbol in the hit file whose name contains the search term, so the
    result is navigable (points at the matched code). Returns None when no DEFINED
    name matches — the term may have matched a signature/dep/caller line rather than a
    definition, and returning an unrelated first symbol would mislead the model into
    `keymd_read_symbol(<wrong name>)`."""
    leaf = term.strip().strip('"').split()[0] if term.strip() else ""
    if not leaf:
        return None
    cur.execute("SELECT name FROM symbols WHERE path=? AND name LIKE ? "
                "ORDER BY line LIMIT 1", (src_path, f"%{leaf}%"))
    row = cur.fetchone()
    return row[0] if row else None


def search(text: str, limit: int = 15) -> list[dict]:
    """Full-text search over rendered summaries, each hit enriched with call-graph
    context. Returns dicts:
      {path, snippet, symbol, called_by}
    `symbol` = the matched/first symbol in the file; `called_by` = number of other
    files that call into a symbol it defines (graph centrality). Results are sorted
    by called_by desc (stable, so FTS rank breaks ties), surfacing a hit in a
    widely-used module above one in a leaf.

    Centrality ranking is applied to a WIDER candidate pool than `limit` (then sliced),
    so a highly-central hit that ranks low in raw FTS relevance can still surface — a
    plain `LIMIT ?` would truncate it before the sort ever saw it.

    Tolerates arbitrary model/user text: input that isn't valid FTS5 (`a AND b`,
    `foo:bar`, an unterminated quote) is retried as one quoted literal phrase, then
    gives up to an empty list — never raises, so a CLI user or the proxy can't crash
    it with a stray colon."""
    pool = max(limit * 4, 50)            # rank over more candidates than we return
    with _conn() as con:
        cur = con.cursor()
        try:
            cur.execute("SELECT path, snippet(keymd_fts, 1, '<<', '>>', '...', 32) "
                        "FROM keymd_fts WHERE keymd_fts MATCH ? LIMIT ?", (text, pool))
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            try:
                cur.execute("SELECT path, snippet(keymd_fts, 1, '<<', '>>', '...', 32) "
                            "FROM keymd_fts WHERE keymd_fts MATCH ? LIMIT ?",
                            ('"' + text.replace('"', '""') + '"', pool))
                rows = cur.fetchall()
            except sqlite3.OperationalError:
                return []
        hits = []
        for p, snip in rows:
            hits.append({
                "path": relpath(p),
                "snippet": snip,
                "symbol": _top_symbol(cur, p, text),
                "called_by": _called_by_count(cur, p),
            })
    hits.sort(key=lambda h: h["called_by"], reverse=True)
    return hits[:limit]            # slice AFTER ranking, so the top-N is by centrality


def graph_data() -> dict:
    """Whole-repo file→file call graph for `keymd graph` — a pure read over the
    existing `files` + `edges` tables (no schema change, no re-index).

    Returns:
      {"nodes": [{"id": relpath, "loc": int, "called_by": int}, ...],
       "edges": [{"from": relpath, "to": relpath,
                  "calls": [{"from_name": str, "to_name": str, "line": int}, ...]}]}

    `called_by` = number of OTHER files that call into a symbol the node defines
    (the same centrality `search` uses). Edges group every resolved cross-file call
    by (from_path, to_path). Degrades to empty (no crash) when no index exists, so
    the server can still start and render an empty graph."""
    p = config.index_path()
    if not p.exists():
        return {"nodes": [], "edges": []}
    con = db.connect(p)
    try:
        cur = con.cursor()
        nodes = []
        cur.execute("SELECT path, line_count FROM files ORDER BY path")
        for abspath, loc in cur.fetchall():
            nodes.append({"id": relpath(abspath), "loc": loc,
                          "called_by": _called_by_count(cur, abspath)})
        grouped: dict[tuple[str, str], list[dict]] = {}
        cur.execute(
            "SELECT from_path, to_path, from_name, to_name, line FROM edges "
            "WHERE kind='call' AND to_path IS NOT NULL AND from_path != to_path "
            "ORDER BY from_path, to_path, line")
        for from_path, to_path, from_name, to_name, line in cur.fetchall():
            key = (relpath(from_path), relpath(to_path))
            grouped.setdefault(key, []).append(
                {"from_name": from_name, "to_name": to_name, "line": line})
        edges = [{"from": f, "to": t, "calls": calls}
                 for (f, t), calls in grouped.items()]
    finally:
        con.close()
    return {"nodes": nodes, "edges": edges}


def _func_doc(abspath: str, qualified: str) -> str | None:
    """First line of a function/method/class docstring, on-demand (not stored).
    Redacted as prose. None if absent/unreadable. `qualified` is dotted (Foo.bar)."""
    try:
        tree = ast.parse(open(abspath, encoding="utf-8", errors="replace").read())
    except (OSError, SyntaxError):
        return None
    node = tree
    for seg in qualified.split("."):
        nxt = None
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    and child.name == seg:
                nxt = child
                break
        if nxt is None:
            return None
        node = nxt
    doc = ast.get_docstring(node)
    if not doc:
        return None
    first = next((ln.strip() for ln in doc.splitlines() if ln.strip()), "")
    return redact_secrets(first)[:200] if first else None


def symbol_detail(path: str, name: str) -> dict:
    """Per-function detail for the graph panel: summary (docstring), signature (I/O),
    upstream callers, downstream callees. `name` may be a leaf (e.g. `parse`) — it is
    resolved to the qualified symbol (`Parser.parse`) against the symbols table.
    Pure read + an on-demand docstring read. Graceful on no-index / unknown symbol."""
    path = config.canonical(path)
    p = config.index_path()
    if not p.exists():
        return {"error": "no index"}
    con = db.connect(p)
    try:
        cur = con.cursor()
        # Prefer an EXACT name match (qualified or top-level). Only if there's no exact
        # match do we consider leaf matches (`%.name`) — and if a leaf is ambiguous
        # (>1 method/class shares it, e.g. two `__init__`), DON'T guess: return the
        # candidates so the caller disambiguates. Guessing by name-length silently
        # returned the wrong symbol's callees/doc.
        matches = cur.execute(
            "SELECT name, signature, line, end_line FROM symbols "
            "WHERE path=? AND kind IN ('function','method','class') "
            "AND (name=? OR name LIKE ?) ORDER BY line",
            (path, name, f"%.{name}")).fetchall()
        exact = [m for m in matches if m[0] == name]
        if exact:
            row = exact[0]
        elif len(matches) == 1:
            row = matches[0]
        elif len(matches) > 1:
            return {"error": "ambiguous symbol", "name": name,
                    "candidates": [{"name": m[0], "line": m[2]} for m in matches]}
        else:
            return {"error": "symbol not found"}
        qn, sig, line, end = row
        callees = []
        for to_name, to_path in cur.execute(
                "SELECT DISTINCT to_name, to_path FROM edges "
                "WHERE from_path=? AND from_name=? AND kind='call' ORDER BY to_name",
                (path, qn)).fetchall():
            callees.append({"name": to_name,
                            "file": relpath(to_path) if to_path else None})
    finally:
        con.close()
    c = callers(qn)                       # reuse the leaf-aware caller query (own _conn)
    seen, callers_out = set(), []
    for f, fn in c["exact"] + c["leaf"]:
        if (f, fn) not in seen:
            seen.add((f, fn))
            callers_out.append({"file": f, "fn": fn})
    return {"path": relpath(path), "name": qn, "signature": sig,
            "line": line, "end_line": end, "doc": _func_doc(path, qn),
            "callees": callees, "callers": callers_out}


def centrality_map() -> dict[str, int]:
    """relpath -> number of distinct files that call into it (graph centrality).

    Same signal `search` ranks by (see _called_by_count). One query over the
    `edges` table; returns {} if the index isn't built (never raises).
    """
    p = config.index_path()
    if not p.exists():               # index absent → empty map, do NOT use _conn() (it raises SystemExit)
        return {}
    con = db.connect(p)
    try:
        rows = con.execute(
            "SELECT to_path, COUNT(DISTINCT from_path) FROM edges "
            "WHERE kind='call' AND to_path IS NOT NULL GROUP BY to_path"
        ).fetchall()
    finally:
        con.close()
    return {relpath(to_path): n for to_path, n in rows}


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
