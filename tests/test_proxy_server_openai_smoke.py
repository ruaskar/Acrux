import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("httpx")
pytest.importorskip("starlette")
import httpx  # noqa: E402

from keymd.engine import index  # noqa: E402
import keymd.engine.parsers.python  # noqa: F401,E402


def test_openai_route_gates_read_via_asgi(env_proj, monkeypatch):
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
                      "message": {"role": "assistant", "content": "ok"}}]},
    ]
    state = {"n": 0}

    async def fake_openai(body, headers):
        r = scripted[state["n"]]; state["n"] += 1; return r
    monkeypatch.setattr(server, "forward_openai", fake_openai)

    app = server.build_app(threshold=0)

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.post("/v1/chat/completions", json={
                "model": "m",
                "messages": [{"role": "user", "content": "go"}]})

    resp = asyncio.run(go())
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["finish_reason"] == "stop"
    assert state["n"] == 2  # gated turn resolved locally, then final
