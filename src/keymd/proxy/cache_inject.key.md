# src\keymd\proxy\cache_inject.py  [81 loc]

Injects Anthropic prompt-cache breakpoints (ephemeral `cache_control`) into the
last element of `system` (list or str→list) and `tools` — **only** when wire is
`"anthropic"` and the body has no pre-existing `cache_control` anywhere.

api:
  inject_cache(body: dict, wire: str) -> dict   # mutates body in-place, returns it
deps: (none — stdlib only)
calls: _has_cache_control, _already_cached (internal)
called_by:
  src/keymd/proxy/middleware.py (inferred — upstream request path)

## Internal helpers
- `_has_cache_control(obj, _depth=0) -> bool` — depth-bounded structural scan
  (cap `_MAX_SCAN_DEPTH = 40`); returns False at cap, never raises.
- `_already_cached(body) -> bool` — scans `system/tools/messages`; FAIL-CLOSED:
  any scan exception → returns True (assume cached → skip injection, avoids
  Anthropic 4-breakpoint cap breach → API 400).

## Safety model (two-tier)
1. Depth cap (>40): returns False cleanly — real bodies ≤5 deep; 40+ = pathological.
2. Fail-closed except in _already_cached: raising dict subclass etc. → True → skip.

## Known limitation (R2-C3)
Key-presence scan false-positives if user data/tool schema has a field literally
named `cache_control`. Safe: injection is skipped (no API error, just no keymd cache).

refreshed: 2026-06-29 — adversarial round 2: depth cap + fail-closed + R2-C3 comment
