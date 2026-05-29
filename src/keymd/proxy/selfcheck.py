"""selfcheck.py — in-process validation of the gate + synthesized-SSE path.

No socket, no API spend: a scripted local stub upstream driven through
httpx.ASGITransport. `keymd doctor --wire` calls run_inprocess(); the real-socket
script scripts/validate_sse.py reuses the shared response builders below (it keeps
its own real-SDK driver). run_inprocess saves/restores the KEYMD_* env it sets, so
it leaves no global state behind.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

MARKER = "⟪keymd-summary:"  # ⟪keymd-summary:


def build_big_repo() -> tuple[Path, str]:
    """A temp repo with one deliberately large module; returns (root, abs file)."""
    tmp = Path(tempfile.mkdtemp(prefix="keymd_selfcheck_"))
    big = tmp / "big.py"
    big.write_text("\n".join(f"def fn_{i}(x):\n    return x + {i}\n"
                             for i in range(60)), encoding="utf-8")
    return tmp, str(big)


def turn1_read(target: str) -> dict:
    """Scripted OpenAI response: ask to Read the gated file."""
    return {"id": "u1", "object": "chat.completion", "created": 1, "model": "stub",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {
                        "name": "Read",
                        "arguments": json.dumps({"file_path": target})}}]}}]}


def turn2_report(saw: bool) -> dict:
    """Scripted OpenAI response: 'GATED' iff the summary was injected as a tool result."""
    return {"id": "u2", "object": "chat.completion", "created": 2, "model": "stub",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "GATED" if saw else "NOGATE"}}]}


def saw_summary(messages: list) -> bool:
    return any(isinstance(m.get("content"), str) and MARKER in m["content"]
               for m in messages if m.get("role") == "tool")


def run_inprocess(threshold: int = 10) -> dict:
    """Build a temp index, drive build_app through a scripted stub via ASGITransport,
    and confirm the gate fired and the synthesized SSE reassembles to 'GATED'.
    Returns {ok, gate_fired, chunks, detail}. Side-effect free (env restored)."""
    import os

    import httpx

    from keymd.engine import config as c
    from keymd.engine import index
    import keymd.engine.parsers.python  # noqa: F401
    from keymd.proxy import server

    tmp, big = build_big_repo()
    saved = {k: os.environ.get(k) for k in ("KEYMD_PROJECT_ROOT", "KEYMD_INDEX_PATH")}
    orig_forward = server.forward_openai
    try:
        os.environ["KEYMD_PROJECT_ROOT"] = str(tmp)
        os.environ["KEYMD_INDEX_PATH"] = str(tmp / ".keymd" / "index.db")
        c.project_pkg_prefixes.cache_clear()
        c._git_toplevel.cache_clear()
        index.build(verbose=False)
        target = c.canonical(big)
        state = {"n": 0, "saw": False}

        async def fake(body, headers, base=None):
            i = state["n"]; state["n"] += 1
            if i == 0:
                return turn1_read(target)
            state["saw"] = saw_summary(body.get("messages", []))
            return turn2_report(state["saw"])
        server.forward_openai = fake
        app = server.build_app(threshold=threshold)

        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://t") as cx:
                async with cx.stream("POST", "/v1/chat/completions",
                                     json={"model": "m", "stream": True,
                                           "messages": [{"role": "user",
                                                         "content": "go"}]}) as r:
                    return [ln async for ln in r.aiter_lines()]
        lines = asyncio.run(go())
    finally:
        server.forward_openai = orig_forward
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        c.project_pkg_prefixes.cache_clear()
        c._git_toplevel.cache_clear()

    datas = [ln[len("data: "):] for ln in lines if ln.startswith("data: ")]
    content = "".join(json.loads(d)["choices"][0]["delta"].get("content", "")
                      for d in datas if d != "[DONE]")
    return {"ok": content == "GATED" and state["saw"] and state["n"] == 2,
            "gate_fired": state["saw"], "chunks": len(datas), "detail": content}
