# keymd Regular-User Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a regular user run one terminal command (`keymd run -- <agent>` or `keymd up`) and get the token-saving proxy fully wired, with persistent config, a verifier, and publish-ready packaging.

**Architecture:** A pure `settings.py` loader (`keymd.toml` via stdlib `tomllib`) feeds a precedence chain (flag>env>toml>default). `server.py` resolves the upstream base at call-time (killing the import-time footgun) and accepts explicit bases. A new `onboarding.py` holds the `up`/`run`/`init`/`doctor` command bodies; `cli.py` wires them. A shared `proxy/selfcheck.py` powers `doctor --wire` and de-dups `scripts/validate_sse.py`. `pyproject.toml` becomes publish-ready behind a do-not-upload guard.

**Tech Stack:** Python 3.11 (stdlib `tomllib`, `argparse`, `subprocess`, `shutil`, `threading`), Starlette/uvicorn/httpx (proxy extra), pytest.

**Repo conventions:** No `.key.md` sidecars for this repo's own source; tests carry none. Match that. Frequent commits, one per task.

---

### Task 1: `settings.py` — keymd.toml loader

**Files:**
- Create: `src/keymd/engine/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings.py
import pytest
from pathlib import Path
from keymd.engine import settings


def test_missing_file_returns_defaults(tmp_path):
    s = settings.load(root=tmp_path)
    assert s.threshold == 400 and s.host == "127.0.0.1" and s.port == 8787
    assert s.wire == "openai" and s.upstream is None


def test_reads_values(tmp_path):
    (tmp_path / "keymd.toml").write_text(
        '[keymd]\nthreshold = 50\n[keymd.serve]\n'
        'host = "0.0.0.0"\nport = 9000\nwire = "anthropic"\n'
        'upstream = "https://x.test"\n', encoding="utf-8")
    s = settings.load(root=tmp_path)
    assert (s.threshold, s.host, s.port, s.wire, s.upstream) == (
        50, "0.0.0.0", 9000, "anthropic", "https://x.test")


def test_malformed_raises_clear_error(tmp_path):
    (tmp_path / "keymd.toml").write_text("not = = valid", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        settings.load(root=tmp_path)
    assert "keymd.toml" in str(e.value)
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_settings.py -q`
Expected: FAIL (`ModuleNotFoundError: keymd.engine.settings`)

- [ ] **Step 3: Implement**

```python
# src/keymd/engine/settings.py
"""settings.py — optional keymd.toml project config (stdlib tomllib).

Pure: path in → Settings out. Reads NO env and NO flags; callers resolve the
precedence chain (flag > env > keymd.toml > default). Contains no secrets — API
keys ride on request headers, never this file.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from keymd.engine import config


@dataclass
class Settings:
    threshold: int = 400
    host: str = "127.0.0.1"
    port: int = 8787
    wire: str = "openai"
    upstream: str | None = None


def config_path(root: Path | None = None) -> Path:
    return (root or config.project_root()) / "keymd.toml"


def load(root: Path | None = None) -> Settings:
    p = config_path(root)
    if not p.exists():
        return Settings()
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ValueError(f"keymd.toml at {p} is malformed: {e}") from e
    km = data.get("keymd", {}) or {}
    srv = km.get("serve", {}) or {}
    return Settings(
        threshold=int(km.get("threshold", 400)),
        host=str(srv.get("host", "127.0.0.1")),
        port=int(srv.get("port", 8787)),
        wire=str(srv.get("wire", "openai")),
        upstream=srv.get("upstream"),
    )
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_settings.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/keymd/engine/settings.py tests/test_settings.py
git commit -m "feat(settings): keymd.toml loader (tomllib, pure, no secrets)"
```

---

### Task 2: Kill the env-before-import footgun in `server.py`

**Files:**
- Modify: `src/keymd/proxy/server.py:30-53,119-156`
- Modify: `src/keymd/cli.py:87-91` (serve print uses resolved base; drop removed globals)
- Test: `tests/test_proxy_upstream_resolve.py`

- [ ] **Step 1: Write the failing regression test**

```python
# tests/test_proxy_upstream_resolve.py
import asyncio
import pytest
pytest.importorskip("starlette")
from keymd.proxy import server


def test_openai_base_resolved_at_call_time(monkeypatch):
    captured = {}
    async def fake_post(url, body, headers):
        captured["url"] = url; return {}
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
        captured["url"] = url; return {}
    monkeypatch.setattr(server, "_post", fake_post)
    monkeypatch.delenv("KEYMD_UPSTREAM_BASE", raising=False)
    asyncio.run(server.forward_upstream({}, {}))
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    asyncio.run(server.forward_upstream({}, {}, "http://a:1"))
    assert captured["url"] == "http://a:1/v1/messages"
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_proxy_upstream_resolve.py -q`
Expected: FAIL (`forward_openai` takes 2 positional args; env not read at call-time)

