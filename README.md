# Acrux

[![Release](https://img.shields.io/github/v/release/ruaskar/Acrux?sort=semver&color=2ea043)](https://github.com/ruaskar/Acrux/releases/latest)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Binaries](https://img.shields.io/badge/binaries-linux%20%C2%B7%20macOS%20%C2%B7%20windows-555)](https://github.com/ruaskar/Acrux/releases/latest)

### Navigate your codebase by its brightest points.

**Acrux builds one structural map of your repo and puts it to work two ways:** your AI
coding agent reads the **crux** of each file instead of the whole thing (**−50–70% tokens,
no loss in answer quality**), and you explore how it all connects as an **interactive
call-graph** in your browser.

> **Acrux is the project; `keymd` is the command you run.** Everything below — `keymd build`,
> `keymd serve`, `keymd graph` — is unchanged; Acrux is the name of the tool, `keymd` is how
> you invoke it (the way you type `rg` to run ripgrep).

## The kernel

A codebase is mostly shape: which functions exist, what they call, where each lives. An
agent usually needs that shape — not the full text of every file — yet today it pays to
ship whole files into the context window just to find a few lines. Acrux breaks that. It
builds **one** structural map of your repo — a call-graph plus a compact, line-anchored
summary of every file, derived deterministically from the AST with **no extra LLM call** —
and runs a local proxy on the one path every read must cross. There it swaps each full-file
read for that summary. The agent navigates by summary and pulls (or surgically edits) only
the exact lines it needs, escalating to full source only when it must. **That is why it
saves tokens:** a summary is roughly constant-size no matter how long the file is, so you
stop paying by the byte for context the agent was only going to skim — **−50–70% on
read-heavy work, with no loss in answer quality** because full source is always one escape
away. The same map, drawn instead of served, is the interactive call-graph you explore in
`keymd graph`.

Under the hood, `keymd` is a local proxy in front of your LLM that swaps every **full file read
for a compact, line-anchored summary** — an API + call-graph map for code, a table of contents
for **PDF / Word / Markdown**. Your agent navigates by summary and pulls (or surgically
**edits**) only the exact lines it needs, opening the full source only when it has to. Summaries
are deterministic — built from the AST / document structure with **no extra LLM call** — and
your API key never leaves your machine. The **same map** is what `keymd graph` draws for you.

*The −50–70% is the **read-payload reduction** — how much smaller a summary is than the full
file — aggregated over this repo (`tiktoken o200k_base`, reproducible with
`python benchmarks/offline_ab.py`). It's **task-shaped**: large when the agent navigates by
summary, and near **0** when it must open a file for an exact value (it escalates and reads
the full source). Savings scale with file size and the gate threshold.*

> **Why it's different:** per-file sidecars for **code *and* documents** · a deterministic structure
> section regenerated with **no LLM** · **served and enforced on every read** by a local proxy ·
> **line anchors** for surgical reads + edits · backed by a **live, incremental call-graph** index ·
> the same index **drawn as an interactive graph** (`keymd graph`).

> **Why "Acrux"?** Acrux is the brightest star of the **Crux** (Southern Cross) — the point you
> navigate by. The name is the idea: read the *crux* of each file (fewer tokens), and steer your
> codebase by the map those points form (the call-graph).

## Quickstart

```bash
curl -fsSL https://raw.githubusercontent.com/ruaskar/Acrux/master/install.sh | sh   # no Python needed (Windows: install.ps1)
keymd graph /path/to/repo   # see a codebase as a call-graph (no API key needed)
keymd run -- <your-agent>   # …or wire your agent through keymd: claude · codex · aider · cline · …
```

> The installer verifies the binary against the release's `SHA256SUMS` before installing. **First run** fetches the dependency wheels from PyPI (a few seconds, needs network); after that keymd runs locally. Not on PyPI yet — Intel Macs / offline installs: `pipx install "keymd[all] @ git+https://github.com/ruaskar/Acrux"`.

Or install via pip and launch your agent through keymd in one command:

```bash
pip install "keymd[all] @ git+https://github.com/ruaskar/Acrux"   # not yet on PyPI; or use the binary
cd your-project
keymd run -- <your-agent>  # build index + serve + wire base-url + launch your agent through keymd
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

### Install as a binary

Prefer a self-contained executable? Install the native binary (built with
[PyApp](https://ofek.dev/pyapp); no Python or pip needed on your machine):

```bash
# Linux / macOS (Apple Silicon):
curl -fsSL https://raw.githubusercontent.com/ruaskar/Acrux/master/install.sh | sh
# Windows (PowerShell):
irm https://raw.githubusercontent.com/ruaskar/Acrux/master/install.ps1 | iex
```

Or download a binary directly from the
[latest release](https://github.com/ruaskar/Acrux/releases/latest) —
`keymd-linux-x86_64`, `keymd-macos-aarch64`, `keymd-windows-x86_64.exe`. On first run it
installs its dependencies into a private environment (one-time, ~seconds); every run after
is instant. *Intel Macs:* use the `pip install` above for now.

**Keep it current** — `keymd update` downloads the latest release, **verifies it against the
published `SHA256SUMS`**, and self-replaces the running binary:

```bash
keymd update        # or: keymd update --check   (report only)
keymd --version
```

## Measured token savings

Deterministic, **no API spend** — full source vs `.key.md` summary, counted with a real
tokenizer (`tiktoken o200k_base`). Reproduce: `python benchmarks/offline_ab.py`. Numbers
below are measured **on keymd's own repo** (86 files, all small — a compact repo
*understates* the effect, since a summary is ~constant size regardless of file length).

| Workload | Tokens | Lines read |
|---|--:|--:|
| Agent reads the whole repo (every file by summary) | **−71%** | **−81%** |
| Gate at files > 75 loc | **−57%** | — |
| One large file (`server.py`, 312 loc) | **−75%** | — |

> The production gate's **default threshold is 50 loc** — files larger than that are summarized — so
> savings scale with file size; a compact repo understates them. Regenerate any time with
> `python benchmarks/offline_ab.py`.

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
> measured −29% tokens / −85% lines / 96% accuracy retained on a different codebase.)
>
> **→ Full reproducible benchmark suite** — efficiency + degradation guard, methodology,
> results, and reproduction commands — in [`benchmarks/BENCHMARK.md`](benchmarks/BENCHMARK.md).
> A deterministic run over keymd's own repo measured **−61% read-payload tokens**; the
> escape-honored degradation study (below) retained accuracy **15/15**. A paid end-to-end
> harness is scaffolded, not run.

### Does the gate degrade the agent? No.

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

## See the call graph — `keymd graph`

```bash
keymd graph                 # map the repo in the current directory
keymd graph /path/to/repo   # …or point it at any repo from anywhere
```

Run it in an indexed repo and keymd serves an interactive, force-directed graph of your
files on a local-only server (an auto-chosen free port — two instances never collide). It's
a pure read over the index keymd already built — **no re-index, no schema change, fully
offline** (D3 is vendored, no CDN). Node size reflects call-graph centrality, so the hubs
your codebase actually leans on stand out at a glance.

The side panel is where the summary work pays off:

- **Click a file node** → its `.key.md`: the **summary** lead (the file's docstring), then a
  syntax-highlighted **inputs & outputs** list (signatures with `L`-anchors), then
  **dependencies** and **calls**.
- **Click a dependency or call chip** → the graph navigates to that file and highlights the
  function. Stdlib / external / ambiguous targets are shown but greyed (nowhere to jump).
- **Click a function row** → a focused view of *that function*: its **docstring summary**, its
  **signature (in / out)**, every caller **(upstream)**, and every callee **(downstream)** —
  each caller/callee clickable to jump there. A **← back** link returns to the file.

Because summaries flow through the same renderer as everything else, string **values stay
hidden** (`API_KEY = <str>`) — no secret reaches the browser. While `keymd graph` (or
`keymd serve`) is running it also keeps the index live: edit a file or add a new one and the
summaries refresh automatically (`--no-watch` to opt out; needs the `watch` extra).

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

## How it works — the `.key.md` summary

A generated `.key.md` (deterministic, LLM-optimized, no human-maintained region):

```
# src/foo.py  [python · 153 loc · sha:a2ecd3f3]
summary: foo.py — parse a stream of rows and validate each against the schema.
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

## Wire your agent into any framework (attach mode)

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

For an agent keymd launches itself, the non-streaming path is:

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

### Bring your own LLM + agent framework

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

## Why local-proxy enforcement (not MCP, not a cloud service)

- **More enforceable than MCP.** MCP only *offers* a tool the agent may ignore; the proxy sits on the one path every token must cross to reach the model, so the summary is *guaranteed* to land before the expensive read.
- **Not sketchy.** The proxy forwards to your real upstream (Anthropic/OpenAI) **with your own key**. The only thing that leaves your machine is the request that was already going to the LLM — now smaller. No third party, no telemetry.
- **Reads and edits are confined to the project root** — `keymd_read_full`/`keymd_read_range`/`keymd_read_symbol` won't read, and `keymd_edit` won't write, outside the repo (e.g. `/etc/passwd`, SSH keys, `.env`) even if the model asks. `keymd_edit` only applies an *exact, unique* match, then re-indexes the file so its summary/anchors stay accurate.

## Use the engine (works today, fully offline)

```bash
keymd build                       # index the repo into .keymd/index.db
keymd impact src/foo.py           # who depends on this file
keymd refresh src/foo.py          # (re)generate src/foo.key.md
keymd search "parse header"       # FTS over all summaries
keymd watch                       # keep sidecars + index live on edits
keymd graph                       # interactive call-graph in your browser (localhost)
```

## What's here (status)

| Component | State |
|---|---|
| **Index engine** — tree-sitter call-graph + `.key.md` generator + query CLI | ✅ implemented, tested |
| **Languages** — Python (stdlib `ast`), JS/TS · Java · C · C++ (tree-sitter) | ✅ Python full; JS/TS/Java/C/C++ symbols/sigs/deps/callees + cross-file call graph (caller-graph best-effort) |
| **Documents** — Markdown (core) · PDF + DOCX (`docs` extra) | ✅ table-of-contents summary + section anchors + ranged reads; binary docs read-only |
| **Region tools** — `keymd_read_symbol` / `keymd_read_range` / `keymd_edit` | ✅ pull or surgically edit a span by anchor; edit re-indexes; confined to the repo |
| **Graph viz** — `keymd graph` interactive call-graph + side panel | ✅ force-directed map; node→summary, clickable dep/call chips + per-function detail (callers/callees); localhost, offline (vendored D3) |
| **LLM summaries** — `keymd summarize` (opt-in; your own model) | ✅ caches a prose summary per gated file via **your** endpoint+key, sha-incremental, secret-redacted; served as the `summary:` lead in `.key.md` + gate + graph. Works with any OpenAI-compatible provider — OpenAI, **DeepSeek, Qwen, Gemini** (`/v1beta/openai`), local **Ollama/LM Studio** — via `--wire openai` + your provider's base URL (set `KEYMD_OPENAI_BASE`, version segment included); plus `--wire anthropic` for Claude/Anthropic-compatible. First pass ≈ one scan; wins on reuse. |
| **FS watcher** — keeps sidecars + index live on edits | ✅ implemented, tested; runs standalone (`keymd watch`) or bundled into `keymd serve` / `keymd graph` (`--no-watch` to disable) |
| **Enforcing proxy** — gate + virtual tools, Anthropic + OpenAI wire formats | ✅ gate logic implemented, tested against a mock upstream |
| **Guardrails** — push-main / duplicate / commit-before-build (opt-in, *not* token-saving) | ✅ implemented, tested |
| **SSE streaming to a host** | ✅ synthesized — `stream:true` clients get a valid event stream (buffered then synthesized, **not** token-by-token; whole answer in one delta after the gate). Validated against the real `openai` SDK in-process and over a real socket (`python scripts/validate_sse.py`). |
| **A/B token benchmark** | ✅ offline efficiency harness + live paired-subagent degradation guard run — see [`benchmarks/BENCHMARK.md`](benchmarks/BENCHMARK.md); paid end-to-end harness scaffolded, not run |

> **Honest boundary:** the proxy's gate *logic* is proven end-to-end against a mock upstream and a real self-hosted-LLM dogfood (no paid API spend). The synthesized stream is validated against the real `openai` SDK — the canonical strict SSE client — both in-process and over a real socket; the *named* frameworks (OpenClaw / Hermes Agent) themselves haven't yet been driven against it. Streaming is *synthesized* (one delta after the gate completes), not true token-by-token relay — that's a future refinement.

## Install from source

```bash
pip install -c requirements.lock -e ".[dev,proxy,watch,lang,docs]"   # engine is dependency-free; extras add proxy / watcher / JS-TS / PDF+DOCX
```

> **Install hanging or slow to resolve?** Use the `-c requirements.lock` constraints
> file shown above — it pins every extra to a known-good version so pip's resolver
> settles immediately instead of backtracking across hundreds of candidate releases.
> If a native dependency (`python-docx` → `lxml`, `pypdf`) tries to build from source
> and stalls, add `--prefer-binary` to force prebuilt wheels:
> `pip install --prefer-binary -c requirements.lock -e ".[all]"`.

> If `keymd` isn't found after install (common with Microsoft Store / `pip --user` Python, whose Scripts dir isn't on PATH), use the PATH-independent form **`python -m keymd ...`** in place of `keymd ...` everywhere below, or add your Python user-Scripts dir to PATH. A virtualenv avoids the issue entirely.

## License

[Apache-2.0](LICENSE) © ruaskar. Patent grant included; use, modify, and redistribute with attribution + NOTICE preservation.
