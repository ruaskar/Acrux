from starlette.testclient import TestClient

from keymd.proxy import server


def test_dns_rebinding_host_guard_rejects_foreign_host():
    # On a loopback bind, a request whose Host header isn't localhost (a browser
    # DNS-rebinding attempt) is rejected before reaching any route.
    app = server.build_app(allowed_hosts=["localhost", "127.0.0.1"])
    r = TestClient(app).post("/v1/chat/completions", json={"messages": []},
                             headers={"host": "evil.example.com"})
    assert r.status_code == 400


def test_localhost_host_passes_the_guard():
    # A localhost Host clears the guard (it then reaches the route; we only assert
    # it was NOT blocked by the host check).
    app = server.build_app(allowed_hosts=["localhost", "127.0.0.1"])
    r = TestClient(app).post("/nope", headers={"host": "127.0.0.1:8787"})
    assert r.status_code == 404            # routing, not a 400 host block


def test_no_guard_without_allowed_hosts():
    # build_app() without allowed_hosts imposes no Host restriction (back-compat;
    # serve() wires the guard only for a loopback bind).
    app = server.build_app()
    r = TestClient(app).post("/nope", headers={"host": "evil.example.com"})
    assert r.status_code == 404
