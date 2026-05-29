"""server.py — Starlette ASGI shell exposing the gated proxy.

Two routes:
  POST /v1/messages          → Anthropic Messages  (AnthropicAdapter)
  POST /v1/chat/completions  → OpenAI Chat Compl.   (OpenAIAdapter)

The proxy's own upstream calls are always non-streamed (it must read whole
responses to run the gate loop). When the HOST requests stream:true, the gate
runs buffered and the final response is SYNTHESIZED into a protocol-valid SSE
stream (see _openai_sse / _anthropic_sse) so streaming clients (e.g. Hermes
Agent) work without erroring/hanging. Caveat: this is buffered-then-streamed,
NOT token-by-token — the whole answer arrives in one delta after the (possibly
multi-turn) gate completes. True incremental relay is a future refinement.
"""
from __future__ import annotations

import json
import os

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from keymd.proxy.adapters.anthropic import AnthropicAdapter
from keymd.proxy.adapters.openai import OpenAIAdapter
from keymd.proxy.adapters.responses import ResponsesAdapter
from keymd.proxy.orchestrator import complete

_FORWARD_HEADERS = ("x-api-key", "authorization", "anthropic-version",
                    "anthropic-beta", "content-type", "openai-organization")
_DEFAULT_ANTHROPIC = "https://api.anthropic.com"
_DEFAULT_OPENAI = "https://api.openai.com"


class UpstreamError(Exception):
    """A non-2xx from the upstream LLM API. Carries the status + parsed body so a
    route surfaces it to the host, instead of the gate loop misreading an
    error-shaped dict (no `output`/`choices`/`content`) as the model's final answer."""

    def __init__(self, status: int, body):
        super().__init__(f"upstream returned {status}")
        self.status = status
        self.body = body


async def _post(url: str, body: dict, headers: dict, *,
                force_nonstream: bool = True) -> dict:
    """POST upstream with the caller's auth headers. IPv4-pinned transport (proxies
    returning AAAA hang Python SDKs on a dead IPv6 route).

    force_nonstream sets stream:false (the gate must read whole responses); pass
    False for verbatim-passthrough routes that have no stream param (count_tokens).
    Raises UpstreamError on a non-2xx so the caller can propagate the real status."""
    fwd = {k: v for k, v in headers.items() if k.lower() in _FORWARD_HEADERS}
    payload = {**body, "stream": False} if force_nonstream else body
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    async with httpx.AsyncClient(transport=transport, timeout=600.0) as client:
        r = await client.post(url, json=payload, headers=fwd)
        try:
            data = r.json()
        except ValueError:
            data = {"error": {"message": r.text[:2000], "type": "upstream_non_json"}}
        if r.is_error:
            raise UpstreamError(r.status_code, data)
        return data


def _anthropic_base(override: str | None) -> str:
    # Resolved at CALL time (override > env > default) — NOT an import-time global,
    # so `keymd serve`/`run`/`up` can set the upstream after this module imports.
    return override or os.environ.get("KEYMD_UPSTREAM_BASE", _DEFAULT_ANTHROPIC)


def _openai_base(override: str | None) -> str:
    return override or os.environ.get("KEYMD_OPENAI_BASE", _DEFAULT_OPENAI)


async def forward_upstream(body: dict, headers: dict, base: str | None = None) -> dict:
    return await _post(f"{_anthropic_base(base)}/v1/messages", body, headers)


async def forward_openai(body: dict, headers: dict, base: str | None = None) -> dict:
    return await _post(f"{_openai_base(base)}/v1/chat/completions", body, headers)


async def forward_count_tokens(body: dict, headers: dict, base: str | None = None) -> dict:
    # Claude Code calls this for context management; pure passthrough (no file
    # reads to gate), so a proper Anthropic gateway must expose it or CC 404s.
    # force_nonstream=False: count_tokens has no `stream` param — don't inject one.
    return await _post(f"{_anthropic_base(base)}/v1/messages/count_tokens", body, headers,
                       force_nonstream=False)


async def forward_responses(body: dict, headers: dict, base: str | None = None) -> dict:
    return await _post(f"{_openai_base(base)}/v1/responses", body, headers)


# --- SSE synthesis -----------------------------------------------------------
# The gate loop must read whole (non-streamed) responses, so when the HOST asked
# for stream:true we run the loop buffered and then SYNTHESIZE a valid SSE stream
# from the final response. This is NOT token-by-token — the whole answer arrives
# in one delta after the gate completes — but it is a protocol-valid stream a
# streaming client (e.g. Hermes Agent) consumes without erroring/hanging.

