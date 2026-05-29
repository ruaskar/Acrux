# keymd — cross-framework token-saving enforcement layer

**Status:** design approved (2026-05-29), pre-implementation
**Working name:** `keymd` (the `.key.md` convention is unclaimed; alternatives `keygate`/`keyward`; lock before publish)
**Source material:** extracted/generalized from `WhiteBox-Macro/aotc-harness` (private) — see §10.

---

## 1. Problem & positioning

Agentic coding tools burn tokens reading whole files and mass-grepping when a compact, accurate summary would do. `aotc-harness` proved a fix for **Claude Code only**, via hooks: a `.key.md` sidecar read before the full file (benchmarked −85% lines read / −29% tokens, 96% accuracy retained). That enforcement is welded to Claude Code's proprietary hook API and is Python-only.

**This project generalizes the mechanism to every framework** by relocating enforcement from the host's hook API onto the **universal LLM-traffic path** (a local proxy), and by replacing the Python-only AST front-end with tree-sitter.

**Positioning — what we are NOT:** not "AI codebase docs" (that space is occupied by Autodoc / DeepWiki / docstring generators and we'd look redundant). The defensible, currently-unoccupied combination is:

> **Per-file, git-committed sidecars that are fully machine-maintained and LLM-optimized — a deterministic AST-structure section regenerated with no LLM call, plus an optional LLM semantic digest — served before every file read and *enforced* by a local proxy, kept fresh by a live incremental call-graph index.**

Prior art ships the *ingredients* separately (tree-sitter signature maps: aider, repomix `--compress`; incremental Merkle indexes: Cursor, claude-context; per-file LLM docs: Autodoc) but no tool combines committed-per-file + hybrid-deterministic/LLM + **served-and-enforced-on-read** + **incremental live graph**. The three load-bearing differentiators are (a) **proxy-enforced read-gating**, (b) **deterministic structure that needs no LLM and never drifts**, (c) **per-file committed sidecars backed by a live caller/callee graph**.

## 2. The `.key.md` artifact contract

**Fully machine-maintained. No human-authored / protected region.** Formatted for LLM consumption (token-dense, structured, high-signal — not human-prose readability). The whole file is regenerable; nothing is "owned." Two parts:

1. **Deterministic structure (always; no LLM, free):** extracted by tree-sitter and the index — top-level symbols with signatures, project + external dependencies, downstream calls (resolved), upstream callers (`sym ← path, path (+N more)`), line count, source content-hash, refreshed-at. Regenerated on every change to the file.
2. **LLM semantic digest (optional; off by default):** dense purpose / contract / side-effects / gotchas. Generated only when the user enables it **with their own API key**, debounced to *material* structural changes (not every save), batched. Absent this, the file is still fully useful (structure only). Honors the no-unprompted-API-spend rule.

Example shape (content terse; exact format finalized in implementation):

```markdown
# parser.py  [python · 5021 loc · sha:9f2a…]
purpose: streaming SEC-filing tokenizer → row dicts        # (LLM digest, if enabled)
api:
  parse_header(buf: bytes) -> Header
  Parser.parse(self, stream) -> Iterator[Row]
deps: io, typing | .schema, .errors
calls: schema.validate_row, errors.raise_malformed
called_by:
  Parser.parse ← pipeline.py, batch.py (+3 more)
contracts: not thread-safe; consumes stream once             # (LLM digest, if enabled)
refreshed: 2026-05-29T14:02Z
```

No sentinel-merge logic is needed (a simplification vs the source `aotc-harness`, which protected a human region above a sentinel).

## 3. Architecture — one local daemon, three faculties

```
  agent (Claude Code / Codex / Cline / Aider / LangGraph / CrewAI / MAF …)
        │  LLM base_url → http://localhost:8787
        ▼
  ┌────────────────────────────────────────────────────────────┐
  │ keymd daemon  (localhost only; forwards upstream w/ YOUR key)│
  │                                                              │
  │ (a) ENFORCING PROXY  — hook-equivalent on the LLM path       │
  │      • pre-read gate: withhold full read / mass-grep of an   │
  │        indexed file until the .key.md has been served;       │
  │        full body is opt-in via explicit `:full` escalation   │
  │      • virtual tools: keymd_read / keymd_symbol /            │
  │        keymd_impact / keymd_callers / keymd_callees /        │
  │        keymd_search — answered LOCALLY (no host MCP needed)  │
  │      • read-redirect: swap oversized file blobs → summary    │
  │      • output-cap: cap oversized tool-results in context     │
  │                                                              │
  │ (b) INDEX ENGINE  — tree-sitter (py/js/ts) → SQLite + FTS5   │
  │      tables: files · symbols · edges(call/import/inherit) ·  │
  │      keymds · keymd_fts                                      │
  │                                                              │
  │ (c) FS WATCHER  — on write: re-parse file, regenerate its    │
  │      .key.md, cascade-refresh upstream/downstream callers'   │
  │      keys → graph stays live at refactor speed               │
  └────────────────────────────────────────────────────────────┘
        │  forwards compressed request
        ▼
   real upstream (api.anthropic.com / api.openai.com)
```

- **(a) Enforcing proxy** = the `aotc-harness` hook chain (`pre-read-key-gate` + query tools + read-redirect + output cap), unified on the one path every token must cross. Speaks **Anthropic Messages** and **OpenAI Chat-Completions/Responses** wire formats; preserves SSE streaming and tool-call IDs.
- **(b) Index engine** = `aotc-harness` `keymd/` engine with the `ast.walk` front-end replaced by tree-sitter (py/js/ts), reusing its language-neutral downstream (SQLite schema, import-gated caller heuristic + STDLIB_STEMS guard, AUTO-refresh, query CLI).
- **(c) FS watcher** = replaces the `post-edit`/`commit-gate` bash hooks; catches writes regardless of origin (more robust than parsing edit calls from the stream).

### Proxy enforcement mechanism (the novel core)

The proxy adds virtual `keymd_*` tools and a directive to each upstream request. When the model emits a host tool-call that reads/greps an indexed file, the proxy **does not forward it to the host**. In its own inner loop it returns the `.key.md` as the tool-result and re-queries the model, repeating until the model either (i) proceeds with the summary, or (ii) explicitly escalates (`Read <path>:full`). Only an escalated/real call is forwarded to the host for execution. The host issues one HTTP request and receives one coherent assistant turn; it never sees the inner loop.

**Honest guarantee (not overclaimed):** like the source key-gate (which has a bypass), this *guarantees the cheap summary is in front of the model before the expensive read and makes the full read opt-in*. It does not prevent a model that genuinely needs the body from escalating — that is correct behavior, not a leak.

## 4. Enforcement walkthrough — "read & change a 5000-line file"

1. User: *"refactor `parser.py` (5000 loc)."* Model emits `Read(parser.py)`.
2. Proxy intercepts; `parser.py` is indexed and large → withholds. Inner-loop tool-result = `parser.key.md` (~15 lines) + "reply `Read parser.py:full`, or `keymd_symbol(name)` for a specific body."
3. Model has the map for ~15 lines instead of 5000. It calls `keymd_symbol("Parser.parse")` → just that function + its call-sites. Reads stay surgical.
4. Model emits `Edit(parser.py, …)` → proxy forwards (edits never blocked) → host writes disk.
5. FS watcher fires: re-parses `parser.py`, regenerates its `.key.md`, and cascade-refreshes the keys of every upstream caller / downstream callee whose edges changed.
6. Net: the 5000-line blob never enters model context; structure queries replace mass-greps; keys are current for the next turn.

## 5. Coverage & limits (explicit)

| Host class | LLM endpoint configurable? | Enforcement mode |
|---|---|---|
| Claude Code (`ANTHROPIC_BASE_URL`), OpenAI Codex CLI, Cline, Roo, Continue, Aider, LangGraph / CrewAI / MAF (model-client base_url) | **Yes** | **Hard** — full proxy gate + virtual tools + redirect + cap |
| Cursor, Windsurf, GitHub Copilot (vendor-routed endpoints) | No | **Soft** — degrade to an MCP query server + an `AGENTS.md` "read the key first" instruction (advisory, ~80% compliance, no hard gate) |

No central server. The proxy only ever forwards the user's own traffic to the user's own upstream with the user's own key; the sole thing leaving the machine is the request that was already going to the LLM, now smaller.

## 6. Scope

**In — token savers (core):**
- `.key.md` contract + generator (§2)
- tree-sitter index engine (py/js/ts) (§3b)
- enforcing proxy: gate + virtual tools + read-redirect + output-cap (§3a)
- FS watcher + incremental cascade refresh (§3c)
- CLI: `keymd build | serve | impact | callers | callees | search | handoff`
- `/handoff` session-compaction — cherry-picked from `origin/feature/handoff-command` and generalized (compresses a session into a structured catchup + paste-ready pickup → next session reloads minimal context)

**In — portable guardrails (separate, optional module; explicitly NOT token-saving):**
- `push-main-gate`, `duplicate-gate`, `commit-before-build` — realized as git-hooks + proxy-side checks, env-configurable, AOTC narratives scrubbed (kept for completeness/usefulness, clearly labeled non-saving).

**Out:**
- 3 private hooks hardwired to `/opt/coverage-ai` (`docker-build-gate`, `sandbox-guard`, `vip-py-gate`) — concepts documented, code left behind.
- discipline-only protocols (memory-threading, memory-write-protocol, self-improving, per-prompt reminder) — no token savings; some add context.

## 7. Risks / load-bearing engineering

1. **Prompt-cache safety** — rewriting must be deterministic with stable prefixes so Anthropic/OpenAI prefix-cache hits survive; naive rewriting *raises* cost. Make-or-break.
2. **Tool-virtualization fidelity** — inner loop must return one coherent assistant turn; preserve tool-call IDs, parallel tool-calls, `tool_choice`, stop reasons.
3. **Expansion without loops** — `:full` escalation passes through once and is remembered (no re-elide loop).
4. **Wire-format + streaming adapters** — Anthropic Messages vs OpenAI Chat-Completions vs Responses; SSE passthrough.
5. **tree-sitter edge resolution** — port the import-gated caller heuristic + STDLIB_STEMS guard to JS/TS module resolution (differs from Python).
6. **Windows** — replace the POSIX `fcntl` lock from the source engine (daemon must run on the user's Windows box).

## 8. Repo layout

```
keymd/
  daemon/      proxy.py · wireformats/{anthropic,openai}.py · gate.py · virtual_tools.py · cache.py
  engine/      index.py (tree-sitter) · refresh.py · sync_one.py · graph.py · query.py · config.py
  watcher/     fswatch.py
  guardrails/  (optional) push_main.py · duplicate.py · commit_before_build.py
  cli/         keymd entrypoint (build · serve · impact · callers · callees · search · handoff)
  templates/   key-file.md · AGENTS.md snippet · per-host setup (CC / Codex / Cline / Aider)
  benchmarks/  A/B harness (re-run on a public repo)
  docs/        README (lead w/ read-gate + privacy, not "AI docs") · adapters · privacy
```

**Stack:** Python 3.11 daemon — `asyncio` reverse-proxy + `tree-sitter` (py/js/ts grammars) + `sqlite3`/FTS5. One language; reuses the source engine's downstream.

## 9. Phasing

- **v1:** daemon (a)+(b)+(c); Python + JS/TS; Anthropic + OpenAI wire formats; `.key.md` contract; **hard enforcement proven on Claude Code + Codex + Cline**; A/B benchmark on a public repo.
- **v1.1:** guardrails module + `/handoff` + soft-mode MCP fallback for closed IDEs.
- **v2:** more languages (Go/Rust); optional LLM intent-digest pipeline; richer output-cap rules.

**Success criterion (measured, not asserted):** on a "read + edit a large file" task battery, measurable token reduction vs a no-proxy control (target in the ballpark of −29% tokens / −85% lines from the source benchmark) with accuracy retained.

## 10. Sourcing & public-safety scrub (from recon)

- **Canonical source:** `WhiteBox-Macro/aotc-harness@main` (content superset of `ruaskar/AOTC_Harness`: hardened 16 hooks + 3 net-new). The two remotes have **independent git roots** — combine by content copy / cherry-pick, never a merge.
- **Cherry-pick:** `commands/handoff.md` from `origin/feature/handoff-command` (present on no main branch).
- **Reusable as-is:** `protocols/` and the `keymd/` engine `.py` are already clean.
- **Scrub before publish:** `/opt/coverage-ai` references; the `-home-coverage` hardcoded memory-path glob (latent silent no-op bug); the personal per-prompt reminder string; the AOTC git-pull incident narrative (keep its regex bank); benchmark script names (re-run on a public repo).
- **Fix on extraction:** `fcntl` Windows blocker; doc drift ("7-step" prose vs 4-step live reminder).

## 11. Open items (non-blocking)

- Final name + GitHub org/visibility for the public repo.
- Whether the LLM semantic-digest pipeline ships in v1 (currently v2) given it's off-by-default anyway.
- Exact `.key.md` on-disk format (markdown-ish vs a more compact encoding) — pin during implementation with a token-density micro-benchmark.

## 12. As-built reconciliation (2026-05-30) — spec vs shipped surface

The implementation reconciled two §3/§6/§9 items differently (both decided in the implementation plan; recording here so this design-of-record matches the code):
- **`keymd_symbol` → `keymd_read_full`.** The full-source escalation tool shipped as `keymd_read_full(path)` (project-root-confined, line-capped). A symbol-granular `keymd_symbol` needs per-symbol end-line tracking in the parser/schema and is deferred to Phase 3b.
- **`keymd handoff` CLI → Phase 5 template.** Handoff ships as `templates/handoff.md` (a host slash-command) rather than a `keymd` CLI subcommand, since session compaction is host-side, not engine-side.
- The shipped v1 CLI is `build | refresh | sync | callers | callees | symbols | impact | search | missing-keymds | stats | serve | watch | guard`.
