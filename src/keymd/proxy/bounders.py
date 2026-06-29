"""bounders.py — pure bounding rules for live tool-results (A1 grep, A2 listings).

Each rule takes the raw tool-result text and returns a smaller, structured
equivalent, or None to leave it untouched (fail-open). Rules NEVER consult the
index for content — they restructure the real output only.
"""
from __future__ import annotations

import re

_HIT = re.compile(r"^(?P<path>[^\n:]+):(?P<line>\d+):(?P<rest>.*)$")


def bound_grep(text: str, *, per_file: int = 8, max_files: int = 40) -> str | None:
    lines = text.splitlines()
    parsed, files = 0, {}
    order = []
    for ln in lines:
        m = _HIT.match(ln)
        if not m:
            continue
        parsed += 1
        p = m.group("path")
        if p not in files:
            files[p] = []
            order.append(p)
        files[p].append((m.group("line"), m.group("rest")))
    if parsed == 0 or parsed < max(1, len(lines)) // 2:
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


import os

_PATHISH = re.compile(r"^[\w./\\-]+$")


def bound_listing(text: str, centrality: dict[str, int] | None = None, *,
                  max_entries: int = 60) -> str | None:
    centrality = centrality or {}
    raw = [ln.strip() for ln in text.splitlines() if ln.strip()]
    paths = [p for p in raw if _PATHISH.match(p)]
    if not paths or len(paths) < max(1, len(raw)) // 2:
        return None                       # not majority path-shaped → leave alone

    # rank by centrality desc (0 default), then lexical for stability
    ranked = sorted(paths, key=lambda p: (-centrality.get(p, 0), p))
    shown = ranked[:max_entries]
    by_dir: dict[str, list[str]] = {}
    for p in shown:
        by_dir.setdefault(os.path.dirname(p) or ".", []).append(p)

    out = [f"listing: {len(paths)} paths, {len(by_dir)} dirs (most-central first)"]
    for d, members in by_dir.items():
        out.append(f"{d}/  ({len(members)})")
        for p in members:
            c = centrality.get(p, 0)
            out.append(f"  {os.path.basename(p)}" + (f"  ·{c} callers" if c else ""))
    if len(paths) > max_entries:
        out.append(f"(+{len(paths) - max_entries} more paths)")
    return "\n".join(out)
