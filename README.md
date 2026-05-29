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
| **SSE streaming to a live host** | ⏳ not yet — needed for real Claude Code use (hosts stream by default). Use non-streaming for now. |
| **A/B token benchmark** | ⏳ harness scaffolded; not run (needs API spend) |

> **Honest boundary:** the proxy's gate *logic* is proven end-to-end against a mock upstream (no API spend). It is **not yet wired for a streaming host** — see `docs/superpowers/plans/` for the streaming/benchmark plan.

## Install

```bash
pip install -e ".[dev,proxy,watch,lang]"   # engine is dependency-free; extras add proxy/watcher/JS-TS
```

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

## License

Private (pre-release). No redistribution without permission.
