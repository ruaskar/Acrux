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

VIRTUAL_TOOL_DEFS = [
    {"name": "keymd_read", "schema": _PATH,
     "description": "Return the compact .key.md summary (API, deps, callers) for a "
                    "file. Prefer this before reading a large file in full."},
    {"name": "keymd_read_full", "schema": _PATH,
     "description": "Return the FULL source of a file. Use only when the summary "
                    "from keymd_read is insufficient."},
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
    "for structure instead of grepping. Call keymd_read_full(path) only when the "
    "summary is genuinely insufficient."
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
    if name == "keymd_impact":
        return json.dumps(engine.impact(engine.canon(inp["path"])), indent=2)
    if name == "keymd_callers":
        return json.dumps(engine.callers(inp["symbol"]), indent=2)
    if name == "keymd_callees":
        return json.dumps(engine.callees(engine.canon(inp["path"])), indent=2)
    if name == "keymd_search":
        return json.dumps(engine.search(inp["text"]), indent=2)
    return f"(unknown keymd tool: {name})"
