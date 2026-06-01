# Changelog

Notable changes to keymd. This project follows [Semantic Versioning](https://semver.org/).
Changelog tracking begins at 0.1.4; earlier releases are listed on the
[Releases page](https://github.com/ruaskar/keymd/releases).

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
