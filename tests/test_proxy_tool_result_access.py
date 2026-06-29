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


# ---------------------------------------------------------------------------
# Bug A — list-form tool_result content: image block must survive set_text
# ---------------------------------------------------------------------------

def _body_with_list_content(content):
    """Build a body with a tool_result whose content is a list."""
    return {"messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "grep", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": content}]},
    ]}


def test_list_content_image_block_survives_set_text():
    """Bug A: after set_text, image block must still be present in the list."""
    a = AnthropicAdapter()
    content = [
        {"type": "text", "text": "old text"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
    ]
    body = _body_with_list_content(content)
    refs = a.iter_tool_results(body)
    assert refs[0].text == "old text"
    refs[0].set_text("new text")

    result_content = body["messages"][1]["content"][0]["content"]
    # Must still be a list (not a bare string)
    assert isinstance(result_content, list), "content must remain a list"
    types = [b.get("type") for b in result_content if isinstance(b, dict)]
    assert "image" in types, "image block must survive set_text"
    text_blocks = [b for b in result_content if isinstance(b, dict) and b.get("type") == "text"]
    assert len(text_blocks) == 1, "exactly one text block"
    assert text_blocks[0]["text"] == "new text"


def test_list_content_cache_control_survives_set_text():
    """Bug A2: cache_control on the first text block must survive set_text."""
    a = AnthropicAdapter()
    content = [
        {"type": "text", "text": "original", "cache_control": {"type": "ephemeral"}},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "xyz"}},
    ]
    body = _body_with_list_content(content)
    refs = a.iter_tool_results(body)
    refs[0].set_text("updated")

    result_content = body["messages"][1]["content"][0]["content"]
    assert isinstance(result_content, list)
    text_blocks = [b for b in result_content if isinstance(b, dict) and b.get("type") == "text"]
    assert len(text_blocks) == 1
    assert text_blocks[0]["text"] == "updated"
    assert text_blocks[0].get("cache_control") == {"type": "ephemeral"}, \
        "cache_control must be preserved on the rewritten text block"


def test_string_content_unchanged_behavior():
    """Regression: string content must still produce a bare string after set_text."""
    a = AnthropicAdapter()
    body = _anthropic_body()  # content is the string "BIG"
    refs = a.iter_tool_results(body)
    refs[0].set_text("small")
    result_content = body["messages"][1]["content"][0]["content"]
    assert result_content == "small", "string content must remain a bare string"


# ---------------------------------------------------------------------------
# Bug 4 — duplicate tool_use_id with different names → un-routable ("")
# ---------------------------------------------------------------------------

def test_anthropic_dup_id_different_names_unroutable():
    """Bug 4: two tool_use blocks sharing an id but different names → value ""."""
    a = AnthropicAdapter()
    body = {"messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "dup", "name": "grep", "input": {}},
            {"type": "tool_use", "id": "dup", "name": "apply_patch", "input": {}},
        ]},
    ]}
    names = a.tool_call_names(body)
    assert names.get("dup") == "", \
        "duplicate id with different names must be un-routable (empty string)"


def test_openai_dup_id_different_names_unroutable():
    """Bug 4: same scenario for OpenAI adapter."""
    o = OpenAIAdapter()
    body = {"messages": [
        {"role": "assistant", "tool_calls": [
            {"id": "dup", "function": {"name": "grep", "arguments": "{}"}},
            {"id": "dup", "function": {"name": "apply_patch", "arguments": "{}"}},
        ]},
    ]}
    names = o.tool_call_names(body)
    assert names.get("dup") == "", \
        "duplicate id with different names must be un-routable (empty string)"


def test_responses_dup_id_different_names_unroutable():
    """Bug 4: same scenario for Responses adapter."""
    r = ResponsesAdapter()
    body = {"input": [
        {"type": "function_call", "call_id": "dup", "name": "grep"},
        {"type": "function_call", "call_id": "dup", "name": "apply_patch"},
    ]}
    names = r.tool_call_names(body)
    assert names.get("dup") == "", \
        "duplicate id with different names must be un-routable (empty string)"


def test_same_id_same_name_harmless():
    """Bug 4: same id AND same name is harmless — must not be cleared."""
    a = AnthropicAdapter()
    body = {"messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "dup", "name": "grep", "input": {}},
            {"type": "tool_use", "id": "dup", "name": "grep", "input": {}},
        ]},
    ]}
    names = a.tool_call_names(body)
    assert names.get("dup") == "grep", \
        "same id + same name should remain routable"
