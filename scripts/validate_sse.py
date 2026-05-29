"""validate_sse.py — wire-level self-check for keymd's synthesized SSE.

Manual check (NOT part of the pytest suite, so it never flakes CI on port/threads).
Run it to confirm the real streaming path works end to end on your machine:

    python scripts/validate_sse.py

It stands up, on real sockets via uvicorn, (1) a local *stub* OpenAI-compatible
upstream and (2) the keymd proxy, then drives them with the real *sync* `openai`
SDK and stream=True over a large indexed file. No paid API is called — the stub is
local. This exercises what the in-process regression (tests/test_proxy_sse_openai_sdk.py)
cannot: real uvicorn SSE chunking + real sync httpx streaming.

PASS iff the SDK parses the stream with no error AND the gate fired (the upstream
saw the injected ⟪keymd-summary⟫ as a tool result on turn 2).
"""
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

THRESHOLD = 50  # gate files larger than this many loc


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve(app, port):
    import uvicorn
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    server.install_signal_handlers = lambda: None  # not the main thread
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError(f"uvicorn did not start on :{port}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="keymd_sse_"))
    big = tmp / "big.py"
    big.write_text(
        '"""A deliberately large module so the gate fires."""\n'
        + "\n".join(f"def fn_{i}(x):\n    return x + {i}\n" for i in range(60)),
        encoding="utf-8")

    # env MUST be set before importing keymd.proxy.server (OPENAI_BASE read at import)
    stub_port, proxy_port = _free_port(), _free_port()
    os.environ["KEYMD_PROJECT_ROOT"] = str(tmp)
    os.environ["KEYMD_INDEX_PATH"] = str(tmp / ".keymd" / "index.db")
    os.environ["KEYMD_OPENAI_BASE"] = f"http://127.0.0.1:{stub_port}"

    from keymd.engine import index
    import keymd.engine.parsers.python  # noqa: F401  (register .py parser)
    from keymd.engine.config import canonical
    index.build(verbose=False)
    target = canonical(str(big))

    # --- stub upstream -------------------------------------------------------
    import json
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    state = {"n": 0, "saw_summary": False}

    async def upstream(req):
        body = await req.json()
        i = state["n"]; state["n"] += 1
        if i == 0:  # turn 1: ask to Read the big file
            return JSONResponse({"id": "u1", "object": "chat.completion", "created": 1,
                "model": "stub", "choices": [{"index": 0, "finish_reason": "tool_calls",
                    "message": {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "c1", "type": "function", "function": {
                            "name": "Read",
                            "arguments": json.dumps({"file_path": target})}}]}}]})
        # turn 2: did the gate inject the summary as a tool result?
        saw = any(isinstance(m.get("content"), str) and "⟪keymd-summary:" in m["content"]
                  for m in body.get("messages", []) if m.get("role") == "tool")
        state["saw_summary"] = saw
        return JSONResponse({"id": "u2", "object": "chat.completion", "created": 2,
            "model": "stub", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant",
                            "content": "GATED" if saw else "NOGATE"}}]})

    stub_app = Starlette(routes=[Route("/v1/chat/completions", upstream, methods=["POST"])])

    # --- proxy ---------------------------------------------------------------
    from keymd.proxy import server
    proxy_app = server.build_app(threshold=THRESHOLD)

    _serve(stub_app, stub_port)
    _serve(proxy_app, proxy_port)

    # --- drive with the real sync openai SDK over a real socket --------------
    from openai import OpenAI
    client = OpenAI(api_key="sk-stub", base_url=f"http://127.0.0.1:{proxy_port}/v1")
    stream = client.chat.completions.create(
        model="m", stream=True, messages=[{"role": "user", "content": "go"}])
    content, n_chunks, finish = "", 0, None
    for ch in stream:                       # real SDK strict parse over the wire
        n_chunks += 1
        if ch.choices:
            content += ch.choices[0].delta.content or ""
            finish = ch.choices[0].finish_reason or finish

    ok = (content == "GATED" and state["saw_summary"] and state["n"] == 2
          and finish == "stop" and n_chunks >= 2)
    print(f"chunks={n_chunks} content={content!r} finish={finish!r} "
          f"upstream_calls={state['n']} gate_fired={state['saw_summary']}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
