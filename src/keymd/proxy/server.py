"""server.py — Starlette ASGI shell exposing the gated proxy.

Two routes, both NON-STREAMING (Phase 3b core):
  POST /v1/messages          → Anthropic Messages  (AnthropicAdapter)
  POST /v1/chat/completions  → OpenAI Chat Compl.   (OpenAIAdapter)

The proxy's own upstream calls are always non-streamed (it must read whole
responses to run the gate loop). SSE passthrough for a streaming HOST is a
Phase-4 live-integration item — until then, point the host at the proxy in
non-streaming mode. (A streaming host will receive JSON; that's the documented
boundary, not a silent failure.)
"""
from __future__ import annotations

import os

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy.adapters.openai import OpenAIAdapter
from keymd.proxy.orchestrator import complete

UPSTREAM_BASE = os.environ.get("KEYMD_UPSTREAM_BASE", "https://api.anthropic.com")
OPENAI_BASE = os.environ.get("KEYMD_OPENAI_BASE", "https://api.openai.com")
_FORWARD_HEADERS = ("x-api-key", "authorization", "anthropic-version",
                    "anthropic-beta", "content-type", "openai-organization")


async def _post(url: str, body: dict, headers: dict) -> dict:
    """POST a NON-streamed request upstream with the caller's auth headers.
    IPv4-pinned transport (proxies returning AAAA hang Python SDKs on a dead
    IPv6 route)."""
    fwd = {k: v for k, v in headers.items() if k.lower() in _FORWARD_HEADERS}
    payload = {**body, "stream": False}  # internal calls are always non-streamed
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    async with httpx.AsyncClient(transport=transport, timeout=600.0) as client:
        r = await client.post(url, json=payload, headers=fwd)
        return r.json()


async def forward_upstream(body: dict, headers: dict) -> dict:
    return await _post(f"{UPSTREAM_BASE}/v1/messages", body, headers)


async def forward_openai(body: dict, headers: dict) -> dict:
    return await _post(f"{OPENAI_BASE}/v1/chat/completions", body, headers)


def build_app(threshold: int = 400) -> Starlette:
    async def anthropic_route(request: Request) -> JSONResponse:
        body = await request.json()
        hdrs = dict(request.headers)

        async def upstream(b: dict) -> dict:
            return await forward_upstream(b, hdrs)  # module global → monkeypatchable

        result = await complete(body, AnthropicAdapter(), upstream, threshold=threshold)
        return JSONResponse(result)

    async def openai_route(request: Request) -> JSONResponse:
        body = await request.json()
        hdrs = dict(request.headers)

        async def upstream(b: dict) -> dict:
            return await forward_openai(b, hdrs)

        result = await complete(body, OpenAIAdapter(), upstream, threshold=threshold)
        return JSONResponse(result)

    return Starlette(routes=[
        Route("/v1/messages", anthropic_route, methods=["POST"]),
        Route("/v1/chat/completions", openai_route, methods=["POST"]),
    ])


def serve(host: str = "127.0.0.1", port: int = 8787, threshold: int = 400) -> None:
    import uvicorn
    uvicorn.run(build_app(threshold=threshold), host=host, port=port)
