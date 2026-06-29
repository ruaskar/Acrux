# tests/test_proxy_result_bound.py
from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy.result_bound import bound_results, MARKER_RE


def _body(text, name="grep"):
    return {"messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": name, "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": text}]},
    ]}


def _shrink(_):                      # dummy rule: always returns a tiny body
    return "BOUNDED"


def test_bounds_large_matching_tool():
    big = "x" * 5000
    body = _body(big)
    bound_results(body, AnthropicAdapter(), {r"grep": _shrink},
                  min_bytes=1500, fresh_results=0)
    out = body["messages"][1]["content"][0]["content"]
    assert "BOUNDED" in out and MARKER_RE.search(out)


def test_skips_small_result():
    body = _body("tiny")
    bound_results(body, AnthropicAdapter(), {r"grep": _shrink},
                  min_bytes=1500, fresh_results=0)
    assert body["messages"][1]["content"][0]["content"] == "tiny"


def test_skips_unknown_tool():
    body = _body("x" * 5000, name="Read")   # not in rules
    bound_results(body, AnthropicAdapter(), {r"grep": _shrink},
                  min_bytes=1500, fresh_results=0)
    assert body["messages"][1]["content"][0]["content"] == "x" * 5000


def test_idempotent():
    body = _body("x" * 5000)
    a = AnthropicAdapter()
    bound_results(body, a, {r"grep": _shrink}, min_bytes=1500, fresh_results=0)
    once = body["messages"][1]["content"][0]["content"]
    bound_results(body, a, {r"grep": _shrink}, min_bytes=1500, fresh_results=0)
    assert body["messages"][1]["content"][0]["content"] == once  # no double-wrap


def test_fresh_window_protected():
    body = _body("x" * 5000)
    bound_results(body, AnthropicAdapter(), {r"grep": _shrink},
                  min_bytes=1500, fresh_results=1)   # the only result is "fresh"
    assert body["messages"][1]["content"][0]["content"] == "x" * 5000


def test_rule_returns_none_leaves_untouched():
    body = _body("x" * 5000)
    bound_results(body, AnthropicAdapter(), {r"grep": lambda _: None},
                  min_bytes=1500, fresh_results=0)
    assert body["messages"][1]["content"][0]["content"] == "x" * 5000
