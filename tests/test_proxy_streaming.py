"""Synthesized-SSE streaming: a stream:true host gets a valid event stream,
and the gate still fires (buffered) underneath."""
import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("httpx")
pytest.importorskip("starlette")
import httpx  # noqa: E402

from keymd.engine import index  # noqa: E402
import keymd.engine.parsers.python  # noqa: F401,E402


def _drive(app, path, body):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            async with c.stream("POST", path, json=body) as r:
                ctype = r.headers.get("content-type", "")
                lines = [ln async for ln in r.aiter_lines()]
                return ctype, lines
    return asyncio.run(go())


def test_openai_streaming_gates_then_synthesizes_sse(env_proj, monkeypatch):
    from keymd.proxy import server
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    scripted = [
        {"choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {
                    "name": "Read",
                    "arguments": json.dumps({"file_path": parser_py})}}]}}]},
        {"choices": [{"finish_reason": "stop",
                      "message": {"role": "assistant", "content": "all done"}}]},
    ]
    state = {"n": 0}

    async def fake_openai(body, headers):
        r = scripted[state["n"]]; state["n"] += 1; return r
    monkeypatch.setattr(server, "forward_openai", fake_openai)

    ctype, lines = _drive(server.build_app(threshold=0), "/v1/chat/completions",
                          {"model": "m", "stream": True,
                           "messages": [{"role": "user", "content": "go"}]})
    assert "text/event-stream" in ctype
    assert state["n"] == 2                       # gate fired (read summarized, then final)
    datas = [ln[len("data: "):] for ln in lines if ln.startswith("data: ")]
    assert datas[-1] == "[DONE]"
    text = "".join(
        json.loads(d)["choices"][0]["delta"].get("content", "")
        for d in datas[:-1])
    assert text == "all done"


def test_anthropic_streaming_synthesizes_sse(env_proj, monkeypatch):
    from keymd.proxy import server
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    scripted = [
        {"role": "assistant", "stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read",
             "input": {"file_path": parser_py}}]},
        {"role": "assistant", "stop_reason": "end_turn",
         "content": [{"type": "text", "text": "hi there"}]},
    ]
    state = {"n": 0}

    async def fake_anthropic(body, headers):
        r = scripted[state["n"]]; state["n"] += 1; return r
    monkeypatch.setattr(server, "forward_upstream", fake_anthropic)

    ctype, lines = _drive(server.build_app(threshold=0), "/v1/messages",
                          {"model": "m", "stream": True,
                           "messages": [{"role": "user", "content": "go"}]})
    assert "text/event-stream" in ctype
    assert state["n"] == 2
    events = [ln[len("event: "):] for ln in lines if ln.startswith("event: ")]
    assert events[0] == "message_start" and events[-1] == "message_stop"
    # the text delta carries the final answer
    text = ""
    for ln in lines:
        if ln.startswith("data: "):
            obj = json.loads(ln[len("data: "):])
            if obj.get("type") == "content_block_delta":
                text += obj["delta"].get("text", "")
    assert text == "hi there"


def test_non_stream_still_returns_json(env_proj, monkeypatch):
    # regression: omitting stream still returns a plain JSON response
    from keymd.proxy import server
    index.build(verbose=False)

    async def fake_openai(body, headers):
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": "x"}}]}
    monkeypatch.setattr(server, "forward_openai", fake_openai)
    ctype, lines = _drive(server.build_app(threshold=0), "/v1/chat/completions",
                          {"model": "m", "messages": [{"role": "user", "content": "go"}]})
    assert "application/json" in ctype
