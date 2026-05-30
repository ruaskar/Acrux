"""gate.py — decide how each tool call is handled: virtual / gated / host.

Pure policy over a ToolCall + the set of paths already summarized in the
transcript (the stateless loop-guard). The forwarding rule (all-or-forward)
lives in the orchestrator.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from keymd.engine.keymd_render import strip_timestamp
from keymd.proxy import engine
from keymd.proxy.adapters.base import ToolCall

# Tool names treated as a file read, matched CASE-INSENSITIVELY: Claude Code emits
# "Read", OpenClaw emits "read" — both must gate. Stored lowercase; compared via
# call.name.lower() in classify().
READ_TOOLS = {"read", "read_file", "view", "cat"}
_PATH_KEYS = ("file_path", "path", "target_file", "filename")
MARKER_RE = re.compile(r"⟪keymd-summary:(.+?)⟫")


@dataclass
class Decision:
    kind: Literal["virtual", "gated", "host"]
    call: ToolCall
    path: str | None = None   # canonical absolute path, set when kind == "gated"


def _extract_path(inp: dict) -> str | None:
    for k in _PATH_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def classify(call: ToolCall, *, summarized: set[str], threshold: int) -> Decision:
    if call.name.startswith("keymd_"):
        return Decision("virtual", call)
    if call.name.lower() in READ_TOOLS:
        raw = _extract_path(call.input)
        if raw:
            ap = engine.canon(raw)
            if ap not in summarized and engine.is_indexed_large(ap, threshold):
                return Decision("gated", call, ap)
    return Decision("host", call)


def summarized_paths(messages: list) -> set[str]:
    """Canonical paths for which a keymd summary already appears in the transcript.

    Handles BOTH wire formats: Anthropic tool_result blocks (content is a list)
    AND OpenAI tool messages ({"role":"tool","content":"<str>"}). Missing the
    OpenAI str case re-gated the same file every inner turn on OpenAI hosts.
    """
    found: set[str] = set()
    for m in messages:
        out = m.get("output")
        if isinstance(out, str):                           # Responses function_call_output
            found.update(MARKER_RE.findall(out))
        content = m.get("content")
        if isinstance(content, str):                       # OpenAI tool message
            found.update(MARKER_RE.findall(content))
        elif isinstance(content, list):                    # Anthropic blocks
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, str):
                        found.update(MARKER_RE.findall(c))
                    elif isinstance(c, list):
                        for x in c:
                            if isinstance(x, dict):
                                found.update(MARKER_RE.findall(x.get("text", "")))
    return found


def summary_result(abspath: str) -> str:
    # strip_timestamp makes the injected text deterministic (the live
    # `refreshed:` line would otherwise vary per call — a prompt-cache hazard).
    body = strip_timestamp(engine.summary(abspath) or "(file not indexed)")
    return (f"⟪keymd-summary:{abspath}⟫\n{body}\n\n"
            "(Generated summary. Call keymd_read_full(path) for the full source, "
            "or keymd_impact/keymd_callers for structure.)")
