# Changelog

Notable changes to keymd. This project follows [Semantic Versioning](https://semver.org/).
Changelog tracking begins at 0.1.4; earlier releases are listed on the
[Releases page](https://github.com/ruaskar/keymd/releases).

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
