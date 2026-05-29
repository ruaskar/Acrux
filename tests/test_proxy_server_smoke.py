import asyncio
from pathlib import Path

import pytest

pytest.importorskip("httpx")
pytest.importorskip("starlette")
import httpx  # noqa: E402

from keymd.engine import index  # noqa: E402
import keymd.engine.parsers.python  # noqa: F401,E402


def test_server_gates_read_via_asgi(env_proj, monkeypatch):
    from keymd.proxy import server
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    scripted = [
        {"role": "assistant", "stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read",
             "input": {"file_path": parser_py}}]},
        {"role": "assistant", "stop_reason": "end_turn",
         "content": [{"type": "text", "text": "ok"}]},
    ]
    state = {"n": 0}

    async def fake_upstream(body, headers):
        r = scripted[state["n"]]
        state["n"] += 1
        return r
    monkeypatch.setattr(server, "forward_upstream", fake_upstream)

    app = server.build_app(threshold=0)

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.post("/v1/messages", json={
                "model": "m", "system": "s",
                "messages": [{"role": "user",
                              "content": [{"type": "text", "text": "go"}]}]})

    resp = asyncio.run(go())
    assert resp.status_code == 200
    assert resp.json()["stop_reason"] == "end_turn"
    assert state["n"] == 2  # gated turn resolved locally, then final
