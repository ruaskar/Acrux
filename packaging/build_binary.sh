#!/usr/bin/env bash
# Build a self-contained keymd binary with PyApp (https://ofek.dev/pyapp).
#
# Wraps keymd's own wheel + a standalone CPython into one native executable, so
# the end user needs no Python, no pip, and no PATH setup. PyApp installs keymd
# onto REAL CPython using standard wheels, so native deps (tree-sitter, lxml)
# resolve as ordinary binary wheels — no freezing, no hooks.
#
# Requires: cargo (Rust), python3, curl, tar.
# Usage:    packaging/build_binary.sh        # run from anywhere
# Output:   dist/keymd        (dist/keymd.exe on Windows)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
cd "$root"

command -v cargo  >/dev/null 2>&1 || { echo "error: cargo not found — install Rust from https://rustup.rs" >&2; exit 1; }
command -v python >/dev/null 2>&1 || python3 --version >/dev/null 2>&1 || { echo "error: python not found" >&2; exit 1; }
PY="$(command -v python || command -v python3)"

ext=""
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) ext=".exe";; esac

# git-bash paths like /c/x are not understood by the native (Windows) cargo
# build, which reads PYAPP_PROJECT_PATH at build time — convert to C:/x.
to_native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

# 1. canonical PyApp config (single source of truth)
set -a; . "$here/pyapp.env"; set +a

# 2. build keymd's own wheel — embedded into the binary (no PyPI publish needed)
echo "==> building keymd wheel"
"$PY" -m pip wheel . --no-deps -w dist/ >/dev/null
wheel="$(ls -1 dist/keymd-*.whl | head -n1)"
[ -n "$wheel" ] || { echo "error: no wheel produced in dist/" >&2; exit 1; }
export PYAPP_PROJECT_PATH; PYAPP_PROJECT_PATH="$(to_native "$root/$wheel")"
echo "    embedding: $PYAPP_PROJECT_PATH"

# 3. fetch the PyApp launcher source (compiled around our config)
echo "==> fetching PyApp source"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
curl -fsSL https://github.com/ofek/pyapp/releases/latest/download/source.tar.gz -o "$work/pyapp.tar.gz"
tar -xzf "$work/pyapp.tar.gz" -C "$work"
src="$(ls -d "$work"/pyapp-*/ 2>/dev/null | head -n1)"
[ -n "$src" ] || { echo "error: could not find extracted PyApp source" >&2; exit 1; }

# 4. compile (the PYAPP_* env above is read by PyApp's build script)
echo "==> cargo build --release (downloads crates + compiles; a few minutes)"
( cd "$src" && cargo build --release )

# 5. place the renamed binary
mkdir -p dist
cp "$src/target/release/pyapp$ext" "dist/keymd$ext"
[ -z "$ext" ] && chmod +x "dist/keymd$ext"
echo "==> built dist/keymd$ext"
