"""transforms.py — body->body variants for the replay engine. Each calls the
SHIPPED proxy transforms so the benchmark measures the real product, not a copy."""
from __future__ import annotations

import copy

from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy import result_bound, cache_inject
from keymd.proxy.orchestrator import _bound_rules

_ADAPTER = AnthropicAdapter()


def t_raw(body: dict) -> dict:
    return copy.deepcopy(body)


def t_bound(body: dict) -> dict:
    b = copy.deepcopy(body)
    result_bound.bound_results(b, _ADAPTER, _bound_rules(), fresh_results=0)
    return b


def t_cache(body: dict) -> dict:
    b = copy.deepcopy(body)
    cache_inject.inject_cache(b, "anthropic")
    return b


def t_bound_cache(body: dict) -> dict:
    b = copy.deepcopy(body)
    result_bound.bound_results(b, _ADAPTER, _bound_rules(), fresh_results=0)
    cache_inject.inject_cache(b, "anthropic")
    return b


import json as _json  # noqa: E402
from keymd.proxy import gate as _gate, engine as _eng  # noqa: E402

_READ_TOOLS = {"read", "cat", "view", "read_file"}
_PATH_KEYS = ("file_path", "path", "filename")


def _read_paths_by_id(body: dict) -> dict:
    """tool_use id -> file path, for read-family tool calls only."""
    out = {}
    for m in body.get("messages", []) or []:
        if m.get("role") != "assistant":
            continue
        for b in m.get("content", []) or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" \
                    and b.get("name", "").lower() in _READ_TOOLS:
                inp = b.get("input", {}) or {}
                p = next((inp[k] for k in _PATH_KEYS if k in inp), None)
                if p:
                    out[b.get("id", "")] = p
    return out


def t_gate(body: dict, threshold: int = 50):
    b = copy.deepcopy(body)
    read_paths = _read_paths_by_id(b)
    gated = 0
    for m in b.get("messages", []) or []:
        if m.get("role") != "user":
            continue
        for blk in (m.get("content") or []):
            if not (isinstance(blk, dict) and blk.get("type") == "tool_result"):
                continue
            path = read_paths.get(blk.get("tool_use_id"))
            if not path:
                continue
            try:
                ap = _eng.canon(path)
                if _eng.is_indexed_large(ap, threshold):
                    blk["content"] = _gate.summary_result(ap)
                    gated += 1
            except Exception:
                continue          # unindexed/outside-root → offline gate no-op
    return b, gated
