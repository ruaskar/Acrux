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


def test_index_route_serves_html(env_proj):
    index.build(verbose=False)
    r = _client().get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<svg" in r.text or "d3.v7.min.js" in r.text


def test_d3_asset_served(env_proj):
    r = _client().get("/d3.v7.min.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert len(r.text) > 250_000           # the real vendored bundle, not a stub


def test_api_summary_returns_summary(env_proj):
    import os
    index.build(verbose=False)
    r = _client().get("/api/summary", params={"path": os.path.join("pkg", "parser.py")})
    assert r.status_code == 200
    assert "Parser" in r.json()["summary"]   # the class shows up in the .key.md


def test_api_summary_refuses_path_outside_root(env_proj):
    index.build(verbose=False)
    r = _client().get("/api/summary", params={"path": "../../../../etc/passwd"})
    assert r.status_code == 400
    assert "summary" not in r.json()         # refused before any read


def test_api_summary_hides_string_values(monkeypatch, tmp_path):
    # A hardcoded secret must render as <str>, never verbatim, through the graph surface.
    import os
    proj = tmp_path / "proj"
    (proj / "app").mkdir(parents=True)
    (proj / "app" / "conf.py").write_text(
        'API_KEY = "sk-ant-supersecret-DO-NOT-LEAK"\n'
        'def boot(token: str = "sk-ant-supersecret-DO-NOT-LEAK"):\n'
        '    return token\n', encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(proj))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    from keymd.engine import config
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    index.build(verbose=False)

    r = _client().get("/api/summary", params={"path": os.path.join("app", "conf.py")})
    body = r.text
    assert "sk-ant-supersecret-DO-NOT-LEAK" not in body   # never leaks the value
    assert "<str>" in body                                # shows the type instead


def test_cli_graph_dispatches_to_serve(monkeypatch, env_proj):
    # `keymd graph` ensures an index then calls graph_server.serve(host, port, watch).
    called = {}

    def fake_serve(host="127.0.0.1", port=None, *, watch=True):
        called["host"], called["port"], called["watch"] = host, port, watch

    monkeypatch.setattr(graph_server, "serve", fake_serve)
    from keymd import cli
    rc = cli.main(["graph", "--port", "9999"])
    assert rc == 0
    assert called == {"host": "127.0.0.1", "port": 9999, "watch": True}


def test_cli_graph_no_watch_flag(monkeypatch, env_proj):
    called = {}

    def fake_serve(host="127.0.0.1", port=None, *, watch=True):
        called["watch"] = watch

    monkeypatch.setattr(graph_server, "serve", fake_serve)
    from keymd import cli
    rc = cli.main(["graph", "--no-watch"])
    assert rc == 0
    assert called["watch"] is False


def test_api_summary_includes_summary_lead(monkeypatch, tmp_path):
    import os
    import keymd.engine.parsers.python  # noqa: F401
    proj = tmp_path / "proj"
    (proj / "pkg").mkdir(parents=True)
    (proj / "pkg" / "mod.py").write_text(
        '"""Walk sources and store symbols."""\ndef go(): return 1\n', encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(proj))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    from keymd.engine import config, index
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    index.build(verbose=False)
    r = _client().get("/api/summary", params={"path": os.path.join("pkg", "mod.py")})
    assert "summary: Walk sources and store symbols." in r.json()["summary"]


def test_api_symbol_returns_detail(env_proj):
    import os
    index.build(verbose=False)
    r = _client().get("/api/symbol", params={"path": os.path.join("pkg", "pipeline.py"), "name": "run"})
    assert r.status_code == 200
    j = r.json()
    assert j["name"] == "run" and j["signature"].startswith("def run(")
    assert any(c["name"] == "parse_header" for c in j["callees"])


def test_api_symbol_missing_name_400(env_proj):
    index.build(verbose=False)
    r = _client().get("/api/symbol", params={"path": "pkg/pipeline.py"})
    assert r.status_code == 400


def test_api_symbol_refuses_outside_root(env_proj):
    index.build(verbose=False)
    r = _client().get("/api/symbol", params={"path": "../../../etc/passwd", "name": "x"})
    assert r.status_code == 400
    assert "callees" not in r.json()
