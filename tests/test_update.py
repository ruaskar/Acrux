"""`keymd update` — uv-style self-update of the binary from GitHub Releases."""
import os

import pytest

from keymd import update as up


# --- pure logic -------------------------------------------------------------

@pytest.mark.parametrize("system,machine,expected", [
    ("Linux", "x86_64", "keymd-linux-x86_64"),
    ("Linux", "AMD64", "keymd-linux-x86_64"),
    ("Darwin", "arm64", "keymd-macos-aarch64"),
    ("Darwin", "aarch64", "keymd-macos-aarch64"),
    ("Darwin", "x86_64", "keymd-macos-x86_64"),
    ("Windows", "AMD64", "keymd-windows-x86_64.exe"),
    ("Linux", "armv7l", None),        # unsupported
])
def test_asset_name_matches_release_names(system, machine, expected):
    assert up.asset_name(system, machine) == expected


def test_is_newer():
    assert up.is_newer("0.2.0", "0.1.0")
    assert up.is_newer("v0.1.1", "0.1.0")        # v-prefix tolerated
    assert not up.is_newer("0.1.0", "0.1.0")
    assert not up.is_newer("0.1.0", "0.2.0")
    assert up.is_newer("1.0.0", "0.9.9")


def test_ver_tuple_tolerates_prefix_and_suffix():
    assert up._ver_tuple("v1.2.3") == (1, 2, 3)
    assert up._ver_tuple("1.2.3-rc1") == (1, 2, 3)
    assert up._ver_tuple("1.2.3+build") == (1, 2, 3)


def test_binary_path_reads_pyapp(tmp_path, monkeypatch):
    exe = tmp_path / "keymd"; exe.write_text("x", encoding="utf-8")
    monkeypatch.setenv("PYAPP", str(exe))
    assert up.binary_path() == str(exe)
    monkeypatch.setenv("PYAPP", "1")              # built without pass-location
    assert up.binary_path() is None
    monkeypatch.delenv("PYAPP", raising=False)
    assert up.binary_path() is None


# --- atomic replace (both OS branches, exercised on whatever host runs) ------

def _replace_case(tmp_path, force_nt):
    # Pass windows= explicitly — never mutate the global os.name (it breaks pathlib).
    target = tmp_path / "keymd.exe"; target.write_text("OLD", encoding="utf-8")
    new = tmp_path / "dl" / "keymd.exe"; new.parent.mkdir(); new.write_text("NEW", encoding="utf-8")
    up.replace_binary(str(target), str(new), windows=force_nt)
    return target


def test_replace_windows_branch_moves_old_aside(tmp_path):
    target = _replace_case(tmp_path, True)
    assert target.read_text(encoding="utf-8") == "NEW"
    assert (tmp_path / "keymd.exe.old").read_text(encoding="utf-8") == "OLD"


def test_replace_posix_branch_swaps_in_place(tmp_path):
    target = _replace_case(tmp_path, False)
    assert target.read_text(encoding="utf-8") == "NEW"
    assert not (tmp_path / "keymd.exe.old").exists()


# --- update() orchestration (network + replace injected) --------------------

def _bin(tmp_path, monkeypatch):
    exe = tmp_path / "keymd"; exe.write_text("OLD", encoding="utf-8")
    monkeypatch.setenv("PYAPP", str(exe))
    return exe


def test_update_up_to_date_does_nothing(tmp_path, monkeypatch, capsys):
    _bin(tmp_path, monkeypatch)
    called = {"dl": 0, "rp": 0}
    rc = up.update(_latest=lambda repo: ("v" + up.current_version(), up.current_version()),
                   _download_fn=lambda *a, **k: called.__setitem__("dl", 1),
                   _replace=lambda *a: called.__setitem__("rp", 1))
    assert rc == 0 and "up to date" in capsys.readouterr().out
    assert called == {"dl": 0, "rp": 0}           # no download, no replace


