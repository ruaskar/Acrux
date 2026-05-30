"""markdown.py — Markdown document parser: headings become sections.

A long doc gets a Table-of-Contents summary (section headings + their line spans)
so an agent reads the map first and pulls one section via keymd_read_range, instead
of the whole file. Stdlib-only; ships in core like the Python parser. Emits the same
language-neutral ParseResult — each heading is a Symbol(kind="section"), no edges —
so the rest of the engine (anchors, ranged reads, the gate) reuses Phase A as-is.
"""
from __future__ import annotations

import re
from pathlib import Path

from keymd.engine.parsers.base import ParseResult, build_sections, register

_ATX = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")   # ATX heading, optional closing #s
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")       # ≥3 of one kind, ≤3-space indent


def _headings(lines: list[str]) -> list[tuple[int, str, int]]:
    """(level, text, line) for ATX headings OUTSIDE fenced code blocks (so a `#`
    comment inside ```` ``` ```` is not mistaken for a heading). Per CommonMark a
    fence closes only with the SAME char (``` ≠ ~~~) and a run at least as long as
    the opener — so a 3-backtick line does NOT close a 4-backtick fence."""
    out: list[tuple[int, str, int]] = []
    fence: tuple[str, int] | None = None           # (char, length) of the opener
    for i, raw in enumerate(lines, start=1):
        fm = _FENCE.match(raw)
        if fm:
            run = fm.group(1)
            if fence is None:                      # open
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1]:   # valid close
                fence = None
            continue
        if fence is not None:
            continue
        m = _ATX.match(raw)
        if m:
            out.append((len(m.group(1)), m.group(2).strip(), i))
    return out


class MarkdownParser:
    extensions = (".md",)

    def parse(self, path: Path) -> ParseResult:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return ParseResult(symbols=build_sections(_headings(lines), len(lines)),
                           edges=[], line_count=len(lines))


register(MarkdownParser())
