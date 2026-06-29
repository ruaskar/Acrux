from keymd.proxy.cache_inject import inject_cache


def test_injects_when_absent_anthropic():
    body = {"system": [{"type": "text", "text": "you are..."}],
            "tools": [{"name": "Read"}], "messages": []}
    inject_cache(body, "anthropic")
    assert body["system"][-1].get("cache_control") == {"type": "ephemeral"}
    assert body["tools"][-1].get("cache_control") == {"type": "ephemeral"}


def test_noop_when_already_cached():
    body = {"system": [{"type": "text", "text": "x",
                        "cache_control": {"type": "ephemeral"}}],
            "tools": [{"name": "Read"}], "messages": []}
    before = body["tools"][0].copy()
    inject_cache(body, "anthropic")
    assert body["tools"][0] == before          # untouched — framework already caches


def test_noop_for_openai():
    body = {"messages": [{"role": "system", "content": "x"}]}
    out = inject_cache(body, "openai")
    assert out == body                          # auto-caches → nothing to do


def test_handles_string_system():
    body = {"system": "plain string prompt", "tools": [{"name": "Read"}],
            "messages": []}
    inject_cache(body, "anthropic")             # must not raise
    assert body["tools"][-1].get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# Bug B — _already_cached must not crash on non-serializable values
# ---------------------------------------------------------------------------

def test_non_serializable_body_does_not_raise():
    """Bug B: body with a non-JSON-serializable value must not raise."""
    body = {
        "system": [{"type": "text", "text": "you are..."}],
        "tools": [{"name": "Read"}],
        "messages": [],
        "_handle": object(),   # non-serializable — crashes json.dumps
    }
    # Must not raise TypeError; must inject breakpoints (no cache_control present)
    result = inject_cache(body, "anthropic")
    assert result["system"][-1].get("cache_control") == {"type": "ephemeral"}
    assert result["tools"][-1].get("cache_control") == {"type": "ephemeral"}


def test_cache_control_in_messages_detected_no_injection():
    """Bug B: cache_control nested inside messages must be detected → no injection."""
    body = {
        "system": [{"type": "text", "text": "you are..."}],
        "tools": [{"name": "Read"}],
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "hi",
                 "cache_control": {"type": "ephemeral"}}
            ]}
        ],
    }
    before_sys = [dict(b) for b in body["system"]]
    inject_cache(body, "anthropic")
    # system block must be UNTOUCHED (framework already has cache_control)
    assert body["system"] == before_sys


# ---------------------------------------------------------------------------
# R2-C1 — fail-CLOSED: when _has_cache_control raises, assume cached → skip
# ---------------------------------------------------------------------------

class _RaisingDict(dict):
    """Dict subclass whose .values() raises RuntimeError — simulates a pathological
    body field that causes the scan to raise despite depth being in range."""
    def values(self):
        raise RuntimeError("pathological dict")
    def __iter__(self):
        raise RuntimeError("pathological dict")


def test_r2c1_raising_body_returns_already_cached():
    """R2-C1: when _has_cache_control raises (e.g. pathological dict subclass),
    _already_cached must return True (fail closed) rather than swallowing the
    error and returning False (which was the fail-open bug)."""
    from keymd.proxy.cache_inject import _already_cached
    # Place the raising object as the 'system' field so _already_cached hits it.
    body = {"system": _RaisingDict(type="text"), "tools": [{"name": "T"}],
            "messages": []}
    # Must not raise; must return True (fail-closed: assume already cached).
    assert _already_cached(body) is True


def test_r2c1_inject_cache_skips_on_scan_error():
    """R2-C1: inject_cache must NOT add cache_control when _already_cached → True."""
    body = {"system": _RaisingDict(type="text"), "tools": [{"name": "T"}],
            "messages": []}
    inject_cache(body, "anthropic")  # must not raise
    # Should NOT have injected (assumed already cached → skipped)
    assert "cache_control" not in body["tools"][0]


# ---------------------------------------------------------------------------
# R2-C2 — depth cap: deeply nested body must not RecursionError
# ---------------------------------------------------------------------------

def _make_deep_dict(depth: int) -> dict:
    """Build a chain of dicts: {"messages": [{"messages": [...]}]} depth levels."""
    obj: dict = {}
    for _ in range(depth):
        obj = {"level": obj}
    return {"messages": [obj], "system": [{"type": "text", "text": "x"}],
            "tools": [{"name": "T"}]}


def test_r2c2_deep_nested_no_recursionerror():
    """R2-C2: 5000-deep body must not raise RecursionError; _has_cache_control
    returns False; inject_cache proceeds normally and injects breakpoints."""
    from keymd.proxy.cache_inject import _has_cache_control
    body = _make_deep_dict(5000)
    # Must not raise; no cache_control anywhere → should return False
    result = _has_cache_control(body)
    assert result is False


def test_r2c2_inject_cache_proceeds_on_deep_body():
    """R2-C2: inject_cache must still inject breakpoints on a very deep body
    (no cache_control present, scan returns False cleanly via depth cap)."""
    body = _make_deep_dict(5000)
    inject_cache(body, "anthropic")  # must not raise
    # system and tools should have gotten breakpoints
    assert body["system"][-1].get("cache_control") == {"type": "ephemeral"}
    assert body["tools"][-1].get("cache_control") == {"type": "ephemeral"}
