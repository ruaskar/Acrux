"""Tests for the summarize protocol adapters (OpenAI + Anthropic wire shapes)."""
from keymd.summarize.adapters import WIRES, AnthropicWire, OpenAIWire


def test_openai_wire_shape():
    w = OpenAIWire()
    # endpoint() appends ONLY /chat/completions — the version lives in the base
    # (OpenAI SDK + LiteLLM convention). The default base (run._ENV) carries /v1.
    assert w.endpoint("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"
    # trailing slash on base must not double up
    assert w.endpoint("https://api.openai.com/v1/") == "https://api.openai.com/v1/chat/completions"
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


# Regression guard for the hardcoded-/v1 bug: each provider's OWN documented base
# URL (version already in it) must produce a single, correct /chat/completions —
# never a doubled /v1/v1. Bases verified against each provider's official docs.
def test_openai_compatible_provider_base_urls_compose_correctly():
    w = OpenAIWire()
    cases = {
        "https://api.openai.com/v1":
            "https://api.openai.com/v1/chat/completions",
        "https://api.deepseek.com/v1":
            "https://api.deepseek.com/v1/chat/completions",
        "https://generativelanguage.googleapis.com/v1beta/openai":
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1":
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        "http://localhost:11434/v1":               # Ollama
            "http://localhost:11434/v1/chat/completions",
        "http://localhost:1234/v1":                # LM Studio
            "http://localhost:1234/v1/chat/completions",
    }
    for base, expected in cases.items():
        assert w.endpoint(base) == expected, f"{base} -> {w.endpoint(base)}"
        assert "/v1/v1/" not in w.endpoint(base)   # never double the version


def test_default_openai_base_composes_to_canonical_url():
    """The default base in run._ENV must already carry the version so the bare
    `--wire openai` default still hits the real OpenAI endpoint."""
    from keymd.summarize.run import _ENV
    default_base = _ENV["openai"][1]
    assert OpenAIWire().endpoint(default_base) == "https://api.openai.com/v1/chat/completions"