- [ ] **Step 3: Edit `server.py`** — replace lines 30–53 and 119–156.

Replace the globals + forwarders (lines 30–53) with:

```python
_FORWARD_HEADERS = ("x-api-key", "authorization", "anthropic-version",
                    "anthropic-beta", "content-type", "openai-organization")
_DEFAULT_ANTHROPIC = "https://api.anthropic.com"
_DEFAULT_OPENAI = "https://api.openai.com"


async def _post(url: str, body: dict, headers: dict) -> dict:
    fwd = {k: v for k, v in headers.items() if k.lower() in _FORWARD_HEADERS}
    payload = {**body, "stream": False}  # internal calls are always non-streamed
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    async with httpx.AsyncClient(transport=transport, timeout=600.0) as client:
        r = await client.post(url, json=payload, headers=fwd)
        return r.json()


def _anthropic_base(override: str | None) -> str:
    return override or os.environ.get("KEYMD_UPSTREAM_BASE", _DEFAULT_ANTHROPIC)


def _openai_base(override: str | None) -> str:
    return override or os.environ.get("KEYMD_OPENAI_BASE", _DEFAULT_OPENAI)


async def forward_upstream(body: dict, headers: dict, base: str | None = None) -> dict:
    return await _post(f"{_anthropic_base(base)}/v1/messages", body, headers)


async def forward_openai(body: dict, headers: dict, base: str | None = None) -> dict:
    return await _post(f"{_openai_base(base)}/v1/chat/completions", body, headers)
```

Replace `build_app`/`serve` (lines 119–156) with:

```python
def build_app(threshold: int = 400, *, upstream: str | None = None,
              openai_base: str | None = None) -> Starlette:
    async def anthropic_route(request: Request):
        body = await request.json(); hdrs = dict(request.headers)
        wants_stream = bool(body.get("stream"))

        async def up(b: dict) -> dict:
            return (await forward_upstream(b, hdrs) if upstream is None
                    else await forward_upstream(b, hdrs, upstream))

        result = await complete(body, AnthropicAdapter(), up, threshold=threshold)
        if wants_stream:
            return StreamingResponse(_anthropic_sse(result), media_type="text/event-stream")
        return JSONResponse(result)

    async def openai_route(request: Request):
        body = await request.json(); hdrs = dict(request.headers)
        wants_stream = bool(body.get("stream"))

        async def up(b: dict) -> dict:
            return (await forward_openai(b, hdrs) if openai_base is None
                    else await forward_openai(b, hdrs, openai_base))

        result = await complete(body, OpenAIAdapter(), up, threshold=threshold)
        if wants_stream:
            return StreamingResponse(_openai_sse(result), media_type="text/event-stream")
        return JSONResponse(result)

    return Starlette(routes=[
        Route("/v1/messages", anthropic_route, methods=["POST"]),
        Route("/v1/chat/completions", openai_route, methods=["POST"]),
    ])


def serve(host: str = "127.0.0.1", port: int = 8787, threshold: int = 400,
          *, upstream: str | None = None, openai_base: str | None = None) -> None:
    import uvicorn
    uvicorn.run(build_app(threshold=threshold, upstream=upstream, openai_base=openai_base),
                host=host, port=port)
```

- [ ] **Step 4: Fix the `cli.py` serve print** (line ~90 referenced removed `server.UPSTREAM_BASE`). Defer the full serve-flag wiring to Task 5; for now just make it import-safe:

```python
    elif a.cmd == "serve":
        from keymd.proxy import server
        print(f"keymd proxy on http://{a.host}:{a.port} (threshold={a.threshold} loc)")
        server.serve(host=a.host, port=a.port, threshold=a.threshold)
```

- [ ] **Step 5: Run regression + existing proxy tests**

Run: `python -m pytest tests/test_proxy_upstream_resolve.py tests/test_proxy_streaming.py tests/test_proxy_server_openai_smoke.py tests/test_proxy_server_smoke.py tests/test_proxy_sse_openai_sdk.py -q`
Expected: PASS (existing 2-arg monkeypatched fakes still called with 2 args)

- [ ] **Step 6: Commit**

```bash
git add src/keymd/proxy/server.py src/keymd/cli.py tests/test_proxy_upstream_resolve.py
git commit -m "fix(proxy): resolve upstream base at call-time; kill env-before-import footgun"
```

