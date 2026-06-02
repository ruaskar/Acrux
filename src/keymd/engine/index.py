"""index.py — build the symbol/edge graph for the active project into SQLite."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path

from keymd.engine import config, db
from keymd.engine.keymd_render import render_keymd
from keymd.engine.parsers.base import get_parser_for


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_repo_files():
    """Every file the project contains — index roots (rglob) + flat-repo top-level
    (iterdir) — deduped by canonical path, BEFORE any extension filter. The single
    definition of "what's in this repo", shared by iter_source_files (which keeps
    the parseable ones) and build()'s unsupported-language skip notice (which counts
    the dropped ones), so the two can never disagree about the traversal surface."""
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
        for p in root.rglob("*"):
            if p.is_file() and _emit(p):
                yield p
    # top-level files directly under the project root (flat repos: app.py at root)
    try:
        for p in config.project_root().iterdir():
            if p.is_file() and _emit(p):
                yield p
    except OSError:
        pass


def iter_source_files():
    exts = config.index_extensions()
    for p in iter_repo_files():
        # .key.md are keymd's OWN sidecars (handled by iter_keymd_files); the .md
        # parser would otherwise match them by suffix and index them as documents.
        if (not p.name.endswith(".key.md")
                and any(p.name.endswith(e) for e in exts)
                and not config.is_excluded(str(p))):
            yield p


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
    ".java": "java", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".md": "markdown", ".pdf": "pdf", ".docx": "docx",
}

# Common source extensions keymd has NO parser for yet — used ONLY to print a
# one-line "skipped N files" notice on `build` so a mixed-repo user is never
# *silently* missing files (the failure mode that hid Java/C/C++ before).
_UNSUPPORTED_HINT = {".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
                     ".cs", ".lua", ".dart", ".ex", ".exs", ".clj", ".m"}


def _lang_for(path: Path) -> str:
    # Human-readable language label, stored in files.lang and shown in the
    # .key.md header (e.g. "python", not "py"). Matches spec §2 sample header.
    return _LANG_BY_EXT.get(path.suffix) or path.suffix.lstrip(".") or "?"


def build(verbose: bool = True) -> dict:
    db_path = config.index_path()
    # Preserve the opt-in LLM summary cache across a full rebuild: a build unlinks
    # the whole db, which would otherwise force an expensive re-summarize every time
    # (and `build` runs on graph/serve/summarize-when-absent). Snapshot here; restore
    # below ONLY rows whose path+sha still match the rebuilt index — that also drops
    # orphan rows for deleted files and stale-sha rows for changed ones, in one pass.
    preserved_summaries: list[tuple] = []
    if db_path.exists():
        _old = db.connect(db_path)
        try:
            preserved_summaries = _old.execute(
                "SELECT path, sha256, summary, model, created_at FROM llm_summaries"
            ).fetchall()
        except sqlite3.OperationalError:        # table absent (pre-summarize index)
            preserved_summaries = []
        finally:
            _old.close()                        # MUST close before unlink — an open
                                                # handle blocks unlink on Windows (WinError 32)
        db_path.unlink()
    con = db.connect(db_path, create=True)

    files = list(iter_source_files())
    if verbose:
        print(f"Indexing {len(files)} source files…")
        skipped: dict[str, int] = {}
        for q in iter_repo_files():
            if q.suffix in _UNSUPPORTED_HINT and not config.is_excluded(str(q)):
                skipped[q.suffix] = skipped.get(q.suffix, 0) + 1
        if skipped:
            top = ", ".join(f"{ext} ({n})" for ext, n in
                            sorted(skipped.items(), key=lambda kv: -kv[1]))
            total = sum(skipped.values())
            print(f"skipped {total} files in unsupported languages: {top} "
                  "— keymd indexes py, js, ts, java, c, cpp")

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
        if result.text is not None:               # cached extracted text for binary docs
            con.execute("INSERT OR REPLACE INTO doc_text(path, text) VALUES (?, ?)",
                        (sp, result.text))
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

    # Restore preserved LLM summaries whose file is STILL present at the SAME sha.
    # A sha mismatch (file changed) or a missing path (file deleted) is dropped — so
    # the cache survives a rebuild for unchanged files but never serves a stale summary.
    # Done before the FTS render so a restored summary also feeds `keymd search`.
    if preserved_summaries:
        fresh = {p: s for (p, s) in con.execute("SELECT path, sha256 FROM files").fetchall()}
        keep = [row for row in preserved_summaries
                if fresh.get(row[0]) == row[1]]
        if keep:
            con.executemany(
                "INSERT OR REPLACE INTO llm_summaries(path, sha256, summary, model, "
                "created_at) VALUES (?, ?, ?, ?, ?)", keep)
            con.commit()

    # FTS over the RENDERED summary of every indexed file (keyed by SOURCE path).
    # This makes `keymd search` work on a plain build — it indexes the summary text
    # (signatures, deps, callers) that is ALWAYS present, not just committed .key.md
    # sidecars (which a fresh build rarely has). Rendered after edge resolution so the
    # summary's called_by section is complete. The summary already hides string
    # values (<str>), so nothing a sidecar wouldn't show reaches the index.
    for (sp,) in con.execute("SELECT path FROM files").fetchall():
        try:
            content = render_keymd(con, sp)
        except Exception:           # one unrenderable file must not abort the build
            continue                # (it's simply absent from search, still indexed)
        con.execute("INSERT INTO keymd_fts(path, content) VALUES (?, ?)", (sp, content))
    con.commit()

    # Track committed .key.md sidecars in the `keymds` table (freshness/auto-refresh
    # bookkeeping). FTS is fed from rendered summaries above, so no FTS insert here.
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
