import asyncio
from pathlib import Path

from keymd.engine import index
from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy.orchestrator import complete, MAX_INNER_TURNS
import keymd.engine.parsers.python  # noqa: F401


def _mock_upstream(scripted):
    calls = {"bodies": []}

    async def upstream(body):
        calls["bodies"].append(body)
        i = len(calls["bodies"]) - 1
        return scripted[min(i, len(scripted) - 1)]
    return upstream, calls


def _tool_use(name, inp, tid):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _turn(*blocks):
    return {"role": "assistant", "stop_reason": "tool_use", "content": list(blocks)}


def _final(text="done"):
    return {"role": "assistant", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}]}


def _run(scripted):
    up, calls = _mock_upstream(scripted)
    body = {"model": "m", "system": "s", "messages": [
        {"role": "user", "content": [{"type": "text", "text": "refactor it"}]}]}
    resp = asyncio.run(complete(body, AnthropicAdapter(), up, threshold=0))
    return resp, calls


def test_gated_read_is_summarized_then_proceeds(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    resp, calls = _run([_turn(_tool_use("Read", {"file_path": parser_py}, "t1")),
                        _final("ok")])
    assert resp["stop_reason"] == "end_turn"
    assert len(calls["bodies"]) == 2
    tr = calls["bodies"][1]["messages"][-1]["content"][0]
    assert tr["type"] == "tool_result" and "keymd-summary" in tr["content"]


def test_virtual_tool_answered_locally(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    resp, calls = _run([_turn(_tool_use("keymd_impact", {"path": parser_py}, "v1")),
                        _final()])
    assert resp["stop_reason"] == "end_turn"
    assert len(calls["bodies"]) == 2


def test_host_tool_forwarded_immediately(env_proj):
    index.build(verbose=False)
    resp, calls = _run([_turn(_tool_use("Bash", {"command": "ls"}, "b1")), _final()])
    assert resp["content"][0]["name"] == "Bash"
    assert len(calls["bodies"]) == 1


def test_mixed_turn_forwards_whole_turn(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    resp, calls = _run([_turn(_tool_use("Read", {"file_path": parser_py}, "r1"),
                              _tool_use("Bash", {"command": "ls"}, "b1")), _final()])
    assert len(resp["content"]) == 2
    assert len(calls["bodies"]) == 1


def test_final_with_no_tools_returns_immediately(env_proj):
    index.build(verbose=False)
    resp, calls = _run([_final("hi")])
    assert resp["content"][0]["text"] == "hi"
    assert len(calls["bodies"]) == 1


def test_no_index_is_transparent_passthrough(env_proj):
    # env_proj sets KEYMD_INDEX_PATH to a tmp file but we DON'T build it → no index.
    # keymd must add NOTHING: no virtual tools, no [keymd] directive, one upstream call.
    resp, calls = _run([_turn(_tool_use("Read", {"file_path": "/x/big.py"}, "t1")),
                        _final("ok")])
    assert len(calls["bodies"]) == 1                      # gate loop never ran
    sent = calls["bodies"][0]
    assert "tools" not in sent or not any(
        t.get("name", "").startswith("keymd_") for t in sent["tools"])
    assert "[keymd]" not in (sent.get("system") or "")     # directive not injected
    # the original host turn (with the un-gated Read) is returned verbatim
    assert resp["content"][0]["name"] == "Read"


def test_multi_nonhost_turn_answers_every_id_in_order(env_proj):
    # 2 gated reads (different files) + 1 virtual, all non-host → all resolved
    # locally; the next user turn must carry exactly 3 tool_results, ids in order.
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    pipeline_py = str(Path(env_proj) / "pkg" / "pipeline.py")
    turn = _turn(_tool_use("Read", {"file_path": parser_py}, "a"),
                 _tool_use("Read", {"file_path": pipeline_py}, "b"),
                 _tool_use("keymd_impact", {"path": parser_py}, "c"))
    resp, calls = _run([turn, _final()])
    assert resp["stop_reason"] == "end_turn"
    second = calls["bodies"][1]["messages"]
    assistant_turn = second[-2]
    user_results = second[-1]["content"]
    assert len(assistant_turn["content"]) == 3       # all 3 tool_use blocks echoed
    assert [r["tool_use_id"] for r in user_results] == ["a", "b", "c"]  # 1:1, in order
    assert all(r["type"] == "tool_result" for r in user_results)


def test_budget_exhaustion_returns_synthetic_terminal(env_proj):
    # model loops forever emitting a virtual tool; orchestrator must bail with a
    # consumable terminal turn, never an unanswerable tool_use turn.
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    loop_turn = _turn(_tool_use("keymd_read", {"path": parser_py}, "x"))
    resp, calls = _run([loop_turn] * (MAX_INNER_TURNS + 5))
    assert resp["stop_reason"] == "end_turn"
    assert all(b["type"] != "tool_use" for b in resp["content"])
    assert len(calls["bodies"]) == MAX_INNER_TURNS
