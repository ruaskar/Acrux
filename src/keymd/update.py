"""update.py — `keymd update`: self-update the binary from GitHub Releases.

Only meaningful for the PyApp binary distribution. The launcher passes its own
absolute path in $PYAPP (the binary is built with PYAPP_PASS_LOCATION=1); we look
up the latest release, download this platform's asset, and atomically swap it in.
pip/uvx installs update via their package manager, not this command.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import urllib.request
from pathlib import Path

REPO = "ruaskar/keymd"
_API = "https://api.github.com/repos/{repo}/releases/latest"
_ASSET = "https://github.com/{repo}/releases/download/{tag}/{asset}"


def current_version() -> str:
    from keymd import __version__
    return __version__


def asset_name(system: str | None = None, machine: str | None = None) -> str | None:
    """Map the running platform to its release asset name — must match the names the
    CI workflow uploads and install.sh/ps1 download. None = unsupported platform."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if system == "linux" and machine in ("x86_64", "amd64"):
        return "keymd-linux-x86_64"
    if system == "darwin":
        return "keymd-macos-aarch64" if machine in ("arm64", "aarch64") else "keymd-macos-x86_64"
    if system == "windows" and machine in ("amd64", "x86_64"):
        return "keymd-windows-x86_64.exe"
    return None


def _ver_tuple(v: str) -> tuple:
    v = v.lstrip("vV").split("+")[0].split("-")[0]
    out = []
    for part in v.split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def is_newer(latest: str, current: str) -> bool:
    return _ver_tuple(latest) > _ver_tuple(current)


def binary_path() -> str | None:
    """Absolute path of the running PyApp launcher (via PYAPP_PASS_LOCATION). None
    when not running as the binary (pip/uvx), or built without pass-location ($PYAPP
    is then just '1')."""
    p = os.environ.get("PYAPP")
    if p and p not in ("0", "1") and Path(p).exists():
        return p
    return None


def latest_release(repo: str = REPO, *, opener=urllib.request.urlopen) -> tuple[str, str]:
    """(tag, version) of the latest GitHub release. Network."""
    req = urllib.request.Request(
        _API.format(repo=repo),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "keymd-update"})
    with opener(req, timeout=30) as r:
        data = json.load(r)
    tag = data["tag_name"]
    return tag, tag.lstrip("vV")


def _download(url: str, dest: Path, *, opener=urllib.request.urlopen) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "keymd-update"})
    with opener(req, timeout=300) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def verify_checksum(repo: str, tag: str, asset: str, path: Path,
                    *, opener=urllib.request.urlopen) -> bool:
    """Verify `path` against the asset's SHA256 in the release's SHA256SUMS file.
    Fail-CLOSED: returns False if the sums file (or the asset's line) can't be
    fetched/parsed — we never install a binary we couldn't verify. This catches
    corruption / CDN tampering; it does NOT defend against a compromised release
    (that needs cryptographic signing — a deferred, cert-dependent step)."""
    url = _ASSET.format(repo=repo, tag=tag, asset="SHA256SUMS")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "keymd-update"})
        with opener(req, timeout=60) as r:
            sums = r.read().decode("utf-8", "replace")
    except Exception:
        return False
    want = None
    for line in sums.splitlines():
        parts = line.split()                       # "<hex>  <name>" or "<hex> *<name>"
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset:
            want = parts[0].lower()
            break
    return bool(want) and _sha256(path) == want


def replace_binary(target: str, new: str, *, windows: bool | None = None) -> None:
    """Atomically replace the (possibly running) binary at `target` with `new`.
    A running .exe can't be overwritten on Windows, so move it aside first; on
    POSIX, copy the old mode bits onto the new file and os.replace (atomic).
    `windows` is the branch selector (defaults to the host); pass it explicitly in
    tests rather than mutating the global os.name (which would break pathlib)."""
    if windows is None:
        windows = os.name == "nt"
    target_p, new_p = Path(target), Path(new)
    if windows:
        old = target_p.with_name(target_p.name + ".old")
        try:
            if old.exists():
                old.unlink()
        except OSError:
            pass
        os.replace(target_p, old)        # rename the running exe aside (allowed on Windows)
        try:
            os.replace(new_p, target_p)  # move the new one into place (same dir → atomic)
        except OSError:
            os.replace(old, target_p)    # restore on failure — never leave target missing
            raise
        # the .old can't be deleted while it's still mapped; leave it for next run
    else:
        mode = os.stat(target_p).st_mode
        os.chmod(new_p, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(new_p, target_p)      # atomic — new_p lives in target's directory


def update(repo: str = REPO, *, check_only: bool = False,
           _latest=latest_release, _download_fn=_download,
           _verify=verify_checksum, _replace=replace_binary) -> int:
    cur = current_version()
    target = binary_path()
    if target is None and not check_only:
        print("keymd update only updates the binary distribution — this looks like a "
              "pip/uvx install; update it with your package manager.")
        return 1
    try:
        tag, latest = _latest(repo)
    except Exception as e:                # network / API / parse — never crash
        print(f"keymd update: could not reach GitHub Releases ({e}).")
        return 1
    if not is_newer(latest, cur):
        print(f"keymd is up to date (v{cur}).")
        return 0
    print(f"update available: v{cur} -> {tag}")
    if check_only:
        return 0
    asset = asset_name()
    if asset is None:
        print(f"keymd update: no prebuilt binary for {platform.system()}/{platform.machine()}.")
        return 1
    url = _ASSET.format(repo=repo, tag=tag, asset=asset)
    print(f"downloading {asset} ({tag})…")
    tmp = Path(target).parent / (asset + ".download")   # same fs as target → atomic replace
    try:
        _download_fn(url, tmp)
        if not tmp.exists() or tmp.stat().st_size == 0:
            print("keymd update: downloaded an empty file; aborting (binary left untouched).")
            return 1
        if not _verify(repo, tag, asset, tmp):
            print("keymd update: checksum verification FAILED — refusing to install "
                  "(binary left untouched).")
            return 1
        _replace(target, str(tmp))
    except Exception as e:                # download / verify / replace — leave target intact
        print(f"keymd update: install failed ({e}); binary left untouched.")
        return 1
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    print(f"updated keymd to {tag} — restart any running keymd.")
    return 0
