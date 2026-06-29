"""bounders.py — pure bounding rules for live tool-results (A1 grep, A2 listings).

Each rule takes the raw tool-result text and returns a smaller, structured
equivalent, or None to leave it untouched (fail-open). Rules NEVER consult the
index for content — they restructure the real output only.
"""
from __future__ import annotations

import os
import re

# BUG C1 fix: allow optional leading Windows drive letter (e.g. C:\ or C:/)
_HIT = re.compile(r"^(?P<path>(?:[A-Za-z]:[\\/])?[^\n:]+):(?P<line>\d+):(?P<rest>.*)$")

# BUG C2 fix: context lines emitted by rg -C use dash separators; count them
# so they don't inflate the denominator and defeat the majority gate.
_CONTEXT = re.compile(r"^(?:[A-Za-z]:[\\/])?[^\n:]+-\d+-")


def bound_grep(text: str, *, per_file: int = 8, max_files: int = 40) -> str | None:
    lines = text.splitlines()
    parsed, files = 0, {}
    order = []
    context_count = 0
    for ln in lines:
        m = _HIT.match(ln)
        if m:
            parsed += 1
            p = m.group("path")
            if p not in files:
                files[p] = []
                order.append(p)
            files[p].append((m.group("line"), m.group("rest")))
        elif _CONTEXT.match(ln) or not ln.strip():
            # BUG C2 fix: context/blank lines are structural — don't penalise them
            context_count += 1
    # Gate: only non-structural (prose) lines count against us.
    # BUG R2-B2 fix: cap how many context lines are excused relative to real
    # matches so that prose-heavy output (1 hit + 100 faked context lines) still
    # returns None.  MAX_CONTEXT_PER_HIT=10 covers rg -C5 (5 before + 5 after).
    _MAX_CONTEXT_PER_HIT = 10
    effective_context = min(context_count, parsed * _MAX_CONTEXT_PER_HIT)
    non_structural = len(lines) - effective_context
    if parsed == 0 or parsed < max(1, non_structural) // 2:
        return None                       # not majority grep-shaped → leave alone

    total = sum(len(v) for v in files.values())
    out = [f"grep: {total} matches in {len(files)} files"]
    for p in order[:max_files]:
        hits = files[p]
        out.append(p)
        for line, rest in hits[:per_file]:
            out.append(f"  {line}: {rest.strip()}")
        if len(hits) > per_file:
            out.append(f"  (+{len(hits) - per_file} more matches in this file)")
    if len(order) > max_files:
        dropped_files = len(order) - max_files
        dropped_hits = sum(len(files[p]) for p in order[max_files:])
        out.append(f"(+{dropped_files} more files, {dropped_hits} matches — "
                   f"narrow the pattern or keymd_search)")
    return "\n".join(out)


# BUG I2 fix: allow spaces so filenames like "my file.py" are not filtered out.
# Guard: must also contain a path indicator (slash or dot) so bare prose words
# ("stack trace here") and ls-style permission strings don't qualify.
_PATHISH = re.compile(r"^[\w ./\\-]+$")
_PATH_INDICATOR = re.compile(r"[./\\]")

# BUG R2-B1 fix: reject ls -l permission lines and "total N" headers.
# A permission line starts with a file-type char followed by 9 rwx bits.
# "total N" headers start with "total " + digits.
_LS_LONG = re.compile(r"^([-dlbcps][-rwxsStT]{9}|total\s)")


def bound_listing(text: str, centrality: dict[str, int] | None = None, *,
                  max_entries: int = 60) -> str | None:
    centrality = centrality or {}
    raw = [ln.strip() for ln in text.splitlines() if ln.strip()]
    paths = [
        p for p in raw
        if not _LS_LONG.match(p) and _PATHISH.match(p) and _PATH_INDICATOR.search(p)
    ]
    if not paths or len(paths) < max(1, len(raw)) // 2:
        return None                       # not majority path-shaped → leave alone

    # rank by centrality desc (0 default), then lexical for stability
    ranked = sorted(paths, key=lambda p: (-centrality.get(p, 0), p))
    shown = ranked[:max_entries]
    by_dir: dict[str, list[str]] = {}
    for p in shown:
        # BUG M1 fix: normalise dir key to forward slashes for consistent display
        raw_dir = os.path.dirname(p) or "."
        d_key = raw_dir.replace("\\", "/")
        by_dir.setdefault(d_key, []).append(p)

    out = [f"listing: {len(paths)} paths, {len(by_dir)} dirs (most-central first)"]
    for d, members in by_dir.items():
        out.append(f"{d}/  ({len(members)})")
        for p in members:
            c = centrality.get(p, 0)
            out.append(f"  {os.path.basename(p)}" + (f"  ·{c} callers" if c else ""))
    if len(paths) > max_entries:
        out.append(f"(+{len(paths) - max_entries} more paths)")
    return "\n".join(out)
