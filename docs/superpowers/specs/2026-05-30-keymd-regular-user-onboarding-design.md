# keymd Regular-User Onboarding — Design Spec

**Date:** 2026-05-30
**Status:** Approved (design); ready for implementation plan.

## Problem (first-principles)

A regular (non-power) user should run **one command in their terminal** and get the
keymd token-saving proxy **fully wired** in front of their agent — index built, proxy
running, base-URL wired, no env-ordering footguns. Today that path is ~6 manual steps
with three sharp edges.

The headline experience (what "wired" means):

```bash
pip install keymd[all]
cd my-project
keymd run -- claude          # or: keymd run -- aider / codex / any agent CLI
```

`keymd run` auto-builds the index, starts the proxy, injects the base-URL env vars for
the child, and execs the agent **through** the proxy — then tears the proxy down when the
agent exits. For frameworks that read their endpoint from a **config file** rather than
env (e.g. OpenClaw), `keymd up` is the zero-config fallback: it builds + serves + prints
the single line to point the framework at.

What already works (verified in code, do NOT rebuild):
- `engine/config.py` auto-detects the project root (`KEYMD_PROJECT_ROOT → git toplevel →
  cwd`) and reads env **at call-time**, so indexing already "just works" in a repo.
- `keymd build|serve|watch|guard|...` subcommands exist and are tested.

Verified friction (the real gaps this spec closes):
1. **env-before-import footgun** — `proxy/server.py` reads `KEYMD_UPSTREAM_BASE` /
   `KEYMD_OPENAI_BASE` as **module globals at import time**, and `serve` has no
   `--upstream` flag. This blocks `run`/`up` from setting the upstream programmatically.
2. **No one-command experience** — no `run` (wrap+exec agent) and no `up` (zero-config
   build+serve+wire-hint).
3. **No persistent config** — every run re-sets env; nothing remembers upstream/threshold/port.
4. **No verifier** — nothing answers "is my setup correct?"
5. **PATH wart** — `keymd` entry point missing on Microsoft-Store / `pip --user` Python.

## Non-goals (YAGNI)

- No daemon/process manager beyond `run`'s single child, no TUI, no multi-project registry.
- No editing of the user's framework config files (env-injection + printed hint only —
  auto-editing arbitrary framework configs is brittle and surprising).
- **No actual PyPI publish** — readiness only, with a guard preventing accidental upload.
- No new runtime dependencies (`tomllib` is stdlib on Python ≥3.11, the floor).
- No change to the engine's existing path/root resolution — it already works.

## Components

### A. `keymd.toml` — optional project config (repo root, committed, NO secrets)

New loader `src/keymd/engine/settings.py` reads an optional `keymd.toml` via stdlib
`tomllib`.

```toml
# keymd.toml — committed; contains NO secrets (API keys ride on request headers)
[keymd]
threshold = 400          # gate files larger than this many loc

[keymd.serve]
host = "127.0.0.1"
port = 8787
wire = "openai"          # "openai" | "anthropic" — which upstream --upstream maps to
upstream = "https://api.openai.com"   # base URL only; NEVER an API key
```

- **Precedence per setting: CLI flag > environment variable > keymd.toml > built-in default.**
- **API keys never stored.** The proxy forwards the caller's `Authorization` / `x-api-key`
  header untouched (honors "never hardcode secrets").
- Missing file → all defaults (zero-config works). Malformed → a clear error naming the
  file + parse problem, not a stack trace.
- `settings.load(root=None) -> Settings` is pure (path in → dataclass out), for testability.

### B. Kill the env-before-import footgun (`proxy/server.py`)

- `forward_upstream(body, headers, base=None)` / `forward_openai(body, headers, base=None)`
  resolve the base **at call-time** (`base or os.environ.get(...) or default`) instead of an
  import-time global. Reading env at call-time alone fixes the documented footgun; the
  `base` param lets `run`/`up`/`serve` pass an explicit upstream.
- `build_app(threshold=400, *, upstream=None, openai_base=None)` and
  `serve(..., upstream=None, openai_base=None)` thread those through. The route's `upstream`
  closure calls the module-level `forward_*` so **existing 2-arg monkeypatched test fakes
  keep working** (closure passes `base` only when non-None).
- Remove the unused `UPSTREAM_BASE`/`OPENAI_BASE` module globals; update `cli.py`'s serve
  print to show the resolved base. (Only `server.py` + `cli.py:90` reference them; no tests do.)
- **Regression test:** set `KEYMD_OPENAI_BASE` *after* importing `server`, call
  `forward_openai`, assert the request URL uses the late-set base (monkeypatch `_post` to
  capture the URL); and assert an explicit `base` override beats env.

### C. `keymd up` — zero-config one-command build + serve

`keymd up [--rebuild]`:
1. Resolve root; if `.keymd/index.db` is missing (or `--rebuild`), run `index.build()`.
2. Resolve host/port/threshold/wire/upstream via the precedence chain (flag>env>toml>default).
3. Print a friendly wiring block: the proxy URL, and the exact env lines to point a
   framework at it (`ANTHROPIC_BASE_URL=…`, `OPENAI_BASE_URL=…/v1`).
4. Start the proxy (`server.serve(...)`).

### D. `keymd run -- <agent cmd> [args…]` — the wired one-liner

