"""Validate the synthesized Responses SSE against the REAL openai SDK's Responses
stream parser (client.responses.create(stream=True)) — the strict-client check that
the manual-parse route test can't give. Also guards the strict-conformance fixes
(created_at/tools/tool_choice/parallel_tool_calls, logprobs, annotations)."""
import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
pytest.importorskip("openai")
import httpx  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from keymd.engine import index  # noqa: E402
import keymd.engine.parsers.python  # noqa: F401,E402


def test_openai_sdk_consumes_responses_sse(env_proj, monkeypatch):
    from keymd.proxy import server
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    scripted = [
        {"id": "resp_1", "object": "response", "model": "stub", "created": 1, "output": [
            {"type": "function_call", "id": "fc1", "call_id": "call1", "name": "Read",
             "arguments": json.dumps({"file_path": parser_py})}]},
        {"id": "resp_2", "object": "response", "model": "stub", "created": 2, "output": [
            {"type": "message", "id": "msg1", "role": "assistant",
             "content": [{"type": "output_text", "text": "all done", "annotations": []}]}]},
    ]
    state = {"n": 0}

    async def fake(body, headers, base=None):
        r = scripted[state["n"]]; state["n"] += 1
        return r
    monkeypatch.setattr(server, "forward_responses", fake)
    app = server.build_app(threshold=0)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as hc:
            client = AsyncOpenAI(api_key="sk-stub", base_url="http://t/v1", http_client=hc)
            stream = await client.responses.create(model="m", input="go", stream=True)
            return [ev async for ev in stream]  # SDK strict-parses each event here

    events = asyncio.run(go())
    assert state["n"] == 2                                   # gate fired
    types = [getattr(e, "type", None) for e in events]
    assert "response.created" in types and "response.completed" in types
    text = "".join(getattr(e, "delta", "") for e in events
                   if getattr(e, "type", None) == "response.output_text.delta")
    assert text == "all done"
