from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy.adapters.openai import OpenAIAdapter
from keymd.proxy.adapters.responses import ResponsesAdapter


def _anthropic_body():
    return {"messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "grep", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "BIG"}]},
    ]}


def test_anthropic_names_and_mutation():
    a = AnthropicAdapter()
    body = _anthropic_body()
    assert a.tool_call_names(body) == {"t1": "grep"}
    refs = a.iter_tool_results(body)
    assert [(r.id, r.text) for r in refs] == [("t1", "BIG")]
    refs[0].set_text("small")
    assert body["messages"][1]["content"][0]["content"] == "small"


def test_openai_names_and_mutation():
    o = OpenAIAdapter()
    body = {"messages": [
        {"role": "assistant", "tool_calls": [
            {"id": "c1", "function": {"name": "rg", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "BIG"}]}
    assert o.tool_call_names(body) == {"c1": "rg"}
    refs = o.iter_tool_results(body)
    refs[0].set_text("small")
    assert body["messages"][1]["content"] == "small"


def test_responses_names_and_mutation():
    r = ResponsesAdapter()
    body = {"input": [
        {"type": "function_call", "call_id": "f1", "name": "ls"},
        {"type": "function_call_output", "call_id": "f1", "output": "BIG"}]}
    assert r.tool_call_names(body) == {"f1": "ls"}
    refs = r.iter_tool_results(body)
    refs[0].set_text("small")
    assert body["input"][1]["output"] == "small"
