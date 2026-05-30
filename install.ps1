# keymd installer (Windows) — downloads the prebuilt binary from GitHub Releases.
#   irm https://raw.githubusercontent.com/ruaskar/keymd/master/install.ps1 | iex
#
# No Python/pip needed. Override the location with $env:KEYMD_INSTALL_DIR.
$ErrorActionPreference = "Stop"

$repo = "ruaskar/keymd"
$dest = if ($env:KEYMD_INSTALL_DIR) { $env:KEYMD_INSTALL_DIR } else { "$env:LOCALAPPDATA\keymd\bin" }

Write-Host "resolving latest release..."
$tag = (Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest").tag_name
if (-not $tag) { throw "could not resolve a release (none published yet?)" }

$url = "https://github.com/$repo/releases/download/$tag/keymd-windows-x86_64.exe"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Write-Host "downloading keymd $tag (windows-x86_64)..."
Invoke-WebRequest -Uri $url -OutFile "$dest\keymd.exe"
Write-Host "installed: $dest\keymd.exe"

if ($env:Path -notlike "*$dest*") {
  Write-Host "note: add it to PATH -> $dest"
}
Write-Host "try:  keymd run -- claude"
