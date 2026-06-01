"""Tests for proxy/graph_server.py — free-port discovery + routes."""
import socket

from starlette.testclient import TestClient

import keymd.engine.parsers.python  # noqa: F401  (registers the .py parser)
from keymd.engine import index
from keymd.proxy import graph_server

LOOPBACK = ["localhost", "127.0.0.1", "::1"]


def _client():
    # base_url Host=localhost is in the real loopback allow-list, so the
    # DNS-rebinding guard passes for the functional tests.
    return TestClient(graph_server.build_graph_app(allowed_hosts=LOOPBACK),
                      base_url="http://localhost")


def test_free_port_returns_bindable_port():
    sock, port = graph_server._free_port(preferred=0)   # 0 = let OS pick
    assert 1 <= port <= 65535
    assert sock.getsockname()[1] == port
    sock.close()


def test_free_port_falls_back_when_preferred_busy():
    busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    taken = busy.getsockname()[1]
    try:
        sock, port = graph_server._free_port(preferred=taken)
        assert port != taken          # preferred was busy → OS-assigned fallback
        sock.close()
    finally:
        busy.close()


def test_api_graph_returns_topology(env_proj):
    index.build(verbose=False)
    r = _client().get("/api/graph")
    assert r.status_code == 200
    data = r.json()
    assert data["nodes"] and isinstance(data["edges"], list)


def test_dns_rebinding_guard_rejects_foreign_host(env_proj):
    index.build(verbose=False)
    evil = TestClient(graph_server.build_graph_app(allowed_hosts=LOOPBACK),
                      base_url="http://evil.com")
    r = evil.get("/api/graph")
    assert r.status_code == 400      # TrustedHostMiddleware rejects non-loopback Host
