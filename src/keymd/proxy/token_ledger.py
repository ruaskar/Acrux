"""token_ledger.py — flagged per-request token ledger for Phase-2 live A/B capture.

IMPORTANT — tokens_in_est is a CHEAP ESTIMATE only:
  The proxy inlines a simple len(text)//4 heuristic over the outbound body's
  system/tools/messages text.  It does NOT import benchmarks (benchmarks depends
  on keymd, not the other way round — importing it here would create a dependency
  cycle).  The AUTHORITATIVE token count for offline measurement is the replay
  engine at benchmarks/replay_engine.py.  The ledger exists for Phase-2 live
  capture where a rough per-request number is sufficient.

Default OFF: when path is None, record() returns immediately without touching
the filesystem.  Zero overhead unless a ledger path is configured.

Output format: one JSONL line per upstream call:
  {"turn_id": "<uuid4>", "tokens_in_est": <int>, "tokens_out": <int>}
"""
from __future__ import annotations

import json
import os
import uuid


# ---------------------------------------------------------------------------
# Cheap token estimator — inlined to keep the proxy dependency-light.
# ---------------------------------------------------------------------------

def _estimate_tokens(body: dict) -> int:
    """Return a cheap token estimate for the outbound body.

    Walks system / tools / messages and sums len(text) // 4.
    Handles str and list[block] content; skips non-text blocks silently.
    """
    total_chars = 0

    # system
    sys = body.get("system", "")
    if isinstance(sys, str):
        total_chars += len(sys)
    elif isinstance(sys, list):
        for block in sys:
            if isinstance(block, dict):
                total_chars += len(block.get("text", ""))
            elif isinstance(block, str):
                total_chars += len(block)

    # tools (JSON-serialise each schema to count its chars)
    for tool in body.get("tools", []):
        if isinstance(tool, dict):
            try:
                total_chars += len(json.dumps(tool))
            except (TypeError, ValueError):
                pass

    # messages
    for msg in body.get("messages", []):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(block.get("text", ""))
                elif isinstance(block, str):
                    total_chars += len(block)

    return max(total_chars // 4, 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _extract_tokens_out(resp: dict) -> int:
    """Extract output-token count from an upstream response.

    Supports both wire shapes:
      - Anthropic: resp["usage"]["output_tokens"]
      - OpenAI:    resp["usage"]["completion_tokens"]
    Returns 0 when absent.
    """
    usage = resp.get("usage") or {}
    if not isinstance(usage, dict):
        return 0
    # Anthropic wire
    if "output_tokens" in usage:
        return int(usage["output_tokens"])
    # OpenAI wire
    if "completion_tokens" in usage:
        return int(usage["completion_tokens"])
    return 0


def record(path: "str | None", *, body_in: dict, resp: dict, adapter) -> None:
    """Append one JSONL line to the ledger file at *path*.

    When path is None this is a strict no-op — the function returns immediately
    without allocating any data structures.  This is the default state (Phase 1
    offline benchmark does not use the ledger).

    Args:
        path:     Absolute or relative path to the JSONL ledger file, or None.
        body_in:  The outbound (post-transform) request body sent to the upstream.
        resp:     The upstream response dict (already parsed JSON).
        adapter:  The WireAdapter instance (reserved for future per-adapter logic).
    """
    if path is None:
        return

    line = {
        "turn_id": str(uuid.uuid4()),
        "tokens_in_est": _estimate_tokens(body_in),
        "tokens_out": _extract_tokens_out(resp),
    }
    # Open in append mode; create the file if it doesn't exist.
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError:
        pass  # telemetry must never crash a real request
