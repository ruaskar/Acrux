# cache_inject.py — prompt-cache breakpoint injection

**Status:** COMPLETE  
**Purpose:** Add `cache_control` breakpoints to Anthropic requests when the framework didn't  
**Scope:** Standalone logic module, no I/O or side effects  

**Core Logic:**
- `inject_cache(body: dict, wire: str) -> dict`: mutates body, returns it
- Anthropic-wire only; OpenAI/Responses auto-cache (no-op)
- Detects existing `cache_control` via JSON string scan; if found, leaves body alone
- Converts string `system` → list form with ephemeral marker
- Adds `cache_control={"type":"ephemeral"}` to LAST system block & LAST tools entry

**Tested:** 4 cases (inject-absent, noop-cached, noop-non-anthropic, string-system)

**Key Files:** cache_inject.py (34 loc) + test_proxy_cache_inject.py (25 loc)
