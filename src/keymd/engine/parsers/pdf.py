"""pdf.py — PDF document parser via pypdf. Registers ONLY if pypdf is installed
(the `docs` extra), like the tree-sitter parsers and the `lang` extra.

Extracts each page's text into one plain-text blob (cached in doc_text by the
engine) and emits a section map: the PDF outline/bookmarks if present, else one
section per page. Sections + ranged reads operate over the EXTRACTED text, since a
binary PDF has no readable source lines.
"""
from __future__ import annotations

from pathlib import Path

from keymd.engine.parsers.base import ParseResult, build_sections, register


def _extract(reader) -> tuple[str, list[int]]:
    """(blob, page_start) — concatenated page text + the 1-based start line of each
    page within it."""
    parts: list[str] = []
    page_start: list[int] = []
    n = 0
    for page in reader.pages:
        page_start.append(n + 1)
        try:
            pl = (page.extract_text() or "").splitlines()
        except Exception:
            pl = []
        parts.extend(pl)
        n += len(pl)
    return "\n".join(parts), page_start


def _outline_heads(reader, page_start: list[int]) -> list[tuple[int, str, int]]:
    """(level, title, line) per bookmark; [] if there is no usable outline."""
    heads: list[tuple[int, str, int]] = []

    def walk(items, depth: int) -> None:
        for it in items:
            if isinstance(it, list):                 # a nested child group
                walk(it, depth + 1)
                continue
            try:
                pg = reader.get_destination_page_number(it)
            except Exception:
                continue
            if pg is None or pg < 0 or pg >= len(page_start):
                continue
            title = (getattr(it, "title", None) or "section").strip()
            heads.append((depth + 1, title, page_start[pg]))

    try:
        walk(reader.outline, 0)
    except Exception:
        return []
    heads.sort(key=lambda h: h[2])                    # document order, by line
    return heads


class PdfParser:
    extensions = (".pdf",)

    def parse(self, path: Path) -> ParseResult:
        from pypdf import PdfReader
        try:
            reader = PdfReader(str(path))
            blob, page_start = _extract(reader)
        except Exception:
            return ParseResult(symbols=[], edges=[], line_count=0, text="")
        total = (blob.count("\n") + 1) if blob else 0
        heads = _outline_heads(reader, page_start)
        if not heads:                                 # structureless PDF → per page
            heads = [(1, f"Page {p + 1}", page_start[p])
                     for p in range(len(page_start))]
        return ParseResult(symbols=build_sections(heads, total),
                           edges=[], line_count=total, text=blob)


try:
    import pypdf  # noqa: F401  (register only when the docs extra is installed)
    register(PdfParser())
except ImportError:
    pass
