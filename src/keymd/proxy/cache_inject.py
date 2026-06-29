"""cache_inject.py — add prompt-cache breakpoints only where the framework didn't.

Anthropic-wire only: if the request already carries any cache_control, the
framework is caching and we leave it alone. OpenAI/Responses auto-cache the
prefix, so there is nothing to inject. Pure mutation of the inbound body.
"""
from __future__ import annotations

import json

_EPHEMERAL = {"type": "ephemeral"}


def _already_cached(body: dict) -> bool:
    return "cache_control" in json.dumps(body)


def inject_cache(body: dict, wire: str) -> dict:
    if wire != "anthropic":
        return body                             # auto-caching providers: no-op
    if _already_cached(body):
        return body                             # framework already placed breakpoints

    sys = body.get("system")
    if isinstance(sys, list) and sys and isinstance(sys[-1], dict):
        sys[-1]["cache_control"] = dict(_EPHEMERAL)
    elif isinstance(sys, str) and sys:
        body["system"] = [{"type": "text", "text": sys, "cache_control": dict(_EPHEMERAL)}]

    tools = body.get("tools")
    if isinstance(tools, list) and tools and isinstance(tools[-1], dict):
        tools[-1]["cache_control"] = dict(_EPHEMERAL)
    return body
