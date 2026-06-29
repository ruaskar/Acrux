"""base.py — neutral proxy types + the WireAdapter protocol."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResultRef:
    id: str
    text: str
    set_text: Callable[[str], None]


class WireAdapter(Protocol):
    def inject(self, body: dict) -> dict: ...
    def tool_uses(self, resp: dict) -> list[ToolCall]: ...
    def messages(self, body: dict) -> list: ...
    def append_assistant(self, body: dict, resp: dict) -> dict: ...
    def append_tool_results(self, body: dict, results: list[tuple[str, str]]) -> dict: ...
    def terminal(self, text: str, template: dict | None = None) -> dict: ...
    def tool_call_names(self, body: dict) -> dict[str, str]: ...
    def iter_tool_results(self, body: dict) -> list["ToolResultRef"]: ...