def _openai_sse(resp: dict):
    base = {"id": resp.get("id", "chatcmpl-keymd"), "object": "chat.completion.chunk",
            "created": resp.get("created", 0), "model": resp.get("model", "")}
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message", {}) or {}
    finish = choice.get("finish_reason", "stop")

    def chunk(delta, fr=None):
        c = dict(base)
        c["choices"] = [{"index": 0, "delta": delta, "finish_reason": fr}]
        return f"data: {json.dumps(c)}\n\n"

    yield chunk({"role": "assistant"})
    if msg.get("content"):
        yield chunk({"content": msg["content"]})
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function", {}) or {}
        yield chunk({"tool_calls": [{"index": i, "id": tc.get("id"), "type": "function",
                                     "function": {"name": fn.get("name"),
                                                  "arguments": fn.get("arguments", "")}}]})
    yield chunk({}, fr=finish)
    yield "data: [DONE]\n\n"


def _anthropic_sse(resp: dict):
    meta = {k: v for k, v in resp.items() if k != "content"}
    meta.setdefault("type", "message")
    meta.setdefault("role", "assistant")
    meta["content"] = []
    yield ("event: message_start\n"
           f"data: {json.dumps({'type': 'message_start', 'message': meta})}\n\n")
    for i, block in enumerate(resp.get("content") or []):
        if block.get("type") == "text":
            cb = {"type": "text", "text": ""}
            d = {"type": "text_delta", "text": block.get("text", "")}
        elif block.get("type") == "tool_use":
            cb = {"type": "tool_use", "id": block.get("id"),
                  "name": block.get("name"), "input": {}}
            d = {"type": "input_json_delta",
                 "partial_json": json.dumps(block.get("input", {}))}
        else:
            continue
        yield ("event: content_block_start\n"
               f"data: {json.dumps({'type': 'content_block_start', 'index': i, 'content_block': cb})}\n\n")
        yield ("event: content_block_delta\n"
               f"data: {json.dumps({'type': 'content_block_delta', 'index': i, 'delta': d})}\n\n")
        yield ("event: content_block_stop\n"
               f"data: {json.dumps({'type': 'content_block_stop', 'index': i})}\n\n")
    md = {"type": "message_delta",
          "delta": {"stop_reason": resp.get("stop_reason", "end_turn"),
                    "stop_sequence": None},
          "usage": resp.get("usage", {})}
    yield f"event: message_delta\ndata: {json.dumps(md)}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"


def _responses_sse(resp: dict):
    """Synthesize the OpenAI Responses typed-event SSE from a buffered final
    response (created → output items → completed). One delta per item, not
    token-by-token, but a protocol-valid stream."""
    seq = 0

    def ev(etype: str, payload: dict) -> str:
        nonlocal seq
        out = {**payload, "type": etype, "sequence_number": seq}
        seq += 1
        return f"event: {etype}\ndata: {json.dumps(out)}\n\n"

    base_resp = {k: v for k, v in resp.items() if k != "output"}
    base_resp.setdefault("id", "resp_keymd")
    base_resp.setdefault("object", "response")
    # Fields the SDK's Response model marks required — set so a STRICT consumer
    # (model_validate, not the SDK's lenient stream path) accepts the synthesized
    # response object. Harmless to lenient consumers.
    base_resp.setdefault("created_at", resp.get("created", 0))
    base_resp.setdefault("model", resp.get("model", ""))
    base_resp.setdefault("tools", [])
    base_resp.setdefault("tool_choice", "auto")
    base_resp.setdefault("parallel_tool_calls", True)
    in_progress = {**base_resp, "status": "in_progress", "output": []}
    yield ev("response.created", {"response": in_progress})
    yield ev("response.in_progress", {"response": in_progress})

    for idx, item in enumerate(resp.get("output") or []):
        itype = item.get("type")
        iid = item.get("id", f"item_{idx}")
        if itype == "message":
            yield ev("response.output_item.added",
                     {"output_index": idx, "item": {**item, "content": []}})
            text = "".join(p.get("text", "") for p in item.get("content", [])
                           if p.get("type") == "output_text")
            yield ev("response.content_part.added",
                     {"item_id": iid, "output_index": idx, "content_index": 0,
                      "part": {"type": "output_text", "text": "", "annotations": []}})
            yield ev("response.output_text.delta",
                     {"item_id": iid, "output_index": idx, "content_index": 0,
                      "delta": text, "logprobs": []})
            yield ev("response.output_text.done",
                     {"item_id": iid, "output_index": idx, "content_index": 0,
                      "text": text, "logprobs": []})
            yield ev("response.content_part.done",
                     {"item_id": iid, "output_index": idx, "content_index": 0,
                      "part": {"type": "output_text", "text": text, "annotations": []}})
            yield ev("response.output_item.done", {"output_index": idx, "item": item})
        elif itype == "function_call":
            args = item.get("arguments", "") or ""
            yield ev("response.output_item.added",
                     {"output_index": idx, "item": {**item, "arguments": ""}})
            yield ev("response.function_call_arguments.delta",
                     {"item_id": iid, "output_index": idx, "delta": args})
            yield ev("response.function_call_arguments.done",
                     {"item_id": iid, "output_index": idx, "arguments": args})
            yield ev("response.output_item.done", {"output_index": idx, "item": item})

    yield ev("response.completed",
             {"response": {**base_resp, "status": "completed",
                           "output": resp.get("output", [])}})


