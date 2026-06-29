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
