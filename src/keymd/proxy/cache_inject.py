"""cache_inject.py — add prompt-cache breakpoints only where the framework didn't.

Anthropic-wire only: if the request already carries any cache_control, the
framework is caching and we leave it alone. OpenAI/Responses auto-cache the
prefix, so there is nothing to inject. Pure mutation of the inbound body.
"""
from __future__ import annotations

_EPHEMERAL = {"type": "ephemeral"}


def _has_cache_control(obj) -> bool:
    """Structural scan for any dict containing 'cache_control'. Never raises."""
    if isinstance(obj, dict):
        if "cache_control" in obj:
            return True
        for v in obj.values():
            if _has_cache_control(v):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _has_cache_control(item):
                return True
    return False


def _already_cached(body: dict) -> bool:
    # Scan only the fields that can carry cache_control; never serialize the body.
    for field in ("system", "tools", "messages"):
        try:
            if _has_cache_control(body.get(field)):
                return True
        except Exception:
            pass
    return False


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
