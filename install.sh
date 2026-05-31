#!/usr/bin/env bash
# keymd installer — downloads the prebuilt binary from GitHub Releases.
#   curl -fsSL https://raw.githubusercontent.com/ruaskar/keymd/master/install.sh | sh
#
# No Python/pip needed. Override the location with KEYMD_INSTALL_DIR.
set -euo pipefail

repo="ruaskar/keymd"
dest="${KEYMD_INSTALL_DIR:-$HOME/.local/bin}"

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

case ":$PATH:" in
  *":$dest:"*) ;;
  *) echo "note: add it to PATH →  export PATH=\"$dest:\$PATH\"" ;;
esac
echo "try:  keymd run -- claude"