---

### Task 3: `onboarding.py` — env-resolution helper + `up`

**Files:**
- Create: `src/keymd/onboarding.py`
- Test: `tests/test_onboarding.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_onboarding.py
import os
from pathlib import Path
import pytest
from keymd import onboarding as ob


def test_resolve_precedence_flag_over_env_over_toml(tmp_path, monkeypatch):
    (tmp_path / "keymd.toml").write_text(
        '[keymd]\nthreshold = 50\n[keymd.serve]\nport = 9000\n', encoding="utf-8")
    monkeypatch.setenv("KEYMD_PORT", "7000")
    r = ob.resolve(root=tmp_path, flag_port=1234, flag_threshold=None)
    assert r.port == 1234            # flag wins
    assert r.threshold == 50         # falls through to toml
    r2 = ob.resolve(root=tmp_path, flag_port=None, flag_threshold=None)
    assert r2.port == 7000           # env beats toml


def test_inject_env_sets_all_base_urls():
    env = ob.child_env({"PATH": "x"}, host="127.0.0.1", port=8787)
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8787"
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:8787/v1"
    assert env["OPENAI_API_BASE"] == "http://127.0.0.1:8787/v1"
    assert env["PATH"] == "x"        # parent env preserved


def test_wiring_lines_mentions_both():
    text = ob.wiring_hint("127.0.0.1", 8787)
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:8787" in text
    assert "OPENAI_BASE_URL=http://127.0.0.1:8787/v1" in text
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_onboarding.py -q` → FAIL (no module)

- [ ] **Step 3: Implement resolve/child_env/wiring_hint + `up`**

```python
# src/keymd/onboarding.py
"""onboarding.py — the regular-user commands: up, run, init, doctor.

One-liner UX: `keymd run -- <agent>` (wrap+exec) and `keymd up` (zero-config
serve). Resolution precedence per setting: flag > env > keymd.toml > default.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from keymd.engine import config, index, settings


@dataclass
class Resolved:
    host: str
    port: int
    threshold: int
    wire: str
    upstream: str | None


def _env_int(name: str) -> int | None:
    v = os.environ.get(name)
    return int(v) if v and v.isdigit() else None


def resolve(*, root: Path | None = None, flag_host=None, flag_port=None,
            flag_threshold=None, flag_wire=None, flag_upstream=None) -> Resolved:
    s = settings.load(root)
    return Resolved(
        host=flag_host or os.environ.get("KEYMD_HOST") or s.host,
        port=flag_port or _env_int("KEYMD_PORT") or s.port,
        threshold=flag_threshold if flag_threshold is not None else s.threshold,
        wire=flag_wire or os.environ.get("KEYMD_WIRE") or s.wire,
        upstream=flag_upstream or os.environ.get("KEYMD_UPSTREAM") or s.upstream,
    )


def _base(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def child_env(parent: dict, host: str, port: int) -> dict:
    b = _base(host, port)
    env = dict(parent)
    env["ANTHROPIC_BASE_URL"] = b
    env["OPENAI_BASE_URL"] = f"{b}/v1"
    env["OPENAI_API_BASE"] = f"{b}/v1"
    return env


def wiring_hint(host: str, port: int) -> str:
    b = _base(host, port)
    return (f"Point your agent at keymd (one of):\n"
            f"  export ANTHROPIC_BASE_URL={b}\n"
            f"  export OPENAI_BASE_URL={b}/v1")


def _ensure_index(rebuild: bool) -> None:
    if rebuild or not config.index_path().exists():
        index.build(verbose=False)


def _serve_kwargs(r: Resolved) -> dict:
    ob = r.upstream if r.wire == "openai" else None
    ab = r.upstream if r.wire == "anthropic" else None
    return {"host": r.host, "port": r.port, "threshold": r.threshold,
            "upstream": ab, "openai_base": ob}


def up(*, root=None, rebuild=False, flag_host=None, flag_port=None,
       flag_threshold=None, flag_wire=None, flag_upstream=None) -> int:
    r = resolve(root=root, flag_host=flag_host, flag_port=flag_port,
                flag_threshold=flag_threshold, flag_wire=flag_wire,
                flag_upstream=flag_upstream)
    _ensure_index(rebuild)
    print(f"keymd proxy on {_base(r.host, r.port)} (threshold={r.threshold} loc)")
    print(wiring_hint(r.host, r.port))
    from keymd.proxy import server
    server.serve(**_serve_kwargs(r))
    return 0
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_onboarding.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/keymd/onboarding.py tests/test_onboarding.py
git commit -m "feat(onboarding): resolve precedence + child_env + wiring hint + keymd up"
```

