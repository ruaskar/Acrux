#!/usr/bin/env bash
# Acrux installer — downloads the prebuilt `keymd` binary from GitHub Releases.
#   curl -fsSL https://raw.githubusercontent.com/ruaskar/Acrux/master/install.sh | sh
#
# No Python/pip needed. The project is Acrux; the command it installs is `keymd`.
#   KEYMD_INSTALL_DIR=<dir>     install somewhere other than ~/.local/bin
#   KEYMD_NO_MODIFY_PATH=1      don't touch your shell profile (print steps instead)
set -euo pipefail

repo="ruaskar/Acrux"
dest="${KEYMD_INSTALL_DIR:-$HOME/.local/bin}"

# --- PATH configuration (factored out so it's unit-testable) -----------------
# Pick the shell profile to persist PATH into: prefer the file for the user's
# login shell ($SHELL), falling back to whatever already exists, then ~/.profile.
_profile_file() {
  case "${SHELL:-}" in
    *zsh)  printf '%s\n' "${ZDOTDIR:-$HOME}/.zshrc"; return ;;
    *bash) printf '%s\n' "$HOME/.bashrc"; return ;;
  esac
  for f in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
    [ -f "$f" ] && { printf '%s\n' "$f"; return; }
  done
  printf '%s\n' "$HOME/.profile"
}

# Append the PATH export to a profile file, idempotently (no duplicate on re-run).
# Returns 0 if it wrote a line, 1 if it was already present.
_add_to_profile() {
  dir="$1"; profile="$2"
  line="export PATH=\"$dir:\$PATH\""
  [ -f "$profile" ] && grep -qF "$line" "$profile" && return 1
  printf '\n# added by the Acrux (keymd) installer\n%s\n' "$line" >> "$profile"
  return 0
}

# Is `dir` already on PATH?
_on_path() { case ":$PATH:" in *":$1:"*) return 0 ;; *) return 1 ;; esac; }

# Configure PATH after install. Echoes guidance. Honors KEYMD_NO_MODIFY_PATH.
_configure_path() {
  dir="$1"
  if _on_path "$dir"; then return 0; fi
  if [ "${KEYMD_NO_MODIFY_PATH:-}" = "1" ]; then
    echo "note: $dir is not on your PATH. To use \`keymd\`, add it:"
    echo "  export PATH=\"$dir:\$PATH\"     # add this to your shell profile"
    return 0
  fi
  profile="$(_profile_file)"
  if _add_to_profile "$dir" "$profile"; then
    echo "added $dir to PATH in $profile"
  else
    echo "$dir already configured in $profile"
  fi
  echo "→ restart your shell, or run:  source \"$profile\""
}

# When sourced by the test harness (LIB_ONLY=1), stop here — expose the functions
# without downloading or installing anything.
[ "${LIB_ONLY:-}" = "1" ] && return 0

os="$(uname -s)"; arch="$(uname -m)"
case "$os" in
  Linux)  plat="linux-x86_64" ;;
  Darwin)
    case "$arch" in
      arm64|aarch64) plat="macos-aarch64" ;;
      *) echo "no prebuilt binary for Intel Macs yet — install via pip/uvx:" >&2
         echo "  pipx install \"keymd[all] @ git+https://github.com/$repo\"" >&2
         exit 1 ;;
    esac ;;
  *) echo "unsupported OS '$os' — on Windows use install.ps1 or the .exe from Releases" >&2; exit 1 ;;
esac

echo "resolving latest release…"
tag="$(curl -fsSL "https://api.github.com/repos/$repo/releases/latest" \
       | grep -o '"tag_name"[^,]*' | head -1 | cut -d'"' -f4)"
[ -n "$tag" ] || { echo "could not resolve a release (none published yet?)" >&2; exit 1; }

base="https://github.com/$repo/releases/download/$tag"
echo "downloading keymd $tag ($plat)…"
mkdir -p "$dest"
tmp="$dest/keymd.download"
curl -fSL "$base/keymd-$plat" -o "$tmp"

# Verify against the release's published SHA256SUMS BEFORE installing — never run
# an unverified native binary that will proxy your API key and edit your files.
echo "verifying checksum…"
sums="$(curl -fsSL "$base/SHA256SUMS")" || {
  rm -f "$tmp"; echo "could not fetch SHA256SUMS — refusing to install unverified binary" >&2; exit 1; }
want="$(printf '%s\n' "$sums" | awk -v f="keymd-$plat" '$2==f{print $1}' | head -1)"
[ -n "$want" ] || { rm -f "$tmp"; echo "no checksum for keymd-$plat in SHA256SUMS — aborting" >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then got="$(sha256sum "$tmp" | awk '{print $1}')"
else got="$(shasum -a 256 "$tmp" | awk '{print $1}')"; fi   # macOS has shasum, not sha256sum
if [ "$want" != "$got" ]; then
  rm -f "$tmp"
  echo "CHECKSUM MISMATCH (expected $want, got $got) — refusing to install" >&2; exit 1
fi
echo "checksum OK"
chmod +x "$tmp"
mv -f "$tmp" "$dest/keymd"
echo "installed: $dest/keymd"

# Fix the PATH (the #1 first-run failure), don't just warn about it.
_configure_path "$dest"

echo
echo "try:"
echo "  keymd graph /path/to/repo   # see a codebase as an interactive call-graph (no API key)"
echo "  keymd run -- <your-agent>   # wire your agent through keymd: e.g. claude · codex · aider · cline"
echo "  (or cd into a repo first, then: keymd graph)"
