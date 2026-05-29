"""Validate synthesized SSE against the REAL `openai` SDK's strict
ChatCompletionChunk parser — not a hand-rolled json.loads (test_proxy_streaming.py
already covers the line-parseable-JSON case).

This closes the catchup caveat "synthesized SSE not validated against a live strict
SSE client" for the in-process path. The SDK's pydantic validation of every chunk is
the same code the wire path runs, so a clean parse here means a clean parse over a
socket; scripts/validate_sse.py exercises the real socket too.

The stub upstream's turn-2 reply encodes whether the gate injected the summary, so a
single content assertion proves BOTH (a) the SDK parsed the stream without error and
(b) the gate fired underneath the stream.
"""
import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("httpx")
pytest.importorskip("starlette")
pytest.importorskip("openai")
import httpx  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from keymd.engine import index  # noqa: E402
import keymd.engine.parsers.python  # noqa: F401,E402

MARKER = "⟪keymd-summary:"  # ⟪keymd-summary:


def _stub_upstream(parser_py, state):
    """An OpenAI-compatible upstream: turn 1 asks to Read the gated file; turn 2
    reports whether the gate injected the summary as a tool result."""
    async def fake_openai(body, headers):
        i = state["n"]
        state["n"] += 1
        if i == 0:
            return {
                "id": "chatcmpl-1", "object": "chat.completion", "created": 1,
                "model": "stub", "choices": [{"index": 0,
                    "finish_reason": "tool_calls", "message": {
                        "role": "assistant", "content": None, "tool_calls": [
                            {"id": "c1", "type": "function", "function": {
                                "name": "Read",
                                "arguments": json.dumps({"file_path": parser_py})}}]}}]}
        saw = any(isinstance(m.get("content"), str) and MARKER in m["content"]
                  for m in body.get("messages", []) if m.get("role") == "tool")
        state["saw_summary"] = saw
        return {"id": "chatcmpl-2", "object": "chat.completion", "created": 2,
                "model": "stub", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant",
                                "content": "GATED" if saw else "NOGATE"}}]}
    return fake_openai


def test_openai_sdk_consumes_synthesized_sse(env_proj, monkeypatch):
    from keymd.proxy import server

    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    state = {"n": 0, "saw_summary": False}
    monkeypatch.setattr(server, "forward_openai", _stub_upstream(parser_py, state))
    app = server.build_app(threshold=0)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as http_client:
            client = AsyncOpenAI(api_key="sk-stub", base_url="http://t/v1",
                                 http_client=http_client)
            stream = await client.chat.completions.create(
                model="m", stream=True,
                messages=[{"role": "user", "content": "go"}])
            return [ch async for ch in stream]  # SDK strict-parses each chunk here

    chunks = asyncio.run(go())

    # (a) the SDK parsed every chunk into a ChatCompletionChunk without raising
    assert chunks, "SDK yielded no chunks"
    assert all(ch.object == "chat.completion.chunk" for ch in chunks)
    # (b) the gate fired (upstream saw the injected summary) AND the SDK reassembled
    #     the streamed answer
    content = "".join(ch.choices[0].delta.content or ""
                      for ch in chunks if ch.choices)
    assert content == "GATED"
    assert state["saw_summary"] is True
    assert state["n"] == 2  # exactly one gate loop: read summarized, then final
    # finish_reason surfaced on the terminal chunk
    assert any(ch.choices and ch.choices[0].finish_reason == "stop" for ch in chunks)
