"""onboarding.py — the regular-user commands: up, run, init, doctor.

One-liner UX: `keymd run -- <agent>` (build+serve+inject base-url env+exec the
agent) and `keymd up` (zero-config build+serve+wiring hint). Resolution
precedence per setting: flag > env > keymd.toml > default. No secrets here — API
keys ride on the caller's request headers, which the proxy forwards untouched.
"""
from __future__ import annotations

import os
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
    """Parent env + injected base-URLs so an env-respecting agent is auto-wired.
    Set all three (the single proxy serves both wire formats) — harmless extras."""
    b = _base(host, port)
    env = dict(parent)
    env["ANTHROPIC_BASE_URL"] = b
    env["OPENAI_BASE_URL"] = f"{b}/v1"
    env["OPENAI_API_BASE"] = f"{b}/v1"
    return env


def wiring_hint(host: str, port: int) -> str:
    b = _base(host, port)
    return ("Point your agent at keymd (one of):\n"
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


def _announce_upstream(r: Resolved) -> None:
    # --upstream binds to ONE wire (the resolved --wire, default openai). Surface
    # it so a Claude Code (Anthropic-wire) user who forgot --wire anthropic sees
    # the binding instead of silently routing to the public Anthropic API.
    if r.upstream:
        print(f"upstream override → {r.wire} wire: {r.upstream}  "
              f"(pass --wire {'anthropic' if r.wire == 'openai' else 'openai'} "
              "to bind the other wire)")


def up(*, root=None, rebuild=False, flag_host=None, flag_port=None,
       flag_threshold=None, flag_wire=None, flag_upstream=None) -> int:
    r = resolve(root=root, flag_host=flag_host, flag_port=flag_port,
                flag_threshold=flag_threshold, flag_wire=flag_wire,
                flag_upstream=flag_upstream)
    _ensure_index(rebuild)
    print(f"keymd proxy on {_base(r.host, r.port)} (threshold={r.threshold} loc)")
    _announce_upstream(r)
    print(wiring_hint(r.host, r.port))
    from keymd.proxy import server
    server.serve(**_serve_kwargs(r))
    return 0


def _start_proxy(r: Resolved):
    """Start the proxy in a background daemon thread; return the uvicorn Server."""
    import uvicorn
    from keymd.proxy import server
    app = server.build_app(threshold=r.threshold, **{
        "upstream": r.upstream if r.wire == "anthropic" else None,
        "openai_base": r.upstream if r.wire == "openai" else None})
    cfg = uvicorn.Config(app, host=r.host, port=r.port, log_level="warning")
    srv = uvicorn.Server(cfg)
    srv.install_signal_handlers = lambda: None  # not the main thread
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
    _announce_upstream(r)
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

# Embedded so it ships with the installed package (repo-root templates/ is not packaged).
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
    print(f"indexed: {res.get('symbols', '?')} symbols across "
          f"{res.get('files', '?')} files")
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
    print("\nNext: `keymd run -- <your agent>`  or  `keymd up`")
    return 0


def _check(label: str, ok: bool, hint: str = "") -> bool:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}" + (f"  → {hint}" if (not ok and hint) else ""))
    return ok