---

### Task 4: `keymd run -- <agent>` (wrap + exec)

**Files:**
- Modify: `src/keymd/onboarding.py` (add `run`)
- Test: `tests/test_onboarding.py` (add run tests)

- [ ] **Step 1: Write failing tests**

```python
# add to tests/test_onboarding.py
def test_run_invokes_child_with_injected_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    seen = {}
    class FakeServer:
        started = True
        should_exit = False
        def run(self): 
            while not self.should_exit: 
                import time; time.sleep(0.01)
    monkeypatch.setattr(ob, "_start_proxy", lambda r: FakeServer())
    def fake_run(cmd, env=None):
        seen["cmd"] = cmd; seen["env"] = env
        class R: returncode = 0
        return R()
    monkeypatch.setattr(ob.subprocess, "run", fake_run)
    rc = ob.run_agent(["echo", "hi"], root=tmp_path, flag_port=8799)
    assert rc == 0
    assert seen["cmd"] == ["echo", "hi"]
    assert seen["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8799"


def test_run_empty_command_errors():
    with pytest.raises(SystemExit):
        ob.run_agent([], root=None)


def test_run_command_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ob, "_start_proxy", lambda r: _NoopServer())
    def boom(cmd, env=None): raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(ob.subprocess, "run", boom)
    rc = ob.run_agent(["nope-xyz"], root=tmp_path)
    assert rc != 0
```

(Add `class _NoopServer: started=True; should_exit=False;\n    def run(self):\n        import time;\n        while not self.should_exit: time.sleep(0.01)` near the top of the test module, or reuse FakeServer.)

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_onboarding.py -q` → FAIL (`run_agent`, `_start_proxy` missing)

- [ ] **Step 3: Implement `run_agent` + `_start_proxy`**

```python
# add to src/keymd/onboarding.py
def _start_proxy(r: "Resolved"):
    import uvicorn
    from keymd.proxy import server
    app = server.build_app(threshold=r.threshold, **{
        k: v for k, v in (("upstream", r.upstream if r.wire == "anthropic" else None),
                          ("openai_base", r.upstream if r.wire == "openai" else None))})
    cfg = uvicorn.Config(app, host=r.host, port=r.port, log_level="warning")
    srv = uvicorn.Server(cfg)
    srv.install_signal_handlers = lambda: None
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(200):
        if srv.started:
            return srv
        time.sleep(0.05)
    raise RuntimeError(f"keymd proxy failed to start on :{r.port}")


def run_agent(cmd: list[str], *, root=None, rebuild=False, flag_host=None,
              flag_port=None, flag_threshold=None, flag_wire=None,
              flag_upstream=None) -> int:
    if not cmd:
        raise SystemExit("keymd run: missing command after `--` "
                         "(e.g. `keymd run -- claude`)")
    r = resolve(root=root, flag_host=flag_host, flag_port=flag_port,
                flag_threshold=flag_threshold, flag_wire=flag_wire,
                flag_upstream=flag_upstream)
    _ensure_index(rebuild)
    srv = _start_proxy(r)
    print(f"keymd proxy on {_base(r.host, r.port)} → launching: {' '.join(cmd)}")
    env = child_env(os.environ, r.host, r.port)
    try:
        proc = subprocess.run(cmd, env=env)
        return proc.returncode
    except FileNotFoundError:
        print(f"keymd run: command not found: {cmd[0]}")
        return 127
    except KeyboardInterrupt:
        return 130
    finally:
        srv.should_exit = True
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_onboarding.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/keymd/onboarding.py tests/test_onboarding.py
git commit -m "feat(onboarding): keymd run -- <agent> (build+serve+inject env+exec)"
```

---

### Task 5: Wire CLI subcommands `up`/`run`/`serve --upstream/--wire`

**Files:**
- Modify: `src/keymd/cli.py`
- Test: `tests/test_cli.py` (add smoke for `up`/`run` arg parsing)

- [ ] **Step 1: Write failing tests**

```python
# add to tests/test_cli.py
def test_cli_run_parses_double_dash(monkeypatch, tmp_path):
    import keymd.cli as cli
    from keymd import onboarding
    seen = {}
    monkeypatch.setattr(onboarding, "run_agent",
                        lambda cmd, **kw: seen.setdefault("cmd", cmd) or 0)
    rc = cli.main(["run", "--port", "8799", "--", "claude", "--flag"])
    assert rc == 0 and seen["cmd"] == ["claude", "--flag"]


