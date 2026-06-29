import asyncio
from keymd.proxy.orchestrator import complete
from keymd.proxy.adapters.anthropic import AnthropicAdapter


def test_complete_injects_cache_after_bounding(monkeypatch):
    import keymd.proxy.engine as eng
    monkeypatch.setattr(eng, "_index_ready", lambda: True)
    monkeypatch.setattr(eng, "centrality_map", lambda: {})
    body = {"system": [{"type": "text", "text": "sys"}],
            "tools": [{"name": "Read"}], "messages": []}
    captured = {}

    async def fake_upstream(b):
        captured["body"] = b
        return {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}

    asyncio.run(complete(body, AnthropicAdapter(), fake_upstream,
                         threshold=50, cache=True, wire="anthropic"))
    assert captured["body"]["system"][-1]["cache_control"] == {"type": "ephemeral"}


def test_no_cache_when_disabled(monkeypatch):
    import keymd.proxy.engine as eng
    monkeypatch.setattr(eng, "_index_ready", lambda: True)
    body = {"system": [{"type": "text", "text": "sys"}], "tools": [{"name": "Read"}],
            "messages": []}
    captured = {}

    async def fake_upstream(b):
        captured["body"] = b
        return {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}

    asyncio.run(complete(body, AnthropicAdapter(), fake_upstream,
                         threshold=50, cache=False, wire="anthropic"))
    assert "cache_control" not in str(captured["body"])
