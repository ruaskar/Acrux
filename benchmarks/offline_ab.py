"""offline_ab.py — deterministic, NO-API token-savings A/B for the keymd gate.

For each indexed file: full-source tokens (Arm A, no keymd) vs the .key.md summary
tokens (Arm B, keymd), counted with a REAL tokenizer (tiktoken). Five views:

  1. per-file (top by token weight)
  2. by language  (Python vs JS/TS)
  3. by subsystem (task-bundle: "work on the proxy / engine / ...")
  4. whole-repo aggregate + fallback sweep (f = files still read in full)
  5. gate-threshold sweep (files > thr gated, the rest read full in BOTH arms)

No LLM is called, no API spend. Honest boundaries: this is the mechanical
read-payload lever ONLY — not whether cheap summaries make a model read MORE
files, not task success, not write-heavy work. Savings scale with file size.

Usage:  python benchmarks/offline_ab.py [--threshold N] [--top N]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import tiktoken

from keymd.engine import config, db, index
from keymd.engine.keymd_render import render_keymd
import keymd.engine.parsers.python  # noqa: F401  (register .py parser)
try:
    import keymd.engine.parsers.treesitter  # noqa: F401  (JS/TS if installed)
except Exception:
    pass

SWEEP = (0, 50, 75, 150, 400)    # gate thresholds to sweep (50 = keymd default)
HEADLINE_THR = 75                # threshold the headline is computed at


def _encoder():
    for name in ("o200k_base", "cl100k_base"):
        try:
            enc = tiktoken.get_encoding(name)
            return name, (lambda t, e=enc: len(e.encode(t)))
        except Exception:
            continue
    return "len/4 estimate", (lambda t: max(1, len(t) // 4))


def _bucket(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    if parts[0] == "src" and len(parts) >= 3 and parts[1] == "keymd":
        return parts[2] if len(parts) > 3 else "keymd-core"  # proxy/engine/... or top-level
    return parts[0]                                          # tests/benchmarks/scripts/...


def _pct(a: float, b: float) -> float:
    return 100 * (a - b) / a if a else 0.0


def _row(label, files, ft, st, width=22):
    return (f"  {label:<{width}} {files:>4}  {ft:>9,}  {st:>8,}  {_pct(ft, st):>5.1f}%")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="offline_ab")
    ap.add_argument("--threshold", type=int, default=HEADLINE_THR,
                    help=f"display per-file table for loc > this (default {HEADLINE_THR})")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args(argv)

    for _s in (sys.stdout, sys.stderr):           # UTF-8 so glyphs don't mojibake
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    index.build(verbose=False)
    enc_name, count = _encoder()
    root = config.project_root()
    con = db.connect(config.index_path())
    rows = con.execute(
        "SELECT path, line_count, lang FROM files ORDER BY line_count DESC").fetchall()

    # per-file records over the WHOLE corpus (every indexed file)
    recs = []  # (rel, lang, loc, full_tok, sum_tok, sum_lines)
    for path, lc, lang in rows:
        try:
            full = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        summary = render_keymd(con, path) or ""
        recs.append((os.path.relpath(path, root), (lang or "?"), lc or 0,
                     count(full), count(summary), len(summary.splitlines())))
    con.close()
    if not recs:
        print("no indexed files")
        return 1

    full_tok = sum(r[3] for r in recs)
    sum_tok = sum(r[4] for r in recs)
    full_lines = sum(r[2] for r in recs)
    sum_lines = sum(r[5] for r in recs)
    n = len(recs)

    print(f"keymd offline A/B  —  {n} indexed files  —  tokenizer: {enc_name}")
    print(f"(Arm A = read full source · Arm B = read .key.md summary · no API spend)\n")

    # 1 — per-file
    shown = [r for r in recs if r[2] > a.threshold]
    print(f"PER-FILE  (loc > {a.threshold}, top {a.top} by tokens)")
    print(f"  {'file':<46} {'loc':>4} {'full':>8} {'sum':>7} {'cut%':>6}")
    for rel, _lang, loc, ft, st, _sl in sorted(shown, key=lambda r: -r[3])[:a.top]:
        print(f"  {rel[-46:]:<46} {loc:>4} {ft:>8,} {st:>7,} {_pct(ft, st):>5.1f}%")

    # 2 — by language
    print(f"\nBY LANGUAGE                files       full       sum    cut%")
    langs = sorted({r[1] for r in recs})
    for lg in langs:
        g = [r for r in recs if r[1] == lg]
        print(_row(lg, len(g), sum(r[3] for r in g), sum(r[4] for r in g)))

    # 3 — by subsystem (task bundle)
    print(f"\nBY SUBSYSTEM (task bundle) files       full       sum    cut%")
    buckets = {}
    for r in recs:
        buckets.setdefault(_bucket(r[0]), []).append(r)
    for bk in sorted(buckets, key=lambda k: -sum(r[3] for r in buckets[k])):
        g = buckets[bk]
        print(_row(bk, len(g), sum(r[3] for r in g), sum(r[4] for r in g)))

    # 4 — whole-repo aggregate + fallback sweep
    print(f"\nWHOLE-REPO AGGREGATE (agent reads every file to understand the repo)")
    print(f"  Arm A full reads      : {full_tok:>10,} tokens  {full_lines:>7,} lines")
    print(f"  Arm B keymd summaries : {sum_tok:>10,} tokens  {sum_lines:>7,} lines")
    print(f"  Fallback sweep (f = fraction of files still read in full):")
    for f in (0.0, 0.25, 0.5):
        b = sum_tok + f * full_tok
        print(f"    f={f:>4.0%} : {b:>11,.0f} tokens   ({_pct(full_tok, b):>5.1f}% cut)")

    # 5 — gate-threshold sweep (files > thr gated; rest read full in both arms)
    print(f"\nGATE-THRESHOLD SWEEP (production gate: only files > thr are summarized)")
    for thr in SWEEP:
        gated = [r for r in recs if r[2] > thr]
        b = sum(r[4] for r in gated) + sum(r[3] for r in recs if r[2] <= thr)
        print(f"    thr={thr:>3} loc : {len(gated):>2} files gated   "
              f"{b:>10,.0f} tokens   ({_pct(full_tok, b):>5.1f}% cut)")

    # headline
    gated_h = [r for r in recs if r[2] > HEADLINE_THR]
    b_h = sum(r[4] for r in gated_h) + sum(r[3] for r in recs if r[2] <= HEADLINE_THR)
    print(f"\nHEADLINE  @ threshold {HEADLINE_THR} loc, f=0% fallback:  "
          f"{_pct(full_tok, b_h):.1f}% fewer tokens, "
          f"{_pct(full_lines, sum_lines):.1f}% fewer lines read.")
    print(f"At the default 50-loc gate, {sum(1 for r in recs if r[2] > 50)} files "
          f"qualify here — savings scale with file size, so a compact repo understates it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
