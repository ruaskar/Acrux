# Acrux installer (Windows) — downloads the prebuilt `keymd` binary from GitHub Releases.
#   irm https://raw.githubusercontent.com/ruaskar/keymd/master/install.ps1 | iex
#
# No Python/pip needed. The project is Acrux; the command it installs is `keymd`.
#   $env:KEYMD_INSTALL_DIR=<dir>     install somewhere other than %LOCALAPPDATA%\keymd\bin
#   $env:KEYMD_NO_MODIFY_PATH=1      don't touch your user PATH (print steps instead)
$ErrorActionPreference = "Stop"

$repo = "ruaskar/keymd"
$dest = if ($env:KEYMD_INSTALL_DIR) { $env:KEYMD_INSTALL_DIR } else { "$env:LOCALAPPDATA\keymd\bin" }

# --- PATH configuration (pure helper, returns an action so it's testable) -----
# Decides what to do about PATH WITHOUT mutating anything. Returns one of:
#   @{ action = "already" }                 dir already on user PATH
#   @{ action = "manual";  newPath = ... }  opt-out / would-add (caller prints steps)
#   @{ action = "add";     newPath = ... }  caller should persist newPath
function Get-KeymdPathAction {
  param([string]$Dir, [string]$UserPath, [bool]$NoModify)
  $entries = @($UserPath -split ';' | Where-Object { $_ -ne '' })
  if ($entries -contains $Dir) { return @{ action = "already" } }
  $newPath = (@($entries + $Dir) -join ';')
  if ($NoModify) { return @{ action = "manual"; newPath = $newPath } }
  return @{ action = "add"; newPath = $newPath }
}

function Set-KeymdPath {
  param([string]$Dir)
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $noModify = ($env:KEYMD_NO_MODIFY_PATH -eq "1")
  $r = Get-KeymdPathAction -Dir $Dir -UserPath $userPath -NoModify $noModify
  switch ($r.action) {
    "already" { return }
    "manual"  {
      Write-Host "note: $Dir is not on your PATH. To use ``keymd``, add it:"
      Write-Host "  [Environment]::SetEnvironmentVariable('Path', '$Dir;' + `$env:Path, 'User')"
      return
    }
    "add" {
      [Environment]::SetEnvironmentVariable("Path", $r.newPath, "User")
      Write-Host "added $Dir to your user PATH"
      Write-Host "-> open a NEW terminal (or log out/in) for it to take effect"
    }
  }
}

# When dot-sourced by the test harness ($env:KEYMD_LIB_ONLY=1), stop here —
# expose the functions without downloading or installing anything.
if ($env:KEYMD_LIB_ONLY -eq "1") { return }

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

# Fix the PATH (the #1 first-run failure), don't just warn about it.
Set-KeymdPath -Dir $dest

Write-Host ""
Write-Host "try (in a code repo):"
Write-Host "  keymd graph                 # see your codebase as an interactive call-graph (no API key)"
Write-Host "  keymd run -- <your-agent>   # wire your agent through keymd: e.g. claude / codex / aider / cline"
