import json

from keymd.proxy.adapters.responses import ResponsesAdapter


def test_inject_flat_tools_and_instructions():
    a = ResponsesAdapter()
    body = a.inject({"model": "m", "input": "hello"})
    # string input normalized to a message item list
    assert isinstance(body["input"], list)
    assert body["input"][0]["role"] == "user" and body["input"][0]["content"] == "hello"
    # flat tool defs (no nested "function" key)
    names = {t["name"] for t in body["tools"]}
    assert "keymd_read" in names
    assert all("function" not in t for t in body["tools"])
    assert all(set(t) >= {"type", "name", "parameters"} for t in body["tools"])
    assert body["tools"][0]["type"] == "function"
    # directive on top-level instructions, idempotent
    assert "[keymd]" in body["instructions"]
    body2 = a.inject(body)
    assert body2["instructions"].count("[keymd]") == 1
    assert sum(1 for t in body2["tools"] if t["name"] == "keymd_read") == 1


def test_inject_appends_to_existing_instructions():
    a = ResponsesAdapter()
    body = a.inject({"input": [], "instructions": "Be terse."})
    assert body["instructions"].startswith("Be terse.")
    assert "[keymd]" in body["instructions"]


def test_tool_uses_extracts_function_calls():
    a = ResponsesAdapter()
    resp = {"output": [
        {"type": "function_call", "id": "fc1", "call_id": "call1", "name": "Read",
         "arguments": json.dumps({"file_path": "/x.py"})},
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "hi"}]}]}
    calls = a.tool_uses(resp)
    assert len(calls) == 1
    assert calls[0].id == "call1" and calls[0].name == "Read"
    assert calls[0].input == {"file_path": "/x.py"}


def test_append_roundtrip_uses_call_id():
    a = ResponsesAdapter()
    body = {"input": [{"role": "user", "content": "go"}]}
    resp = {"output": [{"type": "function_call", "id": "fc1", "call_id": "call1",
                        "name": "Read", "arguments": "{}"}]}
    a.append_assistant(body, resp)
    a.append_tool_results(body, [("call1", "RESULT")])
    types = [it.get("type") for it in body["input"]]
    assert "function_call" in types and "function_call_output" in types
    fco = next(it for it in body["input"] if it.get("type") == "function_call_output")
    assert fco["call_id"] == "call1" and fco["output"] == "RESULT"


def test_append_assistant_preserves_reasoning_before_function_call():
    # Reasoning models (gpt-5-codex) emit a `reasoning` item right before the
    # function_call; the API 400s if the function_call is replayed without it.
    a = ResponsesAdapter()
    body = {"input": [{"role": "user", "content": "go"}]}
    resp = {"output": [
        {"type": "reasoning", "id": "rs1", "summary": []},
        {"type": "function_call", "id": "fc1", "call_id": "call1",
         "name": "Read", "arguments": "{}"}]}
    a.append_assistant(body, resp)
    appended = body["input"][1:]
    assert [it["type"] for it in appended] == ["reasoning", "function_call"]
    assert appended[0]["id"] == "rs1"      # reasoning kept, adjacency preserved


def test_terminal_shape():
    a = ResponsesAdapter()
    t = a.terminal("done", {"id": "r1", "model": "gpt"})
    assert t["status"] == "completed"
    assert t["output"][0]["content"][0]["text"] == "done"
    assert t["id"] == "r1" and t["model"] == "gpt"