def _upstream_error_response(e: "UpstreamError") -> JSONResponse:
    body = e.body if isinstance(e.body, dict) else {"error": {"message": str(e.body)}}
    return JSONResponse(body, status_code=e.status)


def build_app(threshold: int = 400, *, upstream: str | None = None,
              openai_base: str | None = None) -> Starlette:
    async def anthropic_route(request: Request):
        body = await request.json()
        hdrs = dict(request.headers)
        wants_stream = bool(body.get("stream"))

        async def up(b: dict) -> dict:  # calls the module-level fn → monkeypatchable;
            # pass `base` only when set so existing 2-arg test fakes keep working.
            return (await forward_upstream(b, hdrs) if upstream is None
                    else await forward_upstream(b, hdrs, upstream))

        try:
            result = await complete(body, AnthropicAdapter(), up, threshold=threshold)
        except UpstreamError as e:
            return _upstream_error_response(e)
        if wants_stream:
            return StreamingResponse(_anthropic_sse(result),
                                     media_type="text/event-stream")
        return JSONResponse(result)

    async def openai_route(request: Request):
        body = await request.json()
        hdrs = dict(request.headers)
        wants_stream = bool(body.get("stream"))

        async def up(b: dict) -> dict:
            return (await forward_openai(b, hdrs) if openai_base is None
                    else await forward_openai(b, hdrs, openai_base))

        try:
            result = await complete(body, OpenAIAdapter(), up, threshold=threshold)
        except UpstreamError as e:
            return _upstream_error_response(e)
        if wants_stream:
            return StreamingResponse(_openai_sse(result),
                                     media_type="text/event-stream")
        return JSONResponse(result)

    async def count_tokens_route(request: Request):
        # Passthrough — no gate loop (nothing to intercept in a token count).
        body = await request.json()
        hdrs = dict(request.headers)
        try:
            result = (await forward_count_tokens(body, hdrs) if upstream is None
                      else await forward_count_tokens(body, hdrs, upstream))
        except UpstreamError as e:
            return _upstream_error_response(e)
        return JSONResponse(result)

    async def responses_route(request: Request):
        body = await request.json()
        hdrs = dict(request.headers)
        wants_stream = bool(body.get("stream"))

        async def up(b: dict) -> dict:
            return (await forward_responses(b, hdrs) if openai_base is None
                    else await forward_responses(b, hdrs, openai_base))

        try:
            result = await complete(body, ResponsesAdapter(), up, threshold=threshold)
        except UpstreamError as e:
            return _upstream_error_response(e)
        if wants_stream:
            return StreamingResponse(_responses_sse(result),
                                     media_type="text/event-stream")
        return JSONResponse(result)

    return Starlette(routes=[
        Route("/v1/messages/count_tokens", count_tokens_route, methods=["POST"]),
        Route("/v1/messages", anthropic_route, methods=["POST"]),
        Route("/v1/chat/completions", openai_route, methods=["POST"]),
        Route("/v1/responses", responses_route, methods=["POST"]),
    ])


def serve(host: str = "127.0.0.1", port: int = 8787, threshold: int = 400,
          *, upstream: str | None = None, openai_base: str | None = None) -> None:
    import uvicorn
    uvicorn.run(build_app(threshold=threshold, upstream=upstream, openai_base=openai_base),
                host=host, port=port)
