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
import threading
import time

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
    # Shared with keymd doctor --wire: the temp repo + scripted response bodies
    # live in keymd.proxy.selfcheck (DRY). This script keeps its distinct
    # real-socket + real-SDK driver below.
    from keymd.proxy import selfcheck
    tmp, big = selfcheck.build_big_repo()

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

    # --- stub upstream (Starlette route over a real socket) ------------------
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    state = {"n": 0, "saw_summary": False}

    async def upstream(req):
        body = await req.json()
        i = state["n"]; state["n"] += 1
        if i == 0:  # turn 1: ask to Read the big file
            return JSONResponse(selfcheck.turn1_read(target))
        # turn 2: did the gate inject the summary as a tool result?
        state["saw_summary"] = selfcheck.saw_summary(body.get("messages", []))
        return JSONResponse(selfcheck.turn2_report(state["saw_summary"]))

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
