import asyncio
import json
from pathlib import Path

from keymd.engine import index
from keymd.proxy.adapters.openai import OpenAIAdapter
from keymd.proxy.orchestrator import complete
import keymd.engine.parsers.python  # noqa: F401

O = OpenAIAdapter()


def _tc(name, args_json, tid):
    return {"id": tid, "type": "function",
            "function": {"name": name, "arguments": args_json}}


def _asst(tool_calls):
    return {"choices": [{"finish_reason": "tool_calls",
                         "message": {"role": "assistant", "content": None,
                                     "tool_calls": tool_calls}}]}


def _final(text="done"):
    return {"choices": [{"finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}]}


def test_inject_tools_and_system():
    body = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "tools": []}
    out = O.inject(body)
    names = {t["function"]["name"] for t in out["tools"]}
    assert "keymd_read" in names
    assert out["messages"][0]["role"] == "system" and "keymd_read" in out["messages"][0]["content"]


def test_inject_idempotent_with_existing_system():
    body = {"messages": [{"role": "system", "content": "base"}]}
    once = O.inject(body)
    twice = O.inject({"messages": [m.copy() for m in once["messages"]],
                      "tools": list(once["tools"])})
    assert once["messages"][0]["content"] == twice["messages"][0]["content"]


def test_tool_uses_parses_arguments():
    resp = _asst([_tc("Read", '{"file_path": "a.py"}', "call_1")])
    calls = O.tool_uses(resp)
    assert len(calls) == 1
    assert calls[0].id == "call_1" and calls[0].name == "Read"
    assert calls[0].input["file_path"] == "a.py"
    assert O.tool_uses(_final()) == []


def test_appends_and_terminal():
    body = {"messages": []}
    body = O.append_assistant(body, _asst([_tc("Read", "{}", "c1")]))
    body = O.append_tool_results(body, [("c1", "SUMMARY")])
    assert body["messages"][0]["role"] == "assistant"
    assert body["messages"][1] == {"role": "tool", "tool_call_id": "c1", "content": "SUMMARY"}
    term = O.terminal("bye", template={"id": "x", "usage": {"total_tokens": 1}})
    assert term["choices"][0]["message"]["content"] == "bye"
    assert term["choices"][0]["finish_reason"] == "stop"
    assert term["id"] == "x"


def test_orchestrator_is_adapter_agnostic_openai(env_proj):
    # the SAME orchestrator gates a read via the OpenAI wire format
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    scripted = [_asst([_tc("Read", json.dumps({"file_path": parser_py}), "c1")]), _final("ok")]
    state = {"n": 0}

    async def up(b):
        r = scripted[state["n"]]; state["n"] += 1; return r
    body = {"model": "m", "messages": [{"role": "user", "content": "go"}]}
    resp = asyncio.run(complete(body, O, up, threshold=0))
    assert resp["choices"][0]["finish_reason"] == "stop"
    assert state["n"] == 2
    # the injected tool result rode the OpenAI 'tool' role
    tool_msg = [m for m in body["messages"] if m.get("role") == "tool"]
    assert tool_msg and "keymd-summary" in tool_msg[0]["content"]
