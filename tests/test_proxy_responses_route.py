"""End-to-end: the gate fires on the OpenAI Responses wire (/v1/responses), and a
stream:true host gets a valid typed-event SSE."""
import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
import httpx  # noqa: E402

from keymd.engine import index  # noqa: E402
import keymd.engine.parsers.python  # noqa: F401,E402


def _scripted(parser_py):
    return [
        {"id": "r1", "object": "response", "model": "stub", "output": [
            {"type": "function_call", "id": "fc1", "call_id": "call1", "name": "Read",
             "arguments": json.dumps({"file_path": parser_py})}]},
        {"id": "r2", "object": "response", "model": "stub", "output": [
            {"type": "message", "id": "msg1", "role": "assistant",
             "content": [{"type": "output_text", "text": "all done"}]}]},
    ]


def _fake(scripted, state):
    async def fake(body, headers, base=None):
        r = scripted[state["n"]]; state["n"] += 1
        return r
    return fake


def test_responses_nonstream_gates(env_proj, monkeypatch):
    from keymd.proxy import server
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    state = {"n": 0}
    monkeypatch.setattr(server, "forward_responses", _fake(_scripted(parser_py), state))

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.build_app(threshold=0)),
                                     base_url="http://t") as c:
            r = await c.post("/v1/responses", json={"model": "m", "input": "go"})
            return r.json()
    out = asyncio.run(go())
    assert state["n"] == 2                              # read summarized, then final
    text = "".join(p["text"] for it in out["output"] if it["type"] == "message"
                   for p in it["content"] if p["type"] == "output_text")
    assert text == "all done"


def test_responses_stream_synthesizes_events(env_proj, monkeypatch):
    from keymd.proxy import server
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    state = {"n": 0}
    monkeypatch.setattr(server, "forward_responses", _fake(_scripted(parser_py), state))

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.build_app(threshold=0)),
                                     base_url="http://t") as c:
            async with c.stream("POST", "/v1/responses",
                                 json={"model": "m", "stream": True, "input": "go"}) as r:
                ctype = r.headers.get("content-type", "")
                lines = [ln async for ln in r.aiter_lines()]
                return ctype, lines
    ctype, lines = asyncio.run(go())
    assert "text/event-stream" in ctype
    assert state["n"] == 2
    events = [ln[len("event: "):] for ln in lines if ln.startswith("event: ")]
    assert events[0] == "response.created" and events[-1] == "response.completed"
    text = ""
    for ln in lines:
        if ln.startswith("data: "):
            obj = json.loads(ln[len("data: "):])
            if obj.get("type") == "response.output_text.delta":
                text += obj.get("delta", "")
    assert text == "all done"
