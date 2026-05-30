"""tools.py — virtual keymd_* tool definitions, the steering directive, and the
answerer that maps a virtual call to the Phase-1 engine façade."""
from __future__ import annotations

import json

from keymd.proxy.adapters.base import ToolCall

_PATH = {"type": "object", "properties": {"path": {"type": "string"}},
         "required": ["path"]}
_SYM = {"type": "object", "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"]}
_TXT = {"type": "object", "properties": {"text": {"type": "string"}},
        "required": ["text"]}
_PATH_SYM = {"type": "object",
             "properties": {"path": {"type": "string"}, "symbol": {"type": "string"}},
             "required": ["path", "symbol"]}
_RANGE = {"type": "object",
          "properties": {"path": {"type": "string"},
                         "start": {"type": "integer"}, "end": {"type": "integer"}},
          "required": ["path", "start", "end"]}
_EDIT = {"type": "object",
         "properties": {"path": {"type": "string"},
                        "old": {"type": "string"}, "new": {"type": "string"}},
         "required": ["path", "old", "new"]}

VIRTUAL_TOOL_DEFS = [
    {"name": "keymd_read", "schema": _PATH,
     "description": "Return the compact .key.md summary (API + L<start>-<end> line "
                    "anchors, deps, callers) for a file. Prefer this before reading "
                    "a large file in full."},
    {"name": "keymd_read_full", "schema": _PATH,
     "description": "Return the FULL source of a file. Use only when the summary "
                    "from keymd_read is insufficient."},
    {"name": "keymd_read_symbol", "schema": _PATH_SYM,
     "description": "Return the source of ONE symbol (function/class/method) by name, "
                    "using its line span. Cheaper than keymd_read_full for a region."},
    {"name": "keymd_read_range", "schema": _RANGE,
     "description": "Return just lines [start, end] of a file (1-based inclusive). "
                    "Use the L<start>-<end> anchors from keymd_read."},
    {"name": "keymd_edit", "schema": _EDIT,
     "description": "Replace an exact, unique `old` snippet with `new` in a file, "
                    "then re-index it. Read the region first (keymd_read_symbol) and "
                    "copy `old` exactly; `old` must occur exactly once."},
    {"name": "keymd_impact", "schema": _PATH,
     "description": "List files that depend on (call into) this file."},
    {"name": "keymd_callers", "schema": _SYM,
     "description": "List call sites of a symbol (exact + leaf-name matches)."},
    {"name": "keymd_callees", "schema": _PATH,
     "description": "List resolved outgoing calls from a file."},
    {"name": "keymd_search", "schema": _TXT,
     "description": "Full-text search across all .key.md summaries."},
]

SYSTEM_DIRECTIVE = (
    "\n\n[keymd] Before reading a LARGE file in full, call keymd_read(path) for "
    "its compact summary; use keymd_impact/keymd_callers/keymd_callees/keymd_search "
    "for structure instead of grepping. The summary anchors each symbol with its "
    "line span (# L<start>-<end>): pull just that region with keymd_read_symbol(path, "
    "symbol) or keymd_read_range(path, start, end), and change it with keymd_edit(path, "
    "old, new) (exact unique match, auto re-indexed) — avoid reading or rewriting the "
    "whole file. Call keymd_read_full(path) only when the summary is genuinely "
    "insufficient."
)


def answer(call: ToolCall) -> str:
    """Resolve a virtual keymd_* tool to text. Paths are canonicalized via the
    engine façade so they match the index keys."""
    from keymd.proxy import engine  # lazy: avoids import-order coupling at module load
    name, inp = call.name, call.input
    if name == "keymd_read":
        return engine.summary(engine.canon(inp["path"])) or "(file not indexed)"
    if name == "keymd_read_full":
        return engine.full(engine.canon(inp["path"]))
    if name == "keymd_read_symbol":
        return engine.read_symbol(engine.canon(inp["path"]), inp["symbol"])
    if name == "keymd_read_range":
        return engine.read_range(engine.canon(inp["path"]), inp["start"], inp["end"])
    if name == "keymd_edit":
        return engine.edit(engine.canon(inp["path"]), inp["old"], inp["new"])
    if name == "keymd_impact":
        return json.dumps(engine.impact(engine.canon(inp["path"])), indent=2)
    if name == "keymd_callers":
        return json.dumps(engine.callers(inp["symbol"]), indent=2)
    if name == "keymd_callees":
        return json.dumps(engine.callees(engine.canon(inp["path"])), indent=2)
    if name == "keymd_search":
        return json.dumps(engine.search(inp["text"]), indent=2)
    return f"(unknown keymd tool: {name})"
