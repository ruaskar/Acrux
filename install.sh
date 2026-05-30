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
  Darwin) case "$arch" in arm64|aarch64) plat="macos-aarch64" ;; *) plat="macos-x86_64" ;; esac ;;
  *) echo "unsupported OS '$os' — on Windows use install.ps1 or the .exe from Releases" >&2; exit 1 ;;
esac

echo "resolving latest release…"
tag="$(curl -fsSL "https://api.github.com/repos/$repo/releases/latest" \
       | grep -o '"tag_name"[^,]*' | head -1 | cut -d'"' -f4)"
[ -n "$tag" ] || { echo "could not resolve a release (none published yet?)" >&2; exit 1; }

url="https://github.com/$repo/releases/download/$tag/keymd-$plat"
echo "downloading keymd $tag ($plat)…"
mkdir -p "$dest"
curl -fSL "$url" -o "$dest/keymd"
chmod +x "$dest/keymd"
echo "installed: $dest/keymd"

case ":$PATH:" in
  *":$dest:"*) ;;
  *) echo "note: add it to PATH →  export PATH=\"$dest:\$PATH\"" ;;
esac
echo "try:  keymd run -- claude"