def doctor(*, wire: bool = False, net: bool = False) -> int:
    import importlib.util as iu
    import shutil

    from keymd.engine import query

    hard_ok = True
    print("keymd doctor:")
    # 1 — index built (hard). stats() raises SystemExit when the DB is absent
    # (a BaseException, so it must be named explicitly alongside Exception).
    try:
        files = query.stats().get("files", 0)
    except (Exception, SystemExit):
        files = 0
    hard_ok &= _check(f"index built ({files} files)", files > 0,
                      "run `keymd build` (or `keymd up`)")
    # 2 — config parseable (hard; absent is OK)
    try:
        settings.load(); cfg_ok, cfg_hint = True, ""
    except ValueError as e:
        cfg_ok, cfg_hint = False, str(e)
    hard_ok &= _check("keymd.toml parseable (or absent)", cfg_ok, cfg_hint)
    # 3 — entry point on PATH (soft)
    _check("keymd on PATH", shutil.which("keymd") is not None,
           "use `python -m keymd ...` instead")
    # 4 — proxy extras (hard)
    extras = all(iu.find_spec(m) for m in ("httpx", "starlette", "uvicorn"))
    hard_ok &= _check("proxy extras installed", extras,
                      "pip install 'keymd[proxy]'")
    # 5 — gate + SSE self-check (opt-in, hard if requested)
    if wire and extras:
        try:
            from keymd.proxy import selfcheck
            res = selfcheck.run_inprocess()
            hard_ok &= _check("gate + SSE self-check", res["ok"], res.get("detail", ""))
        except Exception as e:  # pragma: no cover - defensive
            hard_ok &= _check("gate + SSE self-check", False, str(e))
    # 6 — upstream reachability (opt-in, warn-only)
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


def _ide_entries(host: str, port: int) -> dict:
    b = f"http://{host}:{port}"
    return {
        "claude-code": ("Anthropic wire",
            f'~/.claude/settings.json → "env": {{"ANTHROPIC_BASE_URL": "{b}"}}  '
            "(CLI + VS Code + JetBrains; restart after). keymd serves /v1/messages "
            "AND /v1/messages/count_tokens."),
        "codex": ("OpenAI wire",
            f'~/.codex/config.toml → a NAMED provider (not the built-in "openai") with '
            f'base_url="{b}/v1", env_key="OPENAI_API_KEY", wire_api="chat" OR "responses" '
            f"(both supported). Quick one-off: export OPENAI_BASE_URL={b}/v1"),
        "cline": ("OpenAI wire",
            f"Settings → API Provider = 'OpenAI Compatible' → Base URL = {b}/v1"),
        "continue": ("OpenAI wire",
            f"config.yaml → provider: openai, apiBase: {b}/v1"),
        "cursor": ("OpenAI wire",
            f"Settings → Override OpenAI Base URL = {b}/v1"),
        "roo": ("OpenAI wire",
            f"Settings → API Provider 'OpenAI Compatible' → Base URL = {b}/v1 (same as Cursor)"),
        "aider": ("OpenAI wire",
            f"export OPENAI_API_BASE={b}/v1  (or OPENAI_BASE_URL; or set in .aider.conf.yml)"),
        "openclaw": ("OpenAI wire",
            f"models.providers.<id>.baseUrl = {b}/v1  (OpenAI-Chat default)"),
        "hermes": ("OpenAI or Anthropic wire",
            f"config.yaml → provider: custom, base_url = {b} (Anthropic) or {b}/v1 "
            "(OpenAI). It forces streaming — keymd's synthesized SSE handles it."),
    }


def ide(tool: str | None = None) -> int:
    """Print exact wiring to point an IDE/framework at keymd (attach mode)."""
    r = resolve()
    entries = _ide_entries(r.host, r.port)
    print(f"keymd proxy base: http://{r.host}:{r.port}  "
          "(start it with `keymd up`; leave it running in a spare terminal)\n")
    if tool:
        key = tool.lower()
        if key not in entries:
            print(f"unknown tool '{tool}'. Known: {', '.join(entries)}")
            return 1
        wire, how = entries[key]
        print(f"# {key}  [{wire}]\n  {how}")
    else:
        for key, (wire, how) in entries.items():
            print(f"# {key}  [{wire}]\n  {how}\n")
        print("keymd routes by WIRE FORMAT (OpenAI vs Anthropic), not by model — any "
              "model behind an OpenAI/Anthropic-compatible endpoint (GPT, Claude, Hermes, "
              "Qwen, Llama via vLLM / Ollama / LM Studio / LiteLLM) works.")
    return 0
