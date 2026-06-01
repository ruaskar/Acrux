"""graph_server.py — localhost server for `keymd graph`.

A small Starlette app (mirrors proxy/server.py) that serves an interactive
force-directed call-graph of the indexed repo. Three concerns:
  GET /                  → the vendored HTML shell (keymd/assets/graph.html)
  GET /d3.v7.min.js      → the vendored D3 bundle (same-origin, no CDN)
  GET /api/graph         → whole topology (one cheap query.graph_data() read)
  GET /api/summary?path= → that file's .key.md summary, lazily (path-confined)

Security: summaries come from engine.summary → render_keymd, which already
renders string VALUES as <str> (incl. the PR #32 annotation fix), so no secret
value reaches the browser. /api/summary canonicalizes + confines the path to the
project root (confused-deputy guard), and the loopback bind restricts the Host
header (DNS-rebinding guard) exactly as proxy/server.py does.

The server binds a free socket BEFORE handing it to uvicorn (Server.run(sockets=
[sock])), so there is no close-then-rebind race and two `keymd graph` invocations
never collide.
"""
from __future__ import annotations

import os
import socket
from importlib.resources import files

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from keymd.engine import config, query
from keymd.engine.refresh import _confined
from keymd.proxy import engine

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _asset(name: str) -> str:
    """Read a packaged asset (works in source tree, wheel, and PyApp binary)."""
    return files("keymd").joinpath("assets", name).read_text(encoding="utf-8")


def _free_port(preferred: int = 8788, host: str = "127.0.0.1") -> tuple[socket.socket, int]:
    """Bind and return (socket, port). Try `preferred`; if it is busy (OSError),
    rebind to port 0 so the OS assigns any free port. The socket is returned
    already bound — hand it straight to uvicorn (no close-then-rebind gap)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, preferred))
    except OSError:
        s.bind((host, 0))
    return s, s.getsockname()[1]


def build_graph_app(*, allowed_hosts: list[str] | None = None) -> Starlette:
    async def index_route(request: Request) -> Response:
        return Response(_asset("graph.html"), media_type="text/html")

    async def d3_route(request: Request) -> Response:
        return Response(_asset("d3.v7.min.js"),
                        media_type="application/javascript")

    async def graph_route(request: Request) -> Response:
        return JSONResponse(query.graph_data())

    async def summary_route(request: Request) -> Response:
        rel = request.query_params.get("path", "")
        if not rel:
            return JSONResponse({"error": "missing path"}, status_code=400)
        abspath = engine.canon(os.path.join(str(config.project_root()), rel))
        if not _confined(abspath):          # confused-deputy guard: never read outside root
            return JSONResponse({"error": "path outside project root"}, status_code=400)
        return JSONResponse({"path": rel,
                             "summary": engine.summary(abspath) or "(no summary indexed)"})

    middleware = ([Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)]
                  if allowed_hosts else [])
    return Starlette(middleware=middleware, routes=[
        Route("/", index_route, methods=["GET"]),
        Route("/d3.v7.min.js", d3_route, methods=["GET"]),
        Route("/api/graph", graph_route, methods=["GET"]),
        Route("/api/summary", summary_route, methods=["GET"]),
    ])


def serve(host: str = "127.0.0.1", port: int | None = None, *, watch: bool = True) -> None:
    """Spawn the graph server, open the browser, and block on uvicorn.

    port is None → auto free-port discovery (preferred 8788 → OS fallback).
    port is an int → bind exactly that port; if busy, fail with a clear message
    (the user named that port, so don't silently move it).
    watch → auto-refresh the index on file edits + new files (bundled watcher)."""
    import webbrowser

    import uvicorn

    if port is None:
        sock, actual = _free_port(host=host)
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
        except OSError:
            sock.close()
            raise SystemExit(f"error: port {port} is in use — omit --port for an "
                             "auto-chosen free port, or pick another.")
        actual = port

    allowed = (["localhost", "127.0.0.1", "::1"] if host in _LOOPBACK else ["*"])
    url = f"http://{host}:{actual}"
    print(f"keymd graph on {url}")
    if watch:
        from keymd.proxy.live import spawn_watcher
        if spawn_watcher(str(config.project_root())) is None:
            print("(live refresh off — `pip install keymd[watch]` to auto-update on edits)")
        else:
            print("live refresh on — edits + new files re-index automatically")
    webbrowser.open(url)
    cfg = uvicorn.Config(build_graph_app(allowed_hosts=allowed), log_level="warning")
    uvicorn.Server(cfg).run(sockets=[sock])
