"""cache_inject.py — add prompt-cache breakpoints only where the framework didn't.

Anthropic-wire only: if the request already carries any cache_control, the
framework is caching and we leave it alone. OpenAI/Responses auto-cache the
prefix, so there is nothing to inject. Pure mutation of the inbound body.
"""
from __future__ import annotations

_EPHEMERAL = {"type": "ephemeral"}

# Maximum recursion depth for _has_cache_control.  Real Anthropic bodies are
# ~4–5 levels deep (system/tools/messages → content list → block dict →
# cache_control).  40 is a safe bound that stops pathological inputs without
# affecting any legitimate payload.
_MAX_SCAN_DEPTH = 40


def _has_cache_control(obj, _depth: int = 0) -> bool:
    """Structural scan for any dict containing 'cache_control'.

    Two-tier safety model:
      1. Depth cap (_depth > _MAX_SCAN_DEPTH): returns False cleanly.
         A 40-deep-clean body genuinely has no cache_control near the top
         where Anthropic places it, so treating it as "not cached" is safe and
         inject will add breakpoints normally.
      2. Any unexpected exception (e.g. a dict subclass whose .items()/.values()
         raises, or an __eq__ override): handled in _already_cached, which
         returns True (fail-closed) so inject_cache skips rather than risks
         double-injection past Anthropic's 4-breakpoint cap.

    NOTE (R2-C3): a bare key-presence scan can false-positive if user data or
    a tool schema legitimately contains a property named 'cache_control'.  The
    consequence is SAFE — we skip injection rather than add breakpoints — so we
    accept this rather than add fragile shape-matching.
    """
    if _depth > _MAX_SCAN_DEPTH:
        return False
    if isinstance(obj, dict):
        if "cache_control" in obj:
            return True
        for v in obj.values():
            if _has_cache_control(v, _depth + 1):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _has_cache_control(item, _depth + 1):
                return True
    return False


def _already_cached(body: dict) -> bool:
    # Scan only the fields that can carry cache_control; never serialize the body.
    # Fail-closed: if the scan raises for any reason (e.g. RecursionError from a
    # self-referential body, or a dict subclass that raises on .values()), we
    # assume the body *may* already be cached and return True so inject_cache
    # skips — safer than risking a double-injection past Anthropic's 4-cap → 400.
    for field in ("system", "tools", "messages"):
        try:
            if _has_cache_control(body.get(field)):
                return True
        except Exception:
            return True  # fail-closed: when unsure, skip injection
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
