"""Regression: the upstream base is resolved at CALL time, not at import time.

The old `OPENAI_BASE`/`UPSTREAM_BASE` module globals were read once at import, so
`keymd serve` (which imports server) ignored env set afterward — the documented
"set env BEFORE serve" footgun. These tests pin call-time resolution + override.
"""
import asyncio

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
from keymd.proxy import server  # noqa: E402


def test_openai_base_resolved_at_call_time(monkeypatch):
    captured = {}

    async def fake_post(url, body, headers):
        captured["url"] = url
        return {}
    monkeypatch.setattr(server, "_post", fake_post)
    # env set AFTER import — the old import-time global ignored this (the footgun)
    monkeypatch.setenv("KEYMD_OPENAI_BASE", "http://late:1234")
    asyncio.run(server.forward_openai({}, {}))
    assert captured["url"] == "http://late:1234/v1/chat/completions"
    # explicit override beats env
    asyncio.run(server.forward_openai({}, {}, "http://override:9"))
    assert captured["url"] == "http://override:9/v1/chat/completions"


def test_anthropic_base_default_and_override(monkeypatch):
    captured = {}

    async def fake_post(url, body, headers):
        captured["url"] = url
        return {}
    monkeypatch.setattr(server, "_post", fake_post)
    monkeypatch.delenv("KEYMD_UPSTREAM_BASE", raising=False)
    asyncio.run(server.forward_upstream({}, {}))
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    asyncio.run(server.forward_upstream({}, {}, "http://a:1"))
    assert captured["url"] == "http://a:1/v1/messages"
