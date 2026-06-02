"""keymd_render.py — deterministic LLM-optimized .key.md text from the index.

The entire file is machine-generated; there is no human-authored region.
Format is terse and token-dense (key: value lines), optimized for an LLM to
consume before reading the full source.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from keymd.engine import config
from keymd.engine.graph import callers_for_symbol, is_project_import, relpath

MAX_DEPS = 10
MAX_CALLS = 15
MAX_CALLERS_PER_SYM = 5
TS_PREFIX = "refreshed:"
_DOC_LANGS = {"markdown", "pdf", "docx"}   # render as a Table-of-Contents, not api/deps


def strip_timestamp(text: str) -> str:
    return "\n".join(l for l in text.splitlines()
                     if not l.startswith(TS_PREFIX))


def _anchor(line: int | None, end: int | None) -> str:
    """ASCII line-range anchor (e.g. '  # L36-45') so an agent can pull/edit just
    that span via keymd_read_symbol/keymd_read_range without reading the whole file."""
    if not line:
        return ""
    return f"  # L{line}" if (not end or end == line) else f"  # L{line}-{end}"


def _render_doc(con, src_path: str, lang: str, loc: int, sha: str) -> str:
    """Table-of-Contents summary for a document: section headings indented by level
    with their L<start>-<end> anchors, so an agent pulls one section via
    keymd_read_range instead of the whole file."""
    rows = con.execute(
        "SELECT signature, name, line, end_line FROM symbols WHERE path=? "
        "ORDER BY line", (src_path,)).fetchall()
    out = [f"# {relpath(src_path)}  [{lang} · {loc} lines · sha:{sha[:8]}]",
           "sections (L-spans include nested sub-sections):"]
    if not rows:
        out.append("  (no headings)")
    for sig, name, line, end in rows:
        sig = sig or name
        level = len(sig) - len(sig.lstrip("#")) or 1     # leading '#' count
        label = sig.lstrip("#").strip()
        out.append(f"{'  ' * level}{label}{_anchor(line, end)}")
    out.append(f"{TS_PREFIX} {time.strftime('%Y-%m-%dT%H:%M', time.localtime())}")
    return "\n".join(out) + "\n"


def render_keymd(con: sqlite3.Connection, src_path: str) -> str:
    cur = con.cursor()
    frow = cur.execute(
        "SELECT lang, line_count, sha256 FROM files WHERE path=?",
        (src_path,)).fetchone()
    lang, loc, sha = frow if frow else ("?", 0, "")

    if lang in _DOC_LANGS:          # documents get a Table-of-Contents, not api/deps
        return _render_doc(con, src_path, lang, loc, sha)

    # API: top-level symbols with signatures, ordered by line. The module_doc
    # pseudo-symbol is the summary lead (emitted below the header), not an api entry.
    cur.execute(
        "SELECT name, kind, signature, line, end_line FROM symbols "
        "WHERE path=? AND name NOT LIKE '%.%' AND kind != 'module_doc' ORDER BY line",
        (src_path,))
    api_lines = []
    for name, kind, sig, line, end in cur.fetchall():
        api_lines.append(f"  {sig or name}{_anchor(line, end)}")
        # include direct methods of a class for context
        cur2 = con.cursor()
        cur2.execute(
            "SELECT signature, name, line, end_line FROM symbols WHERE path=? "
            "AND name LIKE ? AND name NOT LIKE ? ORDER BY line",
            (src_path, f"{name}.%", f"{name}.%.%"))
        for msig, mname, mline, mend in cur2.fetchall():
            api_lines.append(f"    {msig or mname}{_anchor(mline, mend)}")

    # deps
    cur.execute("SELECT DISTINCT to_name FROM edges "
                "WHERE from_path=? AND kind='import' ORDER BY to_name",
                (src_path,))
    imports = [r[0] for r in cur.fetchall()]
    proj = [i for i in imports if is_project_import(i)]
    deps_show = (proj or imports)[:MAX_DEPS]

    # calls (resolved, to other files)
    cur.execute(
        "SELECT DISTINCT to_name FROM edges WHERE from_path=? AND kind='call' "
        "AND to_path IS NOT NULL AND to_path!=? ORDER BY to_name",
        (src_path, src_path))
    calls = [r[0] for r in cur.fetchall()]
    calls_more = max(0, len(calls) - MAX_CALLS)
    calls_show = calls[:MAX_CALLS]

    # callers — only callables have callers; constants/fields would otherwise be
    # falsely attributed via the leaf-name match in callers_for_symbol.
    cur.execute("SELECT name FROM symbols WHERE path=? "
                "AND kind IN ('function', 'method', 'class')", (src_path,))
    own = sorted({r[0] for r in cur.fetchall()})
    stem = Path(src_path).stem
    caller_lines = []
    for sym in own:
        seen = sorted(callers_for_symbol(cur, sym, src_path, stem))
        if not seen:
            continue
        short = [relpath(f) for f in seen[:MAX_CALLERS_PER_SYM]]
        extra = (f" (+{len(seen) - MAX_CALLERS_PER_SYM} more)"
                 if len(seen) > MAX_CALLERS_PER_SYM else "")
        caller_lines.append(f"  {sym} ← {', '.join(short)}{extra}")

    out: list[str] = []
    out.append(f"# {relpath(src_path)}  [{lang} · {loc} loc · sha:{sha[:8]}]")
    # Prefer an opt-in LLM summary cached at the CURRENT sha (`keymd summarize`);
    # fall back to the deterministic module docstring. `sha` is already in scope
    # (from the files query above), so this is a sha-incremental lookup. The
    # llm_summaries table may be absent on an index built before summarize ran —
    # tolerate that and fall back.
    llm = None
    try:
        lrow = cur.execute(
            "SELECT summary FROM llm_summaries WHERE path=? AND sha256=?",
            (src_path, sha)).fetchone()
        llm = lrow[0] if lrow else None
    except sqlite3.OperationalError:           # table not created yet → no LLM summaries
        llm = None
    if llm:
        out.append(f"summary: {llm}")
    else:
        drow = cur.execute(
            "SELECT signature FROM symbols WHERE path=? AND kind='module_doc' LIMIT 1",
            (src_path,)).fetchone()
        if drow and drow[0]:
            out.append(f"summary: {drow[0]}")
    out.append("api:")
    out.extend(api_lines or ["  (none)"])
    out.append("deps: " + (", ".join(deps_show) if deps_show else "(none)"))
    if calls_more:
        out.append(f"calls: {', '.join(calls_show)} (+{calls_more} more)")
    else:
        out.append("calls: " + (", ".join(calls_show) if calls_show else "(none)"))
    out.append("called_by:")
    out.extend(caller_lines or ["  (none)"])
    out.append(f"{TS_PREFIX} {time.strftime('%Y-%m-%dT%H:%M', time.localtime())}")
    return "\n".join(out) + "\n"
