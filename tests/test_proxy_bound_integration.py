"""Integration tests: bound_results wired into complete() behind the bound flag."""
import asyncio
from keymd.proxy.orchestrator import complete
from keymd.proxy.adapters.anthropic import AnthropicAdapter


def test_complete_bounds_grep_when_enabled(monkeypatch):
    import keymd.proxy.engine as eng
    monkeypatch.setattr(eng, "_index_ready", lambda: True)
    monkeypatch.setattr(eng, "centrality_map", lambda: {})

    big = "\n".join(f"src/a.py:{n}:hit{n}" for n in range(200))
    body = {"messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "grep", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big}]},
    ]}

    async def fake_upstream(b):
        # capture what the proxy WOULD send upstream, then end the turn
        captured["body"] = b
        return {"content": [{"type": "text", "text": "done"}], "stop_reason": "end_turn"}

    captured = {}
    asyncio.run(complete(body, AnthropicAdapter(), fake_upstream,
                         threshold=50, bound=True))
    sent = captured["body"]["messages"][1]["content"][0]["content"]
    assert "⟪keymd-bounded:grep⟫" in sent and len(sent) < len(big)


def test_complete_passthrough_when_disabled(monkeypatch):
    import keymd.proxy.engine as eng
    monkeypatch.setattr(eng, "_index_ready", lambda: True)
    big = "\n".join(f"src/a.py:{n}:hit{n}" for n in range(200))
    body = {"messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "grep", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big}]},
    ]}
    captured = {}

    async def fake_upstream(b):
        captured["body"] = b
        return {"content": [{"type": "text", "text": "x"}], "stop_reason": "end_turn"}

    import asyncio
    asyncio.run(complete(body, AnthropicAdapter(), fake_upstream,
                         threshold=50, bound=False))
    assert captured["body"]["messages"][1]["content"][0]["content"] == big
