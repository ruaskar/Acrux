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
