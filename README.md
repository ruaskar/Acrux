# keymd

[![Release](https://img.shields.io/github/v/release/ruaskar/keymd?sort=semver&color=2ea043)](https://github.com/ruaskar/keymd/releases/latest)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Binaries](https://img.shields.io/badge/binaries-linux%20%C2%B7%20macOS%20%C2%B7%20windows-555)](https://github.com/ruaskar/keymd/releases/latest)

### Cut your AI coding agent's token usage by 50–70% — with no loss in answer quality.

*This is the **read-payload reduction** — how much smaller a summary is than the full file —
aggregated over keymd's own repo (`tiktoken o200k_base`, reproducible with
`python benchmarks/offline_ab.py`). It's **task-shaped**: large when the agent navigates by
summary, and near **0** when it must open a file for an exact value (it escalates and reads
the full source). Savings scale with file size and the gate threshold.*

`keymd` is a local proxy in front of your LLM that swaps every **full file read for a compact,
line-anchored summary** — an API + call-graph map for code, a table of contents for **PDF / Word /
Markdown**. Your agent navigates by summary and pulls (or surgically **edits**) only the exact lines
it needs, opening the full source only when it has to. Summaries are deterministic — built from the
AST / document structure with **no extra LLM call** — and your API key never leaves your machine.

```bash
curl -fsSL https://raw.githubusercontent.com/ruaskar/keymd/master/install.sh | sh   # no Python needed (Windows: install.ps1)
keymd run -- claude
```

> The installer verifies the binary against the release's `SHA256SUMS` before installing. **First run** fetches the dependency wheels from PyPI (a few seconds, needs network); after that keymd runs locally. Not on PyPI yet — Intel Macs / offline installs: `pipx install "keymd[all] @ git+https://github.com/ruaskar/keymd"`.

### Performance — measured on keymd's own repo · deterministic · `tiktoken o200k_base`

| Workload | Tokens | Lines read |
|---|--:|--:|
| Agent reads the whole repo (every file by summary) | **−71%** | **−81%** |
| Gate at files > 75 loc | **−57%** | — |
| One large file (`server.py`, 312 loc) | **−75%** | — |

> The production gate's **default threshold is 50 loc** — files larger than that are summarized — so
> savings scale with file size; a compact repo understates them. Regenerate any time with
> `python benchmarks/offline_ab.py`.

And it **doesn't dumb the agent down**: a small paired-agent A/B (N=3–5, single repo, Sonnet,
blind judge) found accuracy retained — **5/5** reading summaries instead of source, **15/15**
under the strict enforced gate (a deliberately *value-heavy* battery that stresses accuracy, not
tokens). keymd is a token lever, not a capability tax.
→ [full methodology + honest boundaries](#measured-token-savings)

> **Why it's different:** per-file sidecars for **code *and* documents** · a deterministic structure
> section regenerated with **no LLM** · **served and enforced on every read** by a local proxy ·
> **line anchors** for surgical reads + edits · backed by a **live, incremental call-graph** index.

## Quickstart (one command)

```bash
pip install "keymd[all] @ git+https://github.com/ruaskar/keymd"   # not yet on PyPI; or use the binary
cd your-project
keymd run -- claude        # build index + serve + wire base-url + launch the agent through keymd
```

`keymd run -- <agent>` builds the index, starts the local proxy, injects the base-URL env
vars, and execs your agent **through** keymd (cleanup on exit). Works for any agent that
reads its endpoint from `ANTHROPIC_BASE_URL`/`OPENAI_BASE_URL` (Claude Code, Codex, Aider,
OpenAI-compatible CLIs).

**See the savings first, no setup:** `keymd demo` runs a before/after on keymd's own
source (or `keymd demo <your-repo>`) and prints the read-payload reduction — no agent, no
API key, no network. The fastest way to know if it's worth wiring up.

For frameworks that take their endpoint from a **config file** (e.g. OpenClaw): run
`keymd up` (zero-config build + serve + prints the one line) and point the framework's
`base_url` at it. Verify anytime with `keymd doctor --wire` (no API spend).

> If `keymd` isn't on PATH (Microsoft-Store / `pip --user` Python), use `python -m keymd …`.

## Install as a binary 

Prefer a self-contained executable? Install the native binary (built with
[PyApp](https://ofek.dev/pyapp); no Python or pip needed on your machine):

```bash
# Linux / macOS (Apple Silicon):
curl -fsSL https://raw.githubusercontent.com/ruaskar/keymd/master/install.sh | sh
# Windows (PowerShell):
irm https://raw.githubusercontent.com/ruaskar/keymd/master/install.ps1 | iex
```

Or download a binary directly from the
[latest release](https://github.com/ruaskar/keymd/releases/latest) —
`keymd-linux-x86_64`, `keymd-macos-aarch64`, `keymd-windows-x86_64.exe`. On first run it
installs its dependencies into a private environment (one-time, ~seconds); every run after
is instant. *Intel Macs:* use the `pip install` above for now.

**Keep it current** — `keymd update` downloads the latest release, **verifies it against the
published `SHA256SUMS`**, and self-replaces the running binary:

```bash
keymd update        # or: keymd update --check   (report only)
keymd --version
```

## Summarize documents too — Markdown · PDF · Word

`keymd build` indexes documents alongside code. A long document gets a **table of
contents** with the same line anchors, so the agent reads the map and pulls one section
instead of the whole file:

```
# report.pdf  [pdf · 212 lines]
sections (L-spans include nested sub-sections):
  Executive Summary  # L1-2
  Financials         # L3-9
  Risks              # L10-24
    Currency Risk    # L18-24
```

→ `keymd_read_range(report.pdf, 3, 9)` returns just the Financials text — extracted and
cached, so the agent never loads the whole binary. Sections come from PDF bookmarks / Word
heading styles / Markdown headings (else one section per page). Markdown ships in **core**;
PDF + Word need the `docs` extra (`pip install keymd[docs]`, already in `[all]`). Binary
docs are **read-only** — `keymd_edit` applies to code/text files.

## Measured token savings

Deterministic, **no API spend** — full source vs `.key.md` summary, counted with a real
tokenizer (`tiktoken o200k_base`). Reproduce: `python benchmarks/offline_ab.py`. Numbers
below are measured **on keymd's own repo** (86 files, all small — a compact repo
*understates* the effect, since a summary is ~constant size regardless of file length).

| View | Arm A (full) | Arm B (keymd) | Reduction |
|---|---|---|---|
| **Whole repo** (read every file) | 51,710 tok / 5,231 lines | 14,565 tok / 1,061 lines | **71.8% tok · 79.7% lines** |
| **Realistic gate** (>75 loc, no fallback) | 51,710 tok | 24,198 tok | **53.2% tok** |
| Per-file (e.g. `cli.py` 151 loc) | 1,692 tok | 186 tok | 89.0% |

**Fallback sweep** (`f` = fraction of files the agent still reads in full): 71.8% → 46.8%
(f=25%) → 21.8% (f=50%). **Gate-threshold sweep**: the default **50-loc** gate summarizes
every real source file (a 400-loc gate fired on almost none — most modules are 100–350 loc);
files ≤50 loc pass through, where a summary would be no smaller than the file.

> **Honest boundary:** this is the *read-payload* lever only — not whether cheap summaries
> make a model read *more* files, not task success, not write-heavy work. The savings are
> largest on read-heavy work over large files. (The source aotc-harness end-to-end A/B
> measured −29% tokens / −85% lines / 96% accuracy retained on a different codebase; a paid
> end-to-end harness for keymd is scaffolded in [`benchmarks/ab_harness.py`](benchmarks/ab_harness.py), not run.)

## Does the gate degrade the agent? No.

A paired-subagent A/B on a 5-task battery over this repo (comprehension · structure · trace
· locate · fix): a **control** agent reads full source; a **treatment** agent reads only
keymd's `.key.md` summaries, opening full source solely when a summary is insufficient. An
independent judge (blind to which arm) scored every answer against a ground-truth key.

**Result: 5/5 vs 5/5 — 100% accuracy retained.** The summary-reading agent answered every
question as correctly as the full-source agent — and on one task found *more* (both call
sites of a function, surfaced by the call-graph summary). Reading compact summaries cost
zero answer quality; the token savings come from the *enforced* gate above (the agent can
always pull full source via `keymd_read_full` when it needs to). Full methodology + per-task
numbers: [`benchmarks/ability_eval.md`](benchmarks/ability_eval.md).

**Under the strict *enforced* gate** (summary-first, no raw reads, explicit `keymd_read_full`
escape — the real product, built deterministically from the live gate by
[`benchmarks/enforced_gate_eval.py`](benchmarks/enforced_gate_eval.py)), across **3 trials**:
**15/15 accuracy retained** when the agent uses the escape keymd's own directive tells it to
use. Token cut is *task-shaped*, not one number: **−34%** on the structural "which files call
X" task (answered from the call-graph, no escape) but ~0 on value-lookup tasks, where a correct
answer means opening the file anyway (so the agent escalates and reads it). This battery is
deliberately value-heavy — a stress test for *accuracy*, not tokens; the corpus-wide structural
savings are the 53–78% above. Honest evidence the gate **doesn't degrade the agent** — the
savings just live in navigation, not in value-lookup. (A single earlier run where the agent
*declined* the escape and guessed scored 4/5 — an escalation-discipline artifact, not a
capability loss.) Full frontier + per-task numbers:
[`benchmarks/ability_eval.md`](benchmarks/ability_eval.md).

## Use keymd from your IDE or framework (attach mode)

IDE agents (Claude Code in VS Code, Codex, Cline, Continue, Cursor) and config-file
frameworks aren't launched by keymd, so instead of `keymd run` you **attach**: start the
proxy once and point the tool's own base-URL at it.

```bash
keymd up        # build + serve; leave it running in a spare terminal
keymd ide       # print the exact wiring for every supported tool (or: keymd ide codex)
```

keymd routes by **wire format, not model** — it serves the Anthropic (`/v1/messages`,
`/v1/messages/count_tokens`) *and* OpenAI (`/v1/chat/completions`, `/v1/responses`) APIs,
so any model behind an OpenAI/Anthropic-compatible endpoint (GPT, Claude, Hermes, Qwen,
Llama via vLLM / Ollama / LM Studio / LiteLLM) works.

| Tool | Wire | Where to point it (base = `http://localhost:8787`) |
|---|---|---|
| **Claude Code** (VS Code/CLI/JetBrains) | Anthropic | `~/.claude/settings.json` → `"env": {"ANTHROPIC_BASE_URL": "<base>"}`; restart |
| **Codex** | OpenAI | `~/.codex/config.toml` named provider → `base_url="<base>/v1"`, `wire_api="chat"` **or** `"responses"` (both supported) |
| **Cline** | OpenAI | Settings → "OpenAI Compatible" → Base URL `<base>/v1` |
| **Continue.dev** | OpenAI | `config.yaml` → `provider: openai`, `apiBase: <base>/v1` |
| **Cursor / Roo** | OpenAI | Override OpenAI Base URL → `<base>/v1` |
| **OpenClaw** | OpenAI | `models.providers.<id>.baseUrl = <base>/v1` |
| **Hermes Agent** | OpenAI/Anthropic | `base_url = <base>` (Anthropic) or `<base>/v1` (OpenAI); forces streaming → handled |

Auth flows through transparently — each tool keeps sending its own key; keymd forwards it
upstream untouched. Verify with `keymd doctor --wire`.

## Why local-proxy enforcement (not MCP, not a cloud service)

- **More enforceable than MCP.** MCP only *offers* a tool the agent may ignore; the proxy sits on the one path every token must cross to reach the model, so the summary is *guaranteed* to land before the expensive read.
- **Not sketchy.** The proxy forwards to your real upstream (Anthropic/OpenAI) **with your own key**. The only thing that leaves your machine is the request that was already going to the LLM — now smaller. No third party, no telemetry.
- **Reads and edits are confined to the project root** — `keymd_read_full`/`keymd_read_range`/`keymd_read_symbol` won't read, and `keymd_edit` won't write, outside the repo (e.g. `/etc/passwd`, SSH keys, `.env`) even if the model asks. `keymd_edit` only applies an *exact, unique* match, then re-indexes the file so its summary/anchors stay accurate.

## What's here (status)

| Component | State |
|---|---|
| **Index engine** — tree-sitter call-graph + `.key.md` generator + query CLI | ✅ implemented, tested |
| **Languages** — Python (stdlib `ast`), JS/TS (tree-sitter) | ✅ Python full; JS/TS symbols/sigs/deps/callees (caller-graph best-effort) |
| **Documents** — Markdown (core) · PDF + DOCX (`docs` extra) | ✅ table-of-contents summary + section anchors + ranged reads; binary docs read-only |
| **Region tools** — `keymd_read_symbol` / `keymd_read_range` / `keymd_edit` | ✅ pull or surgically edit a span by anchor; edit re-indexes; confined to the repo |
| **FS watcher** — keeps sidecars + index live on edits | ✅ implemented, tested |
| **Enforcing proxy** — gate + virtual tools, Anthropic + OpenAI wire formats | ✅ gate logic implemented, tested against a mock upstream |
| **Guardrails** — push-main / duplicate / commit-before-build (opt-in, *not* token-saving) | ✅ implemented, tested |
| **SSE streaming to a host** | ✅ synthesized — `stream:true` clients get a valid event stream (buffered then synthesized, **not** token-by-token; whole answer in one delta after the gate). Validated against the real `openai` SDK in-process and over a real socket (`python scripts/validate_sse.py`). |
| **A/B token benchmark** | ✅ offline (no-spend) harness run — see [Measured token savings](#measured-token-savings); paid end-to-end harness scaffolded, not run |

> **Honest boundary:** the proxy's gate *logic* is proven end-to-end against a mock upstream and a real self-hosted-LLM dogfood (no paid API spend). The synthesized stream is validated against the real `openai` SDK — the canonical strict SSE client — both in-process and over a real socket; the *named* frameworks (OpenClaw / Hermes Agent) themselves haven't yet been driven against it. Streaming is *synthesized* (one delta after the gate completes), not true token-by-token relay — that's a future refinement.

## Bring your own LLM + agent framework

keymd is a transparent middleman: it forwards to **your** upstream with **your** key (it injects no key of its own and drops non-standard headers). It works with any framework + model that meets three requirements:

1. **Wire format:** the framework speaks **OpenAI Chat Completions** (`/v1/chat/completions`), **OpenAI Responses** (`/v1/responses`), or **Anthropic Messages** (`/v1/messages`) — all three have adapters. Other envelopes (raw completions, Gemini, Cohere…) do not.
2. **Tool-calling model:** the model emits `tool_calls`/`tool_use` and reads files via a tool named `Read` / `read_file` / `view` / `cat`. (A model that never calls tools → keymd is a transparent pass-through with zero savings.)
3. **Configurable endpoint:** you can point the framework's `base_url` at `http://localhost:8787`.

Setup:
```bash
keymd build                                            # index your repo (gate files > --threshold loc)
export KEYMD_OPENAI_BASE=http://your-llm:8000          # or KEYMD_UPSTREAM_BASE for an Anthropic endpoint
keymd serve --port 8787 --threshold 50                 # serve reads env per request (or use `keymd up --upstream …`)
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
pip install -e ".[dev,proxy,watch,lang,docs]"   # engine is dependency-free; extras add proxy / watcher / JS-TS / PDF+DOCX
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
  def parse(self, stream) -> Iterator[Row]   # L41-88
deps: io, .schema, .errors
calls: schema.validate_row
called_by:
  Parser.parse ← pipeline.py, batch.py (+3 more)
refreshed: 2026-05-29T22:00
```

The `# L41-88` anchor lets the agent (through the proxy) pull just that function with the
`keymd_read_symbol(path, "parse")` tool — or `keymd_read_range(path, 41, 88)` — and change it
with `keymd_edit(path, old, new)`, which applies an exact, unique match and re-indexes the file
so the anchors stay accurate. (These are virtual tools the model calls over the proxy, not CLI
commands.)

## Point an agent at the proxy (non-streaming)

```bash
keymd build && keymd serve --threshold 50           # gate files > 50 loc
# Claude Code:           ANTHROPIC_BASE_URL=http://localhost:8787
# Codex / Cline / Aider: OpenAI-compatible base URL → http://localhost:8787
```

Add the steering snippet from [`templates/AGENTS.md`](templates/AGENTS.md) so the agent prefers `keymd_read`/`keymd_impact` over raw reads/greps.

Verify the streaming path works on your machine (no paid API — uses a local stub upstream):

```bash
python scripts/validate_sse.py      # PASS = SDK parsed the synthesized stream AND the gate fired
```

## License

[Apache-2.0](LICENSE) © ruaskar. Patent grant included; use, modify, and redistribute with attribution + NOTICE preservation.