def test_cli_up_calls_onboarding(monkeypatch):
    import keymd.cli as cli
    from keymd import onboarding
    called = {}
    monkeypatch.setattr(onboarding, "up", lambda **kw: called.setdefault("ok", True) or 0)
    assert cli.main(["up", "--port", "9001"]) == 0 and called["ok"]
```

- [ ] **Step 2: Run, verify failure** → FAIL (`run`/`up` not subcommands)

- [ ] **Step 3: Edit `cli.py`** — add parsers + dispatch. `run` uses `argparse.REMAINDER` after `--`.

```python
    # parsers
    up = sp.add_parser("up")
    for f in (up,):
        f.add_argument("--host"); f.add_argument("--port", type=int)
        f.add_argument("--threshold", type=int); f.add_argument("--wire",
            choices=["openai", "anthropic"]); f.add_argument("--upstream")
        f.add_argument("--rebuild", action="store_true")
    rn = sp.add_parser("run")
    rn.add_argument("--host"); rn.add_argument("--port", type=int)
    rn.add_argument("--threshold", type=int)
    rn.add_argument("--wire", choices=["openai", "anthropic"])
    rn.add_argument("--upstream"); rn.add_argument("--rebuild", action="store_true")
    rn.add_argument("cmd", nargs=argparse.REMAINDER)  # everything after `--`
    ini = sp.add_parser("init"); ini.add_argument("path", nargs="?")
    ini.add_argument("--force", action="store_true")
    ini.add_argument("--write-agents", action="store_true")
    doc = sp.add_parser("doctor"); doc.add_argument("--wire", action="store_true")
    doc.add_argument("--net", action="store_true")
```

```python
    # dispatch
    elif a.cmd == "up":
        from keymd import onboarding
        return onboarding.up(rebuild=a.rebuild, flag_host=a.host, flag_port=a.port,
                             flag_threshold=a.threshold, flag_wire=a.wire,
                             flag_upstream=a.upstream)
    elif a.cmd == "run":
        from keymd import onboarding
        cmd = a.cmd_[1:] if (a.cmd_ and a.cmd_[0] == "--") else a.cmd_  # see note
        return onboarding.run_agent(cmd, rebuild=a.rebuild, flag_host=a.host,
                                    flag_port=a.port, flag_threshold=a.threshold,
                                    flag_wire=a.wire, flag_upstream=a.upstream)
    elif a.cmd == "init":
        from keymd import onboarding
        return onboarding.init(path=a.path, force=a.force, write_agents=a.write_agents)
    elif a.cmd == "doctor":
        from keymd import onboarding
        return onboarding.doctor(wire=a.wire, net=a.net)
```

> **Note on REMAINDER:** `argparse.REMAINDER` captures the literal `--` as the first
> element. Store the run positional in a distinct dest to avoid clashing with the
> `dest="cmd"` subparser attribute: change `rn.add_argument("cmd", nargs=REMAINDER)` to
> `rn.add_argument("agent", nargs=argparse.REMAINDER)` and strip a leading `--`:
> `cmd = a.agent[1:] if a.agent and a.agent[0] == "--" else a.agent`. Update the test/impl to use `a.agent`.

- [ ] **Step 4: Run** `python -m pytest tests/test_cli.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/keymd/cli.py tests/test_cli.py
git commit -m "feat(cli): wire up/run/init/doctor subcommands"
```

---

### Task 6: `keymd init` (persist config + steering snippet)

**Files:**
- Modify: `src/keymd/onboarding.py` (add `init` + embedded snippet + `DEFAULT_TOML`)
- Test: `tests/test_onboarding.py` (add init tests)

- [ ] **Step 1: Write failing tests**

```python
def test_init_writes_toml_and_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m.py").write_text("y = 2\n", encoding="utf-8")
    assert ob.init(path=str(tmp_path)) == 0
    cfg = tmp_path / "keymd.toml"
    assert cfg.exists() and "[keymd.serve]" in cfg.read_text(encoding="utf-8")
    before = cfg.read_text(encoding="utf-8")
    ob.init(path=str(tmp_path))                 # no clobber
    assert cfg.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "already" in out.lower()


def test_init_write_agents_appends_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ob.init(path=str(tmp_path), write_agents=True)
    agents = tmp_path / "AGENTS.md"
    assert agents.exists() and "keymd steering snippet" in agents.read_text(encoding="utf-8")
    n1 = agents.read_text(encoding="utf-8").count("keymd steering snippet")
    ob.init(path=str(tmp_path), force=True, write_agents=True)
    assert agents.read_text(encoding="utf-8").count("keymd steering snippet") == n1  # not duplicated
