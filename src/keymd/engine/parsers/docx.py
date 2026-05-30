"""docx.py — DOCX document parser via python-docx. Registers ONLY if python-docx
is installed (the `docs` extra), like the tree-sitter parsers.

Extracts paragraphs into one plain-text blob (one line per paragraph, cached in
doc_text) and emits a section per Heading-styled paragraph. Sections + ranged reads
operate over the EXTRACTED text.
"""
from __future__ import annotations

from pathlib import Path

from keymd.engine.parsers.base import ParseResult, build_sections, register


class DocxParser:
    extensions = (".docx",)

    def parse(self, path: Path) -> ParseResult:
        from docx import Document
        try:
            doc = Document(str(path))
        except Exception:
            return ParseResult(symbols=[], edges=[], line_count=0, text="")
        lines: list[str] = []
        heads: list[tuple[int, str, int]] = []
        for para in doc.paragraphs:
            lineno = len(lines) + 1                   # 1-based line of this paragraph
            lines.append(para.text)
            style = (para.style.name if para.style else "") or ""
            if style.startswith("Heading "):
                try:
                    level = int(style.split()[1])
                except (ValueError, IndexError):
                    level = 1
                heads.append((level, para.text.strip() or f"section-{lineno}", lineno))
        blob = "\n".join(lines)
        return ParseResult(symbols=build_sections(heads, len(lines)),
                           edges=[], line_count=len(lines), text=blob)


try:
    import docx  # noqa: F401  (register only when the docs extra is installed)
    register(DocxParser())
except ImportError:
    pass
