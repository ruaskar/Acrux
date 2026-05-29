from keymd.proxy.adapters.anthropic import AnthropicAdapter

A = AnthropicAdapter()


def test_inject_adds_tools_and_directive():
    body = {"model": "m", "messages": [], "system": "base", "tools": [{"name": "Read"}]}
    out = A.inject(dict(body))
    names = {t["name"] for t in out["tools"]}
    assert {"Read", "keymd_read", "keymd_impact"} <= names
    assert "keymd_read" in out["system"]
    vk = next(t for t in out["tools"] if t["name"] == "keymd_read")
    assert vk["input_schema"]["type"] == "object"


def test_inject_handles_block_system_and_no_tools():
    body = {"messages": [], "system": [{"type": "text", "text": "base"}]}
    out = A.inject(dict(body))
    assert any("keymd_read" in b.get("text", "") for b in out["system"])
    assert any(t["name"] == "keymd_read" for t in out["tools"])


def test_inject_is_idempotent():
    # re-injecting an already-injected body must not duplicate tools or directive
    body = {"messages": [], "system": "base", "tools": []}
    once = A.inject(dict(body))
    twice = A.inject(dict(once))
    assert once["system"] == twice["system"]
    assert len([t for t in twice["tools"] if t["name"] == "keymd_read"]) == 1


def test_tool_uses_and_appends():
    resp = {"role": "assistant", "stop_reason": "tool_use", "content": [
        {"type": "text", "text": "ok"},
        {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "a.py"}}]}
    calls = A.tool_uses(resp)
    assert len(calls) == 1 and calls[0].id == "tu1" and calls[0].name == "Read"
    body = {"messages": []}
    body = A.append_assistant(body, resp)
    body = A.append_tool_results(body, [("tu1", "SUMMARY")])
    assert body["messages"][0]["role"] == "assistant"
    tr = body["messages"][1]
    assert tr["role"] == "user" and tr["content"][0]["type"] == "tool_result"
    assert tr["content"][0]["tool_use_id"] == "tu1"
    assert tr["content"][0]["content"] == "SUMMARY"


def test_no_tool_uses_on_final():
    assert A.tool_uses({"content": [{"type": "text", "text": "done"}]}) == []


def test_terminal_preserves_template_fields():
    t = A.terminal("bye", template={"id": "msg_1", "usage": {"input_tokens": 3}})
    assert t["stop_reason"] == "end_turn"
    assert t["content"][0]["text"] == "bye"
    assert t["id"] == "msg_1" and t["usage"]["input_tokens"] == 3
    assert all(b["type"] != "tool_use" for b in t["content"])