```

- [ ] **Step 2: Run, verify failure** → FAIL (`init` missing)

- [ ] **Step 3: Implement `init`**

```python
# add to src/keymd/onboarding.py
DEFAULT_TOML = (
    "# keymd.toml — committed; NO secrets (API keys ride on request headers)\n"
    "[keymd]\n"
    "threshold = 400          # gate files larger than this many loc\n\n"
    "[keymd.serve]\n"
    'host = "127.0.0.1"\n'
    "port = 8787\n"
    'wire = "openai"          # "openai" | "anthropic"\n'
    '# upstream = "https://api.openai.com"   # base URL only; never a key\n'
)

_AGENTS_SNIPPET = """<!-- keymd steering snippet -->

## Reading code efficiently (keymd)

Before reading a LARGE file in full, call `keymd_read(path)` for its compact
summary (API signatures, dependencies, callers). Use `keymd_impact(path)`,
`keymd_callers(symbol)`, `keymd_callees(path)`, and `keymd_search(text)` to
understand structure instead of grepping. Only call `keymd_read_full(path)`
when the summary is genuinely insufficient.
"""
_AGENTS_MARKER = "keymd steering snippet"


def init(*, path=None, force=False, write_agents=False) -> int:
    root = Path(path).resolve() if path else config.project_root()
    cfg = root / "keymd.toml"
    if cfg.exists() and not force:
        print(f"keymd.toml already exists at {cfg} (use --force to overwrite)")
    else:
        cfg.write_text(DEFAULT_TOML, encoding="utf-8")
        print(f"wrote {cfg}")
    res = index.build(verbose=False)
    print(f"indexed: {res.get('symbols', '?')} symbols across {res.get('files', '?')} files")
    if write_agents:
        agents = root / "AGENTS.md"
        existing = agents.read_text(encoding="utf-8") if agents.exists() else ""
        if _AGENTS_MARKER in existing:
            print(f"AGENTS.md already has keymd steering ({agents})")
        else:
            agents.write_text((existing + "\n" + _AGENTS_SNIPPET) if existing
                              else _AGENTS_SNIPPET, encoding="utf-8")
            print(f"appended keymd steering to {agents}")
    else:
        print("\n--- add to your agent's AGENTS.md / system prompt ---")
        print(_AGENTS_SNIPPET)
    print(f"\nNext: `keymd run -- <your agent>`  or  `keymd up`")
    return 0
```

> Verify `index.build()`'s return dict keys against `engine/index.py` before asserting
> exact key names; adjust the print/test to the real keys (`files`/`symbols` or similar).

- [ ] **Step 4: Run** → PASS

- [ ] **Step 5: Commit**

```bash
git add src/keymd/onboarding.py tests/test_onboarding.py
git commit -m "feat(onboarding): keymd init — persist keymd.toml + steering snippet"
```

---

### Task 7: `proxy/selfcheck.py` + `keymd doctor`

**Files:**
- Create: `src/keymd/proxy/selfcheck.py`
- Modify: `src/keymd/onboarding.py` (add `doctor`)
- Modify: `scripts/validate_sse.py` (import shared stub helpers)
- Test: `tests/test_selfcheck.py`, `tests/test_onboarding.py` (doctor)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_selfcheck.py
import pytest
pytest.importorskip("starlette"); pytest.importorskip("httpx")
from keymd.proxy import selfcheck


def test_selfcheck_inprocess_gate_fires():
    res = selfcheck.run_inprocess(threshold=10)
    assert res["ok"] is True
    assert res["gate_fired"] is True
    assert res["chunks"] >= 2
```

```python
# add to tests/test_onboarding.py
def test_doctor_reports_index_and_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / ".keymd" / "index.db"))
    from keymd.engine import config as c
    c.project_pkg_prefixes.cache_clear(); c._git_toplevel.cache_clear()
    (tmp_path / "z.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    rc = ob.doctor()
    out = capsys.readouterr().out
    assert "index" in out.lower()
    assert rc != 0  # index not built yet → hard fail
```

- [ ] **Step 2: Run, verify failure** → FAIL (modules/functions missing)

- [ ] **Step 3: Implement `selfcheck.py`** (in-process, no socket, no API)