`keymd run [--port N] [--rebuild] -- <cmd> [args…]`:
1. Resolve root; build index if missing (or `--rebuild`).
2. Start the proxy in a **background daemon thread** (`uvicorn.Server` with
   `install_signal_handlers=lambda:None`); wait until `server.started` (bounded poll).
3. Build the child env = parent env + injected base-URLs (set ALL of these so it works
   regardless of the agent's wire; the single proxy serves both routes):
   - `ANTHROPIC_BASE_URL = http://host:port`
   - `OPENAI_BASE_URL = http://host:port/v1`
   - `OPENAI_API_BASE = http://host:port/v1`  (legacy alias)
4. `subprocess.run([cmd, *args], env=child_env)` inheriting stdio (interactive agent).
5. On child exit **or** KeyboardInterrupt: signal the server to stop
   (`server.should_exit = True`), join the thread, exit with the child's return code.
6. Errors: empty command after `--` → usage error; command not found → clear message + non-zero exit.

### E. `keymd init [path] [--force] [--write-agents]` — persist config (optional)

For users who want committed settings rather than zero-config:
1. Write `keymd.toml` with sensible defaults; skip if present (print hint) unless `--force`;
   never partially-write on failure.
2. **Print** the `templates/AGENTS.md` steering snippet (embedded as a code constant so it
   ships with the installed package — repo-root `templates/` is not packaged). `--write-agents`
   appends it to the repo's `AGENTS.md` once (no duplicate if the marker is present; no
   silent clobber).
3. Print the `keymd run -- <agent>` / `keymd up` next-step hint.

### F. `keymd doctor` — setup verifier + shared self-check module

`src/keymd/proxy/selfcheck.py` extracts the proven gate-loop validation core into
`run_inprocess(threshold=50) -> {ok, gate_fired, chunks, detail}` — **in-process, local
stub upstream, no API spend** — plus a shared `stub_upstream_app(target)` /
`build_big_repo()` helper. `scripts/validate_sse.py` imports those helpers (DRY; it keeps
its distinct real-socket + real-SDK driver). `keymd doctor [--wire] [--net]` prints ✓/✗
with fix hints; non-zero exit if a **hard** check fails:
1. Index exists + non-empty (`query.stats()`).
2. `keymd.toml` parseable (via `settings.load()`); absent is OK.
3. `keymd` entry point on PATH (`shutil.which`); else advise `python -m keymd`.
4. Proxy extras importable (`httpx`/`starlette`/`uvicorn`); else advise `pip install 'keymd[proxy]'`.
5. `--wire` (opt-in): `selfcheck.run_inprocess()` — confirms the synthesized-SSE gate path works.
6. `--net` (opt-in): cheap unauthenticated TCP reach to the configured upstream host; warn-only.

### G. `pyproject.toml` publish-readiness (ready, NOT published)

Add `authors`, `readme = "README.md"`, `[project.urls]`, `keywords`, classifiers, and an
`all` extra (`all = proxy + watch + lang`) for `pip install keymd[all]`. Add the
**`"Private :: Do Not Upload"`** classifier so a stray upload is rejected by PyPI. Going
public later = remove that classifier + choose a license. **No publish in this work.**

## Testing strategy (TDD)

- `settings.load()` — precedence, missing→defaults, malformed→clear error.
- `server` upstream plumbing — **footgun regression** (env set after import routes
  correctly; explicit override wins); existing streaming/smoke tests unchanged.
- `up` — builds when index missing, skips when present, prints wiring lines, resolves
  precedence (test the resolution helper directly; don't actually block on `serve`).
- `run` — env injection contains all three base-URLs pointing at the chosen port; child is
  invoked with that env (monkeypatch `subprocess.run` to capture env + argv); empty-command
  errors; proxy thread started and stopped. (Use a trivial child like the current Python exe
  printing an env var, or a captured fake.)
- `init` — writes toml, idempotent no-clobber, `--force`, `--write-agents` appends once.
- `doctor` — each check's ✓/✗ on a fixture (index present/absent, config present/absent,
  extras present); `--wire` ok via selfcheck.
- `selfcheck.run_inprocess()` — `ok=True, gate_fired=True` against the local stub.

## Files

- Create: `src/keymd/engine/settings.py`, `src/keymd/proxy/selfcheck.py`,
  `src/keymd/onboarding.py` (the `up`/`run`/`init`/`doctor` command bodies + the embedded
  AGENTS snippet + the env-resolution helper), `tests/test_settings.py`,
  `tests/test_onboarding.py` (up/run/init/doctor), and selfcheck assertions folded into
  `tests/test_proxy_sse_openai_sdk.py` or a small `tests/test_selfcheck.py`.
- Modify: `src/keymd/proxy/server.py` (call-time upstream + params), `src/keymd/cli.py`
  (wire `up`/`run`/`init`/`doctor` + `serve --upstream/--wire`; resolved-base print),
  `scripts/validate_sse.py` (import shared stub helpers from selfcheck), `pyproject.toml`,
  `README.md` (lead with `keymd run`/`keymd up`).
- Convention: this repo keeps **no `.key.md` sidecars for its own source** and tests carry
  none — match that (no key files added). `onboarding.py` >50 loc but follows repo
  convention (no sidecar).
