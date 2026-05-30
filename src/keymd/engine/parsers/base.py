"""base.py — language-neutral parse result + parser registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from keymd.engine import config


@dataclass
class Symbol:
    name: str            # qualified name, e.g. "Parser.parse"
    kind: str            # function|method|class|section|constant|enum_member|attribute
    line: int
    signature: str | None = None
    end_line: int | None = None   # last line of the symbol's body (for ranged reads)


@dataclass
class Edge:
    from_name: str       # caller symbol or "<module>"
    to_name: str         # callee name (possibly dotted) / import target
    kind: str            # "call" | "import" | "inherit"
    line: int


@dataclass
class ParseResult:
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    line_count: int = 0
    text: str | None = None   # extracted plain text for binary docs (PDF/DOCX); the
                              # engine caches it in doc_text so reads slice this, not
                              # the binary file. None for code/markdown (read directly).


def build_sections(heads: list[tuple[int, str, int]], total_lines: int) -> list[Symbol]:
    """Turn (level, label, line) headings into section Symbols with spans + unique
    names — shared by the markdown / pdf / docx doc parsers. A section runs until the
    next heading of level <= its own (so it includes sub-sections); names dedupe vs
    ALL emitted names so a literal 'Foo #2' heading can't collide with a generated one."""
    syms: list[Symbol] = []
    used: set[str] = set()
    for idx, (level, label, line) in enumerate(heads):
        end = total_lines
        for lvl2, _t, line2 in heads[idx + 1:]:
            if lvl2 <= level:
                end = max(line, line2 - 1)   # never invert when two heads share a line
                break
        base = label or f"section-{line}"
        name, k = base, 1
        while name in used:
            k += 1
            name = f"{base} #{k}"
        used.add(name)
        syms.append(Symbol(name, "section", line, f"{'#' * level} {label}", end))
    return syms


class Parser(Protocol):
    extensions: tuple[str, ...]

    def parse(self, path: Path) -> ParseResult: ...


_REGISTRY: dict[str, Parser] = {}


def register(parser: Parser) -> None:
    for ext in parser.extensions:
        _REGISTRY[ext] = parser
        config.REGISTERED_EXTENSIONS.add(ext)


def get_parser_for(path: Path) -> Parser | None:
    name = path.name
    # Handle compound extensions like .d.ts by longest-suffix match.
    for ext in sorted(_REGISTRY, key=len, reverse=True):
        if name.endswith(ext):
            return _REGISTRY[ext]
    return None
