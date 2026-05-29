"""Claude Code calls /v1/messages/count_tokens; a proper Anthropic gateway must
expose it. keymd forwards it verbatim (no gating — nothing to intercept)."""
import asyncio

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
import httpx  # noqa: E402

from keymd.proxy import server  # noqa: E402


def test_count_tokens_forwarded_verbatim(monkeypatch):
    seen = {}

    async def fake_post(url, body, headers):
        seen["url"] = url
        return {"input_tokens": 42}
    monkeypatch.setattr(server, "_post", fake_post)
    app = server.build_app(threshold=0)

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/v1/messages/count_tokens",
                             json={"model": "m",
                                   "messages": [{"role": "user", "content": "hi"}]})
            return r.status_code, r.json()
    code, data = asyncio.run(go())
    assert code == 200
    assert data == {"input_tokens": 42}
    assert seen["url"].endswith("/v1/messages/count_tokens")
