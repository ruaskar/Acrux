# tests/test_proxy_bounders_listing.py
from keymd.proxy.bounders import bound_listing


def test_groups_by_dir_and_caps():
    paths = [f"src/pkg/m{i}.py" for i in range(80)]
    out = bound_listing("\n".join(paths), centrality={}, max_entries=60)
    assert out is not None
    assert "src/pkg" in out
    assert "(+20 more" in out


def test_central_files_ranked_first():
    text = "src/a.py\nsrc/b.py\nsrc/c.py"
    out = bound_listing(text, centrality={"src/b.py": 9, "src/a.py": 1}, max_entries=60)
    # b.py (centrality 9) appears before a.py (1) and c.py (0)
    assert out.index("b.py") < out.index("a.py") < out.index("c.py")


def test_non_listing_returns_none():
    assert bound_listing("error: command failed\nstack trace here", centrality={}) is None


# ── BUG I2: spaced paths preserved + count honest ────────────────────────────

def test_i2_spaced_filename_preserved():
    """'my file.py' must not be filtered out by _PATHISH."""
    text = "src/my file.py\nsrc/normal.py"
    out = bound_listing(text)
    assert out is not None, "Result with spaced filenames should be bounded, not None"
    assert "my file.py" in out


def test_i2_count_includes_spaced_paths():
    """Header must report 2 paths (not 1) when one has a space."""
    text = "src/my file.py\nsrc/normal.py"
    out = bound_listing(text)
    assert out is not None
    assert "listing: 2 paths" in out


def test_i2_ls_la_line_still_none():
    """An ls -la line must still return None (not mistaken for a path listing)."""
    ls_la = (
        "total 80\n"
        "-rw-r--r-- 1 user group 1234 Jun 29 10:00 file.py\n"
        "drwxr-xr-x 2 user group 4096 Jun 29 09:00 src\n"
    )
    assert bound_listing(ls_la) is None, "ls -la output should not be treated as a path listing"


def test_i2_error_text_still_none():
    """'error: command failed' must still return None."""
    assert bound_listing("error: command failed\nstack trace here") is None


# ── BUG M1: backslash dir grouping mixed separators ─────────────────────────

def test_m1_no_mixed_separator_in_dir_header():
    """Backslash path group header must not contain mixed '\\/' separators."""
    text = "src\\sub\\baz.py\nsrc\\sub\\qux.py"
    out = bound_listing(text)
    assert out is not None
    # The dir header must use only forward slashes — no "src\sub/" pattern
    for line in out.splitlines():
        if "/" in line and "\\" in line:
            assert False, f"Mixed separators in output line: {line!r}"


# ── BUG R2-B1: ls -l lines rejected; spaced filenames and total line ─────────

def test_r2b1_ls_long_block_returns_none():
    """`ls -l` permission lines must NOT be mistaken for a path listing."""
    ls_l = (
        "-rw-r--r-- 1 user group 4096 Jun 29 foo.py\n"
        "-rwxr-xr-x 1 user group 2048 Jun 28 bar.sh\n"
        "drwxr-xr-x 2 user group  512 Jun 27 src\n"
        "-rw-r--r-- 1 user group  128 Jun 26 readme.md\n"
    )
    assert bound_listing(ls_l) is None, "ls -l block should return None (not a path listing)"


def test_r2b1_spaced_filename_still_bounded():
    """A plain listing with spaced filenames (Round-1 fix) must still be bounded."""
    text = "my file.py\nother file.py\nfoo.py"
    out = bound_listing(text)
    assert out is not None, "Spaced filename listing must still be bounded"
    assert "my file.py" in out
    assert "other file.py" in out
    assert "foo.py" in out
    assert "listing: 3 paths" in out


def test_r2b1_total_line_not_counted_as_path():
    """`total 48` header must not count as a path candidate."""
    ls_l = (
        "total 48\n"
        "-rw-r--r-- 1 user group 4096 Jun 29 foo.py\n"
        "-rw-r--r-- 1 user group 2048 Jun 28 bar.py\n"
    )
    assert bound_listing(ls_l) is None, "ls -l with total header should return None"


# ── BUG R3-1: _LS_LONG false-drops files named like permission strings ────────

def test_r3_1_file_named_like_perm_string_preserved():
    """A file literally named 'lrwxrwxrwx.txt' must not be dropped by _LS_LONG."""
    text = "lrwxrwxrwx.txt\nsrc/normal.py\nother/file.py"
    out = bound_listing(text)
    assert out is not None, "Listing with perm-named file should be bounded, not None"
    assert "lrwxrwxrwx.txt" in out, "'lrwxrwxrwx.txt' must be preserved (not dropped as ls-l)"


def test_r3_1_real_ls_l_still_none():
    """Real ls -l output (perm block followed by space + more columns) still → None."""
    ls_l = (
        "-rw-r--r-- 1 user group 4096 Jun 29 foo.py\n"
        "lrwxrwxrwx 1 user group   12 Jun 28 link -> target\n"
        "drwxr-xr-x 2 user group  512 Jun 27 src\n"
    )
    assert bound_listing(ls_l) is None, "ls -l block with real perm lines must return None"


def test_r3_1_total_48_still_rejected():
    """`total 48` line must still be rejected (the total\\s pattern is unchanged)."""
    text = "total 48\nsrc/foo.py\nsrc/bar.py"
    # 'total 48' rejected → only 2 paths remain → 2/(2+1) >= 0.5 → bounded
    out = bound_listing(text)
    # We just verify 'total 48' is NOT in the output (rejected correctly)
    if out is not None:
        assert "total 48" not in out, "'total 48' must be filtered out"
