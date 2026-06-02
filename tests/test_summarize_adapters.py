"""Tests for the summarize protocol adapters (OpenAI + Anthropic wire shapes)."""
from keymd.summarize.adapters import WIRES, AnthropicWire, OpenAIWire


def test_openai_wire_shape():
    w = OpenAIWire()
    assert w.endpoint("https://api.openai.com") == "https://api.openai.com/v1/chat/completions"
    # trailing slash on base must not double up
    assert w.endpoint("https://api.openai.com/") == "https://api.openai.com/v1/chat/completions"
    body = w.build_request("SYS", "def f(): pass", "gpt-4o", 512)
    assert body["model"] == "gpt-4o"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == "SYS"
    assert "def f()" in body["messages"][1]["content"]
    assert w.auth_headers("KEY")["Authorization"] == "Bearer KEY"
    resp = {"choices": [{"message": {"content": "It defines f."}}]}
    assert w.extract_text(resp) == "It defines f."
    # robust to an empty/error-shaped response
    assert w.extract_text({}) == ""


def test_anthropic_wire_shape():
    w = AnthropicWire()
    assert w.endpoint("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"
    body = w.build_request("SYS", "class C: ...", "claude-sonnet-4-6", 512)
    assert body["model"] == "claude-sonnet-4-6"
    assert body["system"] == "SYS"
    assert body["max_tokens"] == 512
    assert "class C" in body["messages"][0]["content"]
    h = w.auth_headers("KEY")
    assert h["x-api-key"] == "KEY" and "anthropic-version" in h
    resp = {"content": [{"type": "text", "text": "Defines class C."}]}
    assert w.extract_text(resp) == "Defines class C."
    assert w.extract_text({}) == ""
    assert w.extract_text({"content": []}) == ""
    # a text block with an explicit null value must not crash "".join
    assert w.extract_text({"content": [{"type": "text", "text": None}]}) == ""


def test_registry_has_both():
    assert set(WIRES) == {"openai", "anthropic"}
    assert isinstance(WIRES["openai"], OpenAIWire)
    assert isinstance(WIRES["anthropic"], AnthropicWire)
