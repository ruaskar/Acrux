"""base.py — language-neutral parse result + parser registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from keymd.engine import config


@dataclass
class Symbol:
    name: str            # qualified name, e.g. "Parser.parse"
    kind: str            # "function" | "method" | "class"
    line: int
    signature: str | None = None


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
