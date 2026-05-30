# packaging/ — building the keymd binary

keymd ships as a self-contained native binary (no Python/pip on the user's
machine) built with [PyApp](https://ofek.dev/pyapp). PyApp compiles a small Rust
launcher that, on first run, materializes a private **standard CPython** and
installs keymd onto it from ordinary wheels — so native deps (`tree-sitter`,
`lxml`) "just work" as binary wheels, with no freezing or `.spec` hooks.

## Files

| File | Purpose |
|---|---|
| `pyapp.env` | Canonical PyApp config (`PYAPP_*`). Single source of truth, sourced by the script + CI. |
| `build_binary.sh` | Build one binary for the current platform → `dist/keymd[.exe]`. |

The platform matrix build + release lives in [`.github/workflows/binary.yml`](../.github/workflows/binary.yml).

## Build locally

Prerequisites: **Rust/cargo** (https://rustup.rs), **Python 3**, `curl`, `tar`.
On Windows use **Git Bash** (the script is POSIX; `cygpath` handles path
translation) — the Rust toolchain itself is native MSVC.

```bash
packaging/build_binary.sh        # → dist/keymd  (dist/keymd.exe on Windows)
./dist/keymd build               # first run installs deps into a private env (~once)
./dist/keymd run -- claude       # everything works as the pip-installed CLI does
```

## What the user gets

- **First run:** the launcher installs keymd[all] into a per-user managed env
  (~6 s + a one-time wheel download). CPython is embedded (`PYAPP_DISTRIBUTION_EMBED=1`),
  so there is **no** Python download — only the keymd dependency wheels.
- **Every run after:** instant (~0.2–0.5 s), like any CLI.
- **Footprint:** ~150 MB CPython (shared across PyApp apps) + ~40 MB keymd env.

## Notes

- keymd's wheel is **embedded** in the binary (`PYAPP_PROJECT_PATH`), so we do
  **not** publish keymd to PyPI. Only its public deps fetch from PyPI on first run.
- PyApp can't cross-compile the launcher; the CI matrix builds one binary per
  OS/arch. The Rust wrapper is tiny — the heavy bits resolve at runtime as wheels.
- Air-gapped / fully-offline builds (embed a vendored wheelhouse too) are a
  future option; today's first run needs network for the dependency wheels.
