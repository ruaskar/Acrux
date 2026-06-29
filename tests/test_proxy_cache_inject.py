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
