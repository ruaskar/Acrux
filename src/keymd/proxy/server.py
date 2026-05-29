"""server.py — Starlette ASGI shell exposing the gated proxy (Phase 3a, non-streaming).

POST /v1/messages → run the gate orchestrator with a real upstream forwarder,
return the (possibly locally-resolved) Anthropic response as JSON. Streaming and
the OpenAI surface are Phase 3b.
"""
from __future__ import annotations

import os

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy.orchestrator import complete

UPSTREAM_BASE = os.environ.get("KEYMD_UPSTREAM_BASE", "https://api.anthropic.com")
_FORWARD_HEADERS = ("x-api-key", "authorization", "anthropic-version",
                    "anthropic-beta", "content-type")


async def forward_upstream(body: dict, headers: dict) -> dict:
    """POST the (transformed) body to the real Anthropic Messages endpoint with
    the caller's own auth headers. IPv4-pinned transport (see the VPS-egress
    lesson: proxies returning AAAA hang Python SDKs on a dead IPv6 route)."""
    fwd = {k: v for k, v in headers.items() if k.lower() in _FORWARD_HEADERS}
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    async with httpx.AsyncClient(transport=transport, timeout=600.0) as client:
        r = await client.post(f"{UPSTREAM_BASE}/v1/messages", json=body, headers=fwd)
        return r.json()


def build_app(threshold: int = 400) -> Starlette:
    async def messages(request: Request) -> JSONResponse:
        body = await request.json()
        hdrs = dict(request.headers)

        async def upstream(b: dict) -> dict:
            # reference the module global by name so tests can monkeypatch it
            return await forward_upstream(b, hdrs)

        result = await complete(body, AnthropicAdapter(), upstream,
                                threshold=threshold)
        return JSONResponse(result)

    return Starlette(routes=[Route("/v1/messages", messages, methods=["POST"])])


def serve(host: str = "127.0.0.1", port: int = 8787, threshold: int = 400) -> None:
    import uvicorn
    uvicorn.run(build_app(threshold=threshold), host=host, port=port)
