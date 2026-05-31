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

$base = "https://github.com/$repo/releases/download/$tag"
$asset = "keymd-windows-x86_64.exe"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$tmp = "$dest\keymd.exe.download"
Write-Host "downloading keymd $tag (windows-x86_64)..."
Invoke-WebRequest -Uri "$base/$asset" -OutFile $tmp

# Verify against the release's published SHA256SUMS BEFORE installing — never run
# an unverified native binary that will proxy your API key and edit your files.
Write-Host "verifying checksum..."
$sums = (Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS").Content
$line = ($sums -split "`n") | Where-Object { $_ -match "\s$([regex]::Escape($asset))\s*$" } | Select-Object -First 1
$want = if ($line) { ($line.Trim() -split '\s+')[0].ToLower() } else { $null }
if (-not $want) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue; throw "no checksum for $asset in SHA256SUMS — refusing to install" }
$got = (Get-FileHash $tmp -Algorithm SHA256).Hash.ToLower()
if ($want -ne $got) { Remove-Item $tmp -Force; throw "CHECKSUM MISMATCH (expected $want, got $got) — refusing to install" }
Write-Host "checksum OK"
Unblock-File $tmp   # strip Mark-of-the-Web so SmartScreen doesn't block first run
Move-Item -Force $tmp "$dest\keymd.exe"
Write-Host "installed: $dest\keymd.exe"

if ($env:Path -notlike "*$dest*") {
  Write-Host "note: add it to PATH -> $dest"
}
Write-Host "try:  keymd run -- claude"