```python
# src/keymd/proxy/selfcheck.py
"""selfcheck.py — in-process validation of the gate + synthesized-SSE path.

No socket, no API spend: a scripted local stub upstream + ASGITransport. Shared
by `keymd doctor --wire` and (its helpers) by scripts/validate_sse.py.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

MARKER = "⟪keymd-summary:"


def build_big_repo() -> tuple[Path, str]:
    tmp = Path(tempfile.mkdtemp(prefix="keymd_selfcheck_"))
    big = tmp / "big.py"
    big.write_text("\n".join(f"def fn_{i}(x):\n    return x + {i}\n"
                             for i in range(60)), encoding="utf-8")
    return tmp, str(big)


def stub_upstream(target: str, state: dict):
    """OpenAI-compatible scripted upstream: turn1 Read; turn2 report gate."""
    async def fake(body, headers, base=None):
        i = state["n"]; state["n"] += 1
        if i == 0:
            return {"id": "u1", "object": "chat.completion", "created": 1, "model": "stub",
                    "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                        "role": "assistant", "content": None, "tool_calls": [
                            {"id": "c1", "type": "function", "function": {
                                "name": "Read",
                                "arguments": json.dumps({"file_path": target})}}]}}]}
        saw = any(isinstance(m.get("content"), str) and MARKER in m["content"]
                  for m in body.get("messages", []) if m.get("role") == "tool")
        state["saw"] = saw
        return {"id": "u2", "object": "chat.completion", "created": 2, "model": "stub",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": "GATED" if saw else "NOGATE"}}]}
    return fake


def run_inprocess(threshold: int = 10) -> dict:
    import os
    from keymd.engine import index
    import keymd.engine.parsers.python  # noqa: F401
    from keymd.engine.config import canonical
    from keymd.proxy import server
    import httpx

    tmp, big = build_big_repo()
    os.environ["KEYMD_PROJECT_ROOT"] = str(tmp)
    os.environ["KEYMD_INDEX_PATH"] = str(tmp / ".keymd" / "index.db")
    from keymd.engine import config as c
    c.project_pkg_prefixes.cache_clear(); c._git_toplevel.cache_clear()
    index.build(verbose=False)
    target = canonical(big)
    state = {"n": 0, "saw": False}
    fake = stub_upstream(target, state)

    orig = server.forward_openai
    server.forward_openai = fake
    try:
        app = server.build_app(threshold=threshold)

        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://t") as cx:
                async with cx.stream("POST", "/v1/chat/completions",
                                     json={"model": "m", "stream": True,
                                           "messages": [{"role": "user", "content": "go"}]}) as r:
                    return [ln async for ln in r.aiter_lines()]
        lines = asyncio.run(go())
    finally:
        server.forward_openai = orig

    datas = [ln[6:] for ln in lines if ln.startswith("data: ")]
    content = "".join(json.loads(d)["choices"][0]["delta"].get("content", "")
                      for d in datas if d != "[DONE]")
    return {"ok": content == "GATED" and state["saw"] and state["n"] == 2,
            "gate_fired": state["saw"], "chunks": len(datas), "detail": content}
```

- [ ] **Step 4: Implement `doctor`** in `onboarding.py`

```python
# add to src/keymd/onboarding.py
def _check(label, ok, hint=""):
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}" + (f"  → {hint}" if (not ok and hint) else ""))
    return ok


def doctor(*, wire=False, net=False) -> int:
    from keymd.engine import query
    hard_ok = True
    print("keymd doctor:")
    # 1 index
    try:
        st = query.stats(); files = st.get("files", 0)
    except Exception:
        files = 0
    hard_ok &= _check(f"index built ({files} files)", files > 0,
                      "run `keymd build` (or `keymd up`)")
    # 2 config
    try:
        settings.load(); cfg_ok = True; cfg_hint = ""
    except ValueError as e:
        cfg_ok = False; cfg_hint = str(e)
    hard_ok &= _check("keymd.toml parseable (or absent)", cfg_ok, cfg_hint)
    # 3 PATH (soft)
    on_path = shutil.which("keymd") is not None
    _check("keymd on PATH", on_path, "use `python -m keymd ...` instead")
    # 4 proxy extras
    import importlib.util as u
    extras = all(u.find_spec(m) for m in ("httpx", "starlette", "uvicorn"))
    hard_ok &= _check("proxy extras installed", extras, "pip install 'keymd[proxy]'")
    # 5 wire (opt-in)
    if wire and extras:
        try:
            from keymd.proxy import selfcheck
            res = selfcheck.run_inprocess()
            hard_ok &= _check("gate + SSE self-check", res["ok"], res.get("detail", ""))
        except Exception as e:  # pragma: no cover
            hard_ok &= _check("gate + SSE self-check", False, str(e))
    # 6 net (opt-in, warn-only)
    if net:
        import socket
        r = resolve()
        host = (r.upstream or "https://api.openai.com").split("//")[-1].split("/")[0]
        try:
            socket.create_connection((host, 443), timeout=3).close(); reach = True
        except OSError:
            reach = False
        _check(f"upstream reachable ({host})", reach, "check network / upstream URL")
    return 0 if hard_ok else 1
```

