# keymd

**A local-only, cross-framework token-saving enforcement layer for coding agents.**

`keymd` runs a localhost proxy in front of your LLM endpoint that **gates a full file read behind a compact `.key.md` summary** — so an agent reads ~15 lines of API + call-graph instead of a 5,000-line file, and only pulls the full source when it explicitly needs to. The summaries are deterministic (extracted from the AST, **no LLM call**), committed next to your code, and kept fresh by an incremental call-graph index.

It is **not** "AI codebase docs." The defensible combination it ships, that nothing else does:

> per-file, git-committed sidecars · a **deterministic AST-structure** section regenerated with no LLM · **served and enforced on every read** by a local proxy · backed by a **live incremental call-graph** index.

## Why local-proxy enforcement (not MCP, not a cloud service)

- **More enforceable than MCP.** MCP only *offers* a tool the agent may ignore; the proxy sits on the one path every token must cross to reach the model, so the summary is *guaranteed* to land before the expensive read.
- **Not sketchy.** The proxy forwards to your real upstream (Anthropic/OpenAI) **with your own key**. The only thing that leaves your machine is the request that was already going to the LLM — now smaller. No third party, no telemetry.
- **`keymd_read_full` is confined to the project root** — the proxy will not read `/etc/passwd`, SSH keys, or `.env` even if the model asks.

## What's here (status)

| Component | State |
|---|---|
| **Index engine** — tree-sitter call-graph + `.key.md` generator + query CLI | ✅ implemented, tested |
| **Languages** — Python (stdlib `ast`), JS/TS (tree-sitter) | ✅ Python full; JS/TS symbols/sigs/deps/callees (caller-graph best-effort) |
| **FS watcher** — keeps sidecars + index live on edits | ✅ implemented, tested |
| **Enforcing proxy** — gate + virtual tools, Anthropic + OpenAI wire formats | ✅ gate logic implemented, tested against a mock upstream |
| **Guardrails** — push-main / duplicate / commit-before-build (opt-in, *not* token-saving) | ✅ implemented, tested |
| **SSE streaming to a host** | ✅ synthesized — `stream:true` clients get a valid event stream (buffered then synthesized, **not** token-by-token; whole answer in one delta after the gate). Validated against the real `openai` SDK in-process and over a real socket (`python scripts/validate_sse.py`). |
| **A/B token benchmark** | ⏳ harness scaffolded; not run (needs API spend) |

> **Honest boundary:** the proxy's gate *logic* is proven end-to-end against a mock upstream and a real self-hosted-LLM dogfood (no paid API spend). The synthesized stream is validated against the real `openai` SDK — the canonical strict SSE client — both in-process and over a real socket; the *named* frameworks (OpenClaw / Hermes Agent) themselves haven't yet been driven against it. Streaming is *synthesized* (one delta after the gate completes), not true token-by-token relay — that's a future refinement.

## Bring your own LLM + agent framework

keymd is a transparent middleman: it forwards to **your** upstream with **your** key (it injects no key of its own and drops non-standard headers). It works with any framework + model that meets three requirements:

1. **Wire format:** the framework speaks **OpenAI Chat Completions** (`/v1/chat/completions`) or **Anthropic Messages** (`/v1/messages`). No other envelope (OpenAI Responses, raw completions, Gemini, Cohere…) has an adapter.
2. **Tool-calling model:** the model emits `tool_calls`/`tool_use` and reads files via a tool named `Read` / `read_file` / `view` / `cat`. (A model that never calls tools → keymd is a transparent pass-through with zero savings.)
3. **Configurable endpoint:** you can point the framework's `base_url` at `http://localhost:8787`.

Setup:
```bash
keymd build                                            # index your repo (gate files > --threshold loc)
export KEYMD_OPENAI_BASE=http://your-llm:8000          # or KEYMD_UPSTREAM_BASE for an Anthropic endpoint
keymd serve --port 8787 --threshold 400                # set env BEFORE serve (read at import)
# in your framework: base_url → http://localhost:8787, keep your own API key
```

Verified compatibility (examined May 2026):

| Framework / model | Works? | Notes |
|---|---|---|
| **Self-hosted via vLLM / Ollama / llama.cpp / LM Studio / LiteLLM** | ✅ | All OpenAI-Chat-compatible; point `KEYMD_OPENAI_BASE` at them. Streaming is opt-in at the server, so the backend is fine. |
| **OpenClaw** | ✅ | `models.providers.<id>.baseUrl` → the proxy; OpenAI-Chat default. (Its docs already recommend `streaming:false` for OpenAI-compatible backends, which keymd handles either way.) |
| **Hermes Agent** | ✅ | `config.yaml provider:custom, base_url:…`; OpenAI or Anthropic mode. It forces streaming — keymd's synthesized SSE makes that work. |
| **Hermes / other local models** | ✅ | Serve behind vLLM with the right tool-call parser (e.g. `--tool-call-parser hermes`) → standard OpenAI `tool_calls`. |

## Install

```bash
pip install -e ".[dev,proxy,watch,lang]"   # engine is dependency-free; extras add proxy/watcher/JS-TS
```

> If `keymd` isn't found after install (common with Microsoft Store / `pip --user` Python, whose Scripts dir isn't on PATH), use the PATH-independent form **`python -m keymd ...`** in place of `keymd ...` everywhere below, or add your Python user-Scripts dir to PATH. A virtualenv avoids the issue entirely.

## Use the engine (works today, fully offline)

```bash
keymd build                       # index the repo into .keymd/index.db
keymd impact src/foo.py           # who depends on this file
keymd refresh src/foo.py          # (re)generate src/foo.key.md
keymd search "parse header"       # FTS over all summaries
keymd watch                       # keep sidecars + index live on edits
```

A generated `.key.md` (deterministic, LLM-optimized, no human-maintained region):

```
# src/foo.py  [python · 153 loc · sha:a2ecd3f3]
api:
  def parse(self, stream) -> Iterator[Row]
deps: io, .schema, .errors
calls: schema.validate_row
called_by:
  Parser.parse ← pipeline.py, batch.py (+3 more)
refreshed: 2026-05-29T22:00
```

## Point an agent at the proxy (non-streaming)

```bash
keymd build && keymd serve --threshold 400          # gate files > 400 loc
# Claude Code:           ANTHROPIC_BASE_URL=http://localhost:8787
# Codex / Cline / Aider: OpenAI-compatible base URL → http://localhost:8787
```

Add the steering snippet from [`templates/AGENTS.md`](templates/AGENTS.md) so the agent prefers `keymd_read`/`keymd_impact` over raw reads/greps.

Verify the streaming path works on your machine (no paid API — uses a local stub upstream):

```bash
python scripts/validate_sse.py      # PASS = SDK parsed the synthesized stream AND the gate fired
```

## License

Private (pre-release). No redistribution without permission.
