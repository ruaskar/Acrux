# Changelog

Notable changes to keymd. This project follows [Semantic Versioning](https://semver.org/).
Changelog tracking begins at 0.1.4; earlier releases are listed on the
[Releases page](https://github.com/ruaskar/Acrux/releases).

## [0.1.14] — 2026-06-08

### Added

- **`keymd graph` now shows folder organization on top of the call graph.** Nodes are
  colored by folder and wrapped in translucent labeled "blobs" (convex hulls), with a mild
  clustering force so folders separate into visual neighborhoods — so the graph answers both
  "what calls what" and "how is this repo organized" at once. A bottom-left legend lists each
  folder (color + file count) with two independent per-folder toggles: click the row to
  hide/show that folder's **files** (declutter a dominant directory like a big `tests/`), or
  click the ⬡ button to hide/show just that folder's **grouping blob** while its files stay.
  Quick controls toggle all/no files and all/no blobs. Folder grouping strips a leading
  `src`/`lib` prefix so meaningful packages surface instead of one giant `src` blob. Pure
  client-side — no change to the index or the data served.

[0.1.14]: https://github.com/ruaskar/Acrux/releases/tag/v0.1.14

## [0.1.13] — 2026-06-03

### Fixed

- **`keymd summarize` now works with every OpenAI-compatible provider.** The OpenAI wire
  hardcoded a `/v1` path segment, which doubled the version for any provider whose base URL
  already includes it — breaking DeepSeek (`/v1`), Qwen (`/compatible-mode/v1`), Gemini
  (`/v1beta/openai`), and local Ollama / LM Studio (`/v1`) with a `…/v1/v1/chat/completions`
  404. The wire now follows the OpenAI-SDK / LiteLLM convention: the version lives in the
  base URL you set (`KEYMD_OPENAI_BASE`) and only `/chat/completions` is appended. Point
  `--wire openai` at any of these providers' documented base URLs and it just works; the
  bare default (`https://api.openai.com/v1`) is unchanged. `--wire anthropic` (Claude /
  Anthropic-compatible) is unaffected.

[0.1.13]: https://github.com/ruaskar/Acrux/releases/tag/v0.1.13

## [0.1.12] — 2026-06-02

### Added

- **`keymd summarize` — opt-in LLM file summaries via your own model.** Caches a prose
  summary per gated file, generated through **your** endpoint and key (OpenAI- or
  Anthropic-protocol — covers local models like Ollama/LM Studio), and serves it as the
  `summary:` lead everywhere: `.key.md`, the proxy gate, and the `keymd graph` side panel.
  sha-incremental (re-summarizes only changed files) and secret-redacted. keymd never uses
  its own key — a missing key fails loudly, never spends silently. The cache survives a
  full `keymd build` (only stale/deleted entries are dropped), so summaries aren't
  regenerated on every rebuild. `keymd summarize [path] --wire openai|anthropic --model X`.
  The first pass costs about one scan per file; the win is reuse — later agent sessions
  read the cached prose instead of re-reading the code.

[0.1.12]: https://github.com/ruaskar/Acrux/releases/tag/v0.1.12

## [0.1.11] — 2026-06-02

### Added

- **`keymd graph` now works on Java, C, and C++ repos.** keymd previously indexed only
  Python and JS/TS, so on a Java/C/C++ project the graph showed inert side-panel tabs —
  nothing to map or navigate, because those files were never indexed. A new spec-driven
  tree-sitter walker extracts symbols, signatures, and a cross-file call graph for these
  languages, so the graph, the token-saving gate, search, and `.key.md` summaries all light
  up. Reference/pointer returns, operators, out-of-line definitions, and destructors are
  handled; function-pointer variables are correctly excluded; string default values stay
  hidden (`<str>`) as on every other language. (`pip install 'keymd[lang]'` for the grammars;
  they are embedded in the binary.)
- **`keymd build` now reports skipped files** in languages it can't parse yet (e.g. Go,
  Rust), so a mixed-repo never silently omits sources without telling you.

[0.1.11]: https://github.com/ruaskar/Acrux/releases/tag/v0.1.11

## [0.1.10] — 2026-06-02

### Fixed

- **`keymd graph` no longer dead-ends on a blank page.** Run from a directory with no
  indexable code (e.g. your home dir, the common first-run case), it used to silently
  build an empty index and open a blank graph. It now prints actionable guidance and
  exits without starting a server. And `keymd graph [path]` / `keymd build [path]` accept
  an explicit repo/folder, so you can point keymd at a project from anywhere (defaults to
  the current directory when omitted).

### Changed

- **Repo URLs canonicalized to `github.com/ruaskar/Acrux`** (the project was renamed from
  keymd to Acrux; the command is still `keymd`). Old `ruaskar/keymd` URLs continue to
  redirect, so existing installers and badges keep working.

[0.1.10]: https://github.com/ruaskar/Acrux/releases/tag/v0.1.10

## [0.1.9] — 2026-06-02

### Fixed

- **Installer now configures PATH instead of only warning about it.** `install.sh` /
  `install.ps1` previously printed a "add it to PATH" note, then suggested a `keymd …`
  command that failed with "command not found" whenever the install dir wasn't on PATH
  (the common macOS/zsh case). They now append the install dir to the user's shell profile
  (`.zshrc` / `.bashrc` / `.profile`) or Windows user PATH — idempotently, with
  `KEYMD_NO_MODIFY_PATH=1` to opt out — and tell you to restart/`source` your shell.

### Changed

- **Installer next-steps are agent-agnostic.** The post-install hint no longer hardcodes
  `keymd run -- claude`; it leads with `keymd graph` (no API key needed) and
  `keymd run -- <your-agent>` (claude · codex · aider · cline · …).
- **Project rebranded to Acrux** (the command stays `keymd`). The README now positions the
  tool around its single structural map of your repo — served to your agent (fewer tokens)
  and drawn for you as an interactive call-graph. No code, CLI, package, env-var, or tool
  name changed.

[0.1.9]: https://github.com/ruaskar/keymd/releases/tag/v0.1.9

## [0.1.8] — 2026-06-02

### Fixed

- **Install no longer hangs on a fresh machine.** keymd's optional dependencies were
  declared with lower bounds only (e.g. `starlette>=0.37`, which admits ~195 candidate
  releases), and no lock file shipped — so pip's resolver could backtrack across a huge
  version space on first install (and on the binary's first-run `pip install keymd[all]`).
  Every extra now carries an upper bound (`starlette>=0.37,<2`, `watchdog>=4,<7`, …) so
  the resolver settles immediately; the bounds travel in the wheel metadata, so the binary
  install is fixed too. A clean-venv resolve now completes in seconds instead of backtracking.

### Added

- **`requirements.lock`** — exact, test-verified pins of every optional dependency. Install
  deterministically with `pip install -c requirements.lock -e ".[all]"`. README documents it
  plus a `--prefer-binary` tip for native-dependency (lxml) source-build stalls.

[0.1.8]: https://github.com/ruaskar/keymd/releases/tag/v0.1.8

## [0.1.7] — 2026-06-01

### Added

- **Clickable per-function detail in `keymd graph`.** Clicking a function or class row in
  the side panel's "inputs & outputs" now opens a focused view of that symbol: its
  **docstring summary**, its **signature (in / out)**, every **caller (upstream)**, and every
  **callee (downstream)** — each caller/callee clickable to jump to that file and highlight
  the function. A **← back** link returns to the file panel. Backed by a new read-only
  `query.symbol_detail()` and a path-confined `/api/symbol` endpoint — pure read over the
  existing index (callees from the call graph, callers from the caller index, the function's
  docstring read on demand). No schema change, no re-index.
- When a bare method name is **ambiguous** (e.g. two classes each defining `__init__`), the
  panel shows a small picker of the candidates instead of silently guessing one.

### Security

- The on-demand function docstring is redacted as prose before it is served (provider tokens,
  `key=value` secrets, and long opaque blobs are masked); the new `/api/symbol` route
  canonicalizes and confines its path to the project root exactly like `/api/summary`, and all
  caller/callee navigation attributes are HTML-attribute-escaped.

[0.1.7]: https://github.com/ruaskar/keymd/releases/tag/v0.1.7

## [0.1.6] — 2026-06-01

### Added

- **`keymd graph`** — an interactive, force-directed call-graph of your repo in the
  browser, served from a localhost server on an auto-chosen free port (no hardcoded
  port; two instances never collide). Node size reflects call-graph centrality. The
  side panel **leads with the file's summary** (its module docstring), then a
  syntax-highlighted **inputs & outputs** list (signatures with `L`-anchors), then
  **dependencies** and **calls**. The dep/call chips are **clickable** — they
  navigate the graph to the target file and highlight the called function. D3 is
  vendored (no CDN); fully offline. Pure read over the existing index — no schema
  change, no re-index.
- **Module-docstring summaries.** The Python parser now captures each file's module
  docstring (first line) as a `summary:` lead in its `.key.md` — a deterministic
  "what this file does" with no LLM/API call. Improves `keymd_read` and `keymd
  search` results, not just the graph. String values in a docstring are redacted
  (it rides the same secret backstop as other prose, at the stronger opaque bar).
- **Live index refresh while serving.** `keymd serve` and `keymd graph` now spawn
  keymd's filesystem watcher in a background thread, so `.key.md` + the index + FTS
  stay fresh on every edit **and new file** — including edits made with an agent's
  native tools or your own editor (which the `keymd_edit` tool alone wouldn't see).
  Opt out with `--no-watch`; degrades gracefully to a one-line hint if the `watch`
  extra (watchdog) isn't installed.

### Changed

- **`keymd search` works on a plain build.** Full-text search now indexes the
  rendered summaries of every file (consistently across build/refresh/sync/watch),
  so it returns results immediately after `keymd build` instead of only over
  committed `.key.md` sidecars. Hits are enriched with call-graph context and ranked
  by centrality (a match in a widely-depended-on module surfaces above a leaf), with
  ranking applied to a wider candidate pool than the limit so a central hit isn't
  truncated before it's seen. (Search work landed on master after v0.1.5; this is
  its first release to the binary.)

### Security

- **String contents inside type annotations are hidden structurally.** A string in
  an annotation (e.g. `Literal['secret']`) now renders as `<str>` via an AST
  transform, matching the value-hiding rule for assignments — closing a path where a
  short, opaque, non-provider-shaped secret in a `Literal[...]` could reach a summary
  (and the search index / `keymd_read`). Numeric `Literal[...]` values are kept.

[0.1.6]: https://github.com/ruaskar/keymd/releases/tag/v0.1.6

## [0.1.5] — 2026-06-01

### Changed

- **Default gate threshold lowered 400 → 50 loc.** At 400, the gate almost never
  fired on a normal codebase (on a real 102-file repo it summarized 5 files; at 50
  it summarizes 72). The crossover was measured: files >50 loc summarize at a net
  token win, files ≤50 loc pass through (where a summary's fixed overhead would
  exceed the file). This is the change that makes keymd actually save tokens on a
  typical project — measured 87% read-payload reduction across an external repo's
  ingestion pipeline. Override per-project in `keymd.toml` or with `--threshold`.
- **`keymd_read_full` line cap tightened 800 → 400.** A full read is re-sent in the
  transcript every subsequent turn, so the cap is a recurring per-turn cost; 400
  keeps a genuine escalation useful while halving that tax. (`keymd_read_symbol`
  reads by indexed span and is unaffected — no mid-symbol truncation.)

### Added

- **`keymd demo`** — a zero-config before/after that shows the read-payload savings
  on keymd's own source (or `keymd demo <path>` on your repo). No agent, API key, or
  network. The fastest way to see the value before wiring anything up.

### Fixed

- **Transparent pass-through when no index exists.** The proxy now forwards to the
  upstream without injecting keymd's tool definitions or system directive when no
  index is built — so keymd adds zero tokens instead of advertising tools that can't
  work. It becomes a true no-op until you run `keymd build`.

[0.1.5]: https://github.com/ruaskar/keymd/releases/tag/v0.1.5

## [0.1.4] — 2026-05-31

### Security

- **The JavaScript/TypeScript parser leaked hardcoded string parameter-default
  values into summaries.** A string default in a JS/TS function, method, or arrow
  parameter — e.g. `function connect(url = "postgres://user:pass@host/db")` — was
  emitted verbatim into the generated `.key.md` summary, the symbol/FTS index, and
  model context, so a credential hardcoded in such a default could be exposed. The
  Python parser was unaffected (it already renders string values as `<str>`).
  **Present in the published v0.1.2 and v0.1.3 binaries.**

  Fixed: JS/TS string default values now render as `<str>`, matching the Python
  parser's value-hiding guarantee; type annotations are preserved
  (`url: string = <str>`). A registry-wide conformance test
  (`tests/test_no_secret_leaks.py`) now proves the no-string-value guarantee for
  **every** registered parser and fails CI if a parser is added without leak
  coverage. As defense-in-depth, a uniform secret-shape backstop runs at the single
  `ParseResult` construction point every parser passes through.

  **Recommendation:** upgrade with `keymd update` (or reinstall the binary). If you
  index JS/TS, regenerate summaries so any already-written `.key.md` files that
  captured a default value are refreshed.

[0.1.4]: https://github.com/ruaskar/keymd/releases/tag/v0.1.4
