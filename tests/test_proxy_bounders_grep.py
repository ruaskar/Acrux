# tests/test_proxy_bounders_grep.py
from keymd.proxy.bounders import bound_grep


def test_clusters_by_file_and_preserves_matches():
    lines = []
    for n in range(1, 21):
        lines.append(f"src/a.py:{n}:def f{n}(): pass")
    lines.append("src/b.py:3:x = 1")
    out = bound_grep("\n".join(lines), per_file=5, max_files=40)
    assert out is not None
    assert "src/a.py" in out and "src/b.py" in out
    assert "(+15 more" in out          # 20 hits, 5 shown
    assert ":3:" in out or "3:" in out  # b.py's single match kept verbatim


def test_caps_file_count():
    lines = [f"f{i}.py:1:hit" for i in range(60)]
    out = bound_grep("\n".join(lines), per_file=8, max_files=40)
    assert "(+20 more files" in out


def test_non_grep_text_returns_none():
    assert bound_grep("just some prose\nwith no path:line: form") is None


def test_below_majority_parse_returns_none():
    mixed = "\n".join(["a.py:1:hit"] + ["random line"] * 10)
    assert bound_grep(mixed) is None     # <50% parse → not grep output


# ── BUG C1: Windows drive paths ─────────────────────────────────────────────

def test_c1_windows_backslash_path_parses():
    r"""C:\src\foo.py:10:hit must parse (path=C:\src\foo.py, line=10)."""
    out = bound_grep(r"C:\src\foo.py:10:hit")
    assert out is not None, "Windows backslash drive path should be bounded, not None"
    assert r"C:\src\foo.py" in out


def test_c1_windows_forward_slash_path_parses():
    """C:/src/foo.py:10:hit must also parse."""
    out = bound_grep("C:/src/foo.py:10:hit")
    assert out is not None, "Windows forward-slash drive path should be bounded, not None"
    assert "C:/src/foo.py" in out


def test_c1_posix_path_still_parses():
    """Posix paths must keep working after the regex change."""
    out = bound_grep("src/foo.py:10:hit")
    assert out is not None
    assert "src/foo.py" in out


# ── BUG C2: context lines defeat majority gate ───────────────────────────────

def test_c2_rg_context_lines_do_not_defeat_gate():
    """300 match lines + 600 rg -C2 context lines → must return a bounded string, not None."""
    lines = []
    for n in range(1, 301):
        lines.append(f"a.py:{n}:hit")        # match line
        lines.append(f"a.py-{n}-ctx before") # context line (dash separator)
        lines.append(f"a.py-{n}-ctx after")  # context line
    text = "\n".join(lines)
    out = bound_grep(text)
    assert out is not None, (
        "rg -C2 result with 300 matches + 600 context lines must be bounded, not None"
    )
    assert "a.py" in out


# ── BUG R2-B2: context-gate inflation (uncapped subtraction) ─────────────────

def test_r2b2_prose_context_lines_uncapped_returns_none():
    """1 real hit + 100 prose context-shaped lines → must be None (prose not excused)."""
    lines = ["a.py:1:hit"]
    for n in range(100):
        lines.append(f"note-{n}-text")   # matches _CONTEXT pattern but is prose
    text = "\n".join(lines)
    result = bound_grep(text)
    assert result is None, (
        "1 grep hit drowned by 100 prose-context lines must return None, not a bounded result"
    )


def test_r2b2_real_rg_c2_300_hits_still_bounded():
    """300 real grep hits + 600 rg -C2 context lines → still bounded (cap generous enough)."""
    lines = []
    for n in range(1, 301):
        lines.append(f"a.py:{n}:hit")
        lines.append(f"a.py-{n}-ctx before")
        lines.append(f"a.py-{n}-ctx after")
    text = "\n".join(lines)
    out = bound_grep(text)
    assert out is not None, (
        "300 hits + 600 real context lines (300*2 <= 300*10) must still be bounded"
    )
    assert "a.py" in out