def test_update_downloads_and_replaces_when_newer(tmp_path, monkeypatch, capsys):
    exe = _bin(tmp_path, monkeypatch)
    seen = {}

    def fake_dl(url, dest, **k):
        seen["url"] = url
        from pathlib import Path
        Path(dest).write_bytes(b"NEWBINARY")
    rc = up.update(_latest=lambda repo: ("v9.9.9", "9.9.9"),
                   _download_fn=fake_dl,
                   _verify=lambda *a, **k: True,
                   _replace=lambda t, n: seen.__setitem__("replaced", (t, n)))
    assert rc == 0
    assert "9.9.9" in seen["url"] and seen["replaced"][0] == str(exe)
    assert "updated keymd to v9.9.9" in capsys.readouterr().out


def test_update_refuses_without_binary(monkeypatch, capsys):
    monkeypatch.delenv("PYAPP", raising=False)
    rc = up.update(_latest=lambda repo: ("v9.9.9", "9.9.9"))
    assert rc == 1 and "binary distribution" in capsys.readouterr().out


def test_update_check_only_reports_without_binary(monkeypatch, capsys):
    monkeypatch.delenv("PYAPP", raising=False)            # --check works even via pip
    rc = up.update(check_only=True, _latest=lambda repo: ("v9.9.9", "9.9.9"))
    assert rc == 0 and "update available" in capsys.readouterr().out


class _Resp:
    def __init__(self, data): self._d = data
    def read(self): return self._d
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _fake_opener(data):
    return lambda req, timeout=None: _Resp(data)


def test_verify_checksum_match(tmp_path):
    import hashlib
    f = tmp_path / "keymd-linux-x86_64"; f.write_bytes(b"hello")
    sums = f"{hashlib.sha256(b'hello').hexdigest()}  keymd-linux-x86_64\n".encode()
    assert up.verify_checksum("r/r", "v1", "keymd-linux-x86_64", f, opener=_fake_opener(sums)) is True


def test_verify_checksum_mismatch_fails(tmp_path):
    f = tmp_path / "keymd-linux-x86_64"; f.write_bytes(b"hello")
    sums = b"deadbeefdeadbeef  keymd-linux-x86_64\n"
    assert up.verify_checksum("r/r", "v1", "keymd-linux-x86_64", f, opener=_fake_opener(sums)) is False


def test_verify_checksum_missing_asset_fails_closed(tmp_path):
    f = tmp_path / "keymd-linux-x86_64"; f.write_bytes(b"hello")
    sums = b"abc123  some-other-file\n"          # our asset not listed
    assert up.verify_checksum("r/r", "v1", "keymd-linux-x86_64", f, opener=_fake_opener(sums)) is False


def test_verify_checksum_fetch_error_fails_closed(tmp_path):
    f = tmp_path / "keymd-linux-x86_64"; f.write_bytes(b"hello")
    def boom(req, timeout=None): raise OSError("no net")
    assert up.verify_checksum("r/r", "v1", "keymd-linux-x86_64", f, opener=boom) is False


def test_update_aborts_on_checksum_mismatch(tmp_path, monkeypatch, capsys):
    _bin(tmp_path, monkeypatch)
    rc = up.update(_latest=lambda repo: ("v9.9.9", "9.9.9"),
                   _download_fn=lambda url, dest, **k: __import__("pathlib").Path(dest).write_bytes(b"x"),
                   _verify=lambda *a, **k: False,         # tampered / unverifiable
                   _replace=lambda t, n: (_ for _ in ()).throw(AssertionError("must not replace")))
    assert rc == 1 and "checksum verification failed" in capsys.readouterr().out.lower()


def test_update_survives_network_error(tmp_path, monkeypatch, capsys):
    _bin(tmp_path, monkeypatch)
    def boom(repo): raise OSError("no net")
    rc = up.update(_latest=boom)
    assert rc == 1 and "could not reach" in capsys.readouterr().out


def test_update_aborts_on_empty_download(tmp_path, monkeypatch, capsys):
    _bin(tmp_path, monkeypatch)
    rc = up.update(_latest=lambda repo: ("v9.9.9", "9.9.9"),
                   _download_fn=lambda url, dest, **k: __import__("pathlib").Path(dest).write_bytes(b""),
                   _replace=lambda t, n: (_ for _ in ()).throw(AssertionError("must not replace")))
    assert rc == 1 and "empty file" in capsys.readouterr().out