- [ ] **Step 5: De-dup `scripts/validate_sse.py`** — import `build_big_repo` + `stub_upstream` from `keymd.proxy.selfcheck` instead of inlining them (keep its real-socket + sync-SDK driver). Re-run `python scripts/validate_sse.py` → `PASS`.

- [ ] **Step 6: Run** `python -m pytest tests/test_selfcheck.py tests/test_onboarding.py -q` → PASS

- [ ] **Step 7: Commit**

```bash
git add src/keymd/proxy/selfcheck.py src/keymd/onboarding.py scripts/validate_sse.py tests/test_selfcheck.py tests/test_onboarding.py
git commit -m "feat: proxy/selfcheck + keymd doctor; de-dup validate_sse"
```

---

### Task 8: `pyproject.toml` publish-readiness + README leads with run/up

**Files:**
- Modify: `pyproject.toml`, `README.md`

- [ ] **Step 1: Edit `pyproject.toml`** — add metadata + `all` extra + do-not-upload guard.

```toml
[project]
name = "keymd"
version = "0.1.0"
description = "Cross-framework token-saving enforcement layer: LLM-optimized .key.md sidecars + call-graph index + local enforcing proxy"
readme = "README.md"
requires-python = ">=3.11"
authors = [{ name = "ruaskar" }]
keywords = ["llm", "agents", "tokens", "proxy", "code-index", "tree-sitter"]
classifiers = [
    "Private :: Do Not Upload",
    "Programming Language :: Python :: 3.11",
    "Intended Audience :: Developers",
]
dependencies = []

[project.urls]
Repository = "https://github.com/ruaskar/keymd"

[project.optional-dependencies]
dev = ["pytest>=8"]
proxy = ["httpx>=0.27", "starlette>=0.37", "uvicorn>=0.30"]
watch = ["watchdog>=4"]
lang = ["tree-sitter>=0.25,<0.26", "tree-sitter-javascript>=0.23", "tree-sitter-typescript>=0.23"]
all = ["httpx>=0.27", "starlette>=0.37", "uvicorn>=0.30", "watchdog>=4",
       "tree-sitter>=0.25,<0.26", "tree-sitter-javascript>=0.23", "tree-sitter-typescript>=0.23"]
```

- [ ] **Step 2: Verify the build still resolves**

Run: `python -c "import tomllib,pathlib; tomllib.loads(pathlib.Path('pyproject.toml').read_text())" && pip install -e . -q`
Expected: no error.

- [ ] **Step 3: Edit `README.md`** — add a "Quickstart (one command)" section near the top:

````markdown
## Quickstart (one command)

```bash
pip install keymd[all]
cd your-project
keymd run -- claude        # build + serve + wire base-url + launch your agent through keymd
```

Config-file frameworks (e.g. OpenClaw): `keymd up` then point the framework's base_url at the printed URL.
Verify anytime: `keymd doctor --wire`.
````

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml README.md
git commit -m "chore: pyproject publish-readiness (do-not-upload guard) + README quickstart"
```

---

### Task 9: Full suite + push

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -q`
Expected: all green (prior 85 + new tests).

- [ ] **Step 2: Dogfood the real entrypoints** (per repo lesson — fixtures hide first-run bugs)

Run, in a throwaway dir:
```bash
python -m keymd init && python -m keymd doctor --wire
python -m keymd up --port 8790   # Ctrl-C after the wiring lines print
```
Expected: `init` writes config + indexes; `doctor --wire` all ✓; `up` prints wiring + serves.

- [ ] **Step 3: Push to origin**

```bash
git push origin master
```

---

## Self-Review (completed)

- **Spec coverage:** A→Task1, B→Task2, C(up)→Task3, D(run)→Task4, CLI→Task5, E(init)→Task6, F(selfcheck+doctor)→Task7, G(pyproject)→Task8, verify+push→Task9. All components mapped.
- **Placeholder scan:** two explicit "verify against real API" notes (REMAINDER dest, `index.build()` return keys) are deliberate guardrails, not placeholders — each names the exact check to run.
- **Type consistency:** `Resolved`/`Settings` field names consistent across tasks; `forward_*(body, headers, base=None)` signature consistent between Task 2 and selfcheck's `stub_upstream`. `_start_proxy` returns an object with `.started`/`.should_exit`/`.run` matching the Task-4 FakeServer.
