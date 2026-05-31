"""demo.py — `keymd demo`: a zero-config before/after of the read-payload savings.

Runs on keymd's own installed source (or a path you give it), builds a THROWAWAY
index in a temp dir, and prints how much smaller the line-anchored `.key.md`
summaries are than the full source — the payload an agent ingests to navigate a
repo. No wiring, no agent, no API key, no network.

Lines and chars are exact. Tokens are shown as a clearly-labelled `≈` estimate
(chars/4) so the demo needs no tokenizer download; the rigorous tiktoken number
lives in `benchmarks/offline_ab.py`, which the output points to.

Output uses a few non-ASCII glyphs (↓ ≈ →). stdout is reconfigured to UTF-8 by the
CLI entrypoint (`cli.main`), so `keymd demo` is console-safe; a caller importing
`run_demo` directly should ensure stdout is UTF-8 first.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import keymd
from keymd.engine import config, db, index
from keymd.engine.keymd_render import render_keymd

# Files below the gate are not worth summarizing; a corpus with nothing above it
# (or ~no reduction) gets the friendly "too small" path rather than a flat report.
_GATE = 75
_MIN_AGGREGATE_CUT = 0.05          # <5% whole-corpus reduction => "too small to show"


def _pct(full: int, summ: int) -> float:
    return (1 - summ / full) * 100 if full else 0.0


def _approx_tokens(chars: int) -> str:
    """A deliberately rough chars/4 estimate, rendered like `≈ 18k`. Never sold as
    measured — the exact tiktoken count is in benchmarks/offline_ab.py."""
    t = chars / 4
    if t >= 1000:
        return f"≈ {t / 1000:.0f}k tokens"
    return f"≈ {t:.0f} tokens"


def _measure(con) -> tuple[list[tuple], int, int, int, int]:
    """Per-file (rel, loc, full_lines, full_chars, sum_lines, sum_chars) + totals.

    Reads each indexed file's real source from disk and its rendered summary, so the
    numbers are exactly what keymd would serve. Unreadable files are skipped."""
    rows = con.execute("SELECT path, line_count FROM files ORDER BY path").fetchall()
    per_file = []
    tot_fl = tot_fc = tot_sl = tot_sc = 0
    for path, loc in rows:
        try:
            src = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        summary = render_keymd(con, path)
        fl, fc = src.count("\n") + 1, len(src)
        sl, sc = summary.count("\n") + 1, len(summary)
        per_file.append((path, loc, fl, fc, sl, sc))
        tot_fl += fl; tot_fc += fc; tot_sl += sl; tot_sc += sc
    return per_file, tot_fl, tot_fc, tot_sl, tot_sc


def run_demo(path: str | None = None) -> int:
    # 1. resolve corpus: explicit path, else keymd's own installed package.
    if path is not None:
        corpus = Path(path)
        if not corpus.exists():
            print(f"keymd demo: {path} not found")
            return 1
        if not corpus.is_dir():
            print(f"keymd demo: {path} is not a directory")
            return 1
        label = f"{corpus.name}"
        own = False
    else:
        corpus = Path(keymd.__file__).resolve().parent
        label = "keymd's own source"
        own = True

    # 2. throwaway index in a temp dir; restore env + remove temp in finally.
    prior = {k: os.environ.get(k) for k in ("KEYMD_PROJECT_ROOT", "KEYMD_INDEX_PATH")}
    tmp = tempfile.mkdtemp(prefix="keymd-demo-")
    try:
        os.environ["KEYMD_PROJECT_ROOT"] = str(corpus)
        os.environ["KEYMD_INDEX_PATH"] = str(Path(tmp) / "index.db")
        for fn in ("project_pkg_prefixes", "_git_toplevel"):
            c = getattr(config, fn, None)
            if hasattr(c, "cache_clear"):
                c.cache_clear()

        index.build(verbose=False)
        con = db.connect(config.index_path())
        try:
            per_file, fl, fc, sl, sc = _measure(con)
        finally:
            con.close()
    finally:
        for k, v in prior.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for fn in ("project_pkg_prefixes", "_git_toplevel"):
            c = getattr(config, fn, None)
            if hasattr(c, "cache_clear"):
                c.cache_clear()
        shutil.rmtree(tmp, ignore_errors=True)

    # 3. nothing to show on a tiny / empty / unsupported corpus.
    if not per_file or fc == 0 or _pct(fc, sc) / 100 < _MIN_AGGREGATE_CUT:
        where = "keymd's own source" if own else str(corpus)
        print(f"keymd demo — {where}")
        print("  This corpus is too small to show a meaningful cut "
              "(keymd summarizes files above ~%d lines)." % _GATE)
        print("  Try a larger repo:  keymd demo /path/to/your/repo")
        return 0

    # 4. spotlight = largest file by full chars.
    spot = max(per_file, key=lambda r: r[3])
    sp_rel = os.path.relpath(spot[0], corpus).replace(os.sep, "/")
    print(f"keymd demo — running on {label} ({len(per_file)} files)\n")
    print(f"  Spotlight: {sp_rel}")
    print(f"    full source   {spot[2]:>5,} lines   {spot[3]:>7,} chars")
    print(f"    keymd summary {spot[4]:>5,} lines   {spot[5]:>7,} chars"
          f"      ↓ {_pct(spot[3], spot[5]):.0f}% chars")
    print()
    print("  Whole corpus (agent reads every file to understand it):")
    print(f"    without keymd  {fl:>7,} lines   {fc:>9,} chars   ({_approx_tokens(fc)})")
    print(f"    with keymd     {sl:>7,} lines   {sc:>9,} chars   ({_approx_tokens(sc)})")
    print(f"    → {_pct(fl, sl):.0f}% fewer lines · {_pct(fc, sc):.0f}% fewer chars")
    print()
    print("  This is the read-payload lever — what your agent ingests to navigate.")
    print("  Exact token measurement:  python benchmarks/offline_ab.py")
    if own:
        print("  Now try yours:  keymd demo /path/to/your/repo")
    return 0
