"""Tests for `keymd demo` — the zero-config before/after token-savings showcase.

The demo must: run on keymd's own source with no args, run on an explicit path,
degrade gracefully on a tiny/empty/missing corpus, leave NO artifacts behind, and
restore the caller's environment (it mutates KEYMD_PROJECT_ROOT / KEYMD_INDEX_PATH
on a throwaway index, then must put them back).
"""
import os
from pathlib import Path

from keymd import demo


def _big_py(n_defs: int) -> str:
    # A file comfortably over the gate so there is a real reduction to show.
    head = "import os\nimport sys\n\n"
    body = "".join(
        f"def func_{i}(a, b, c):\n"
        f'    """Function number {i} doing some work."""\n'
        f"    x = a + b + c\n"
        f"    y = x * {i}\n"
        f"    return y\n\n"
        for i in range(n_defs)
    )
    return head + body


def test_demo_own_source_returns_zero(capsys):
    rc = demo.run_demo(None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "fewer lines" in out
    # ran on keymd's own package
    assert "keymd" in out.lower()


def test_demo_leaves_no_artifacts(tmp_path, capsys):
    # running on an explicit corpus must not write a .keymd into it
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "big.py").write_text(_big_py(40), encoding="utf-8")
    rc = demo.run_demo(str(proj))
    capsys.readouterr()
    assert rc == 0
    assert not (proj / ".keymd").exists(), "demo left an index behind in the corpus"


def test_demo_explicit_path_shows_spotlight_and_aggregate(tmp_path, capsys):
    proj = tmp_path / "repo"
    proj.mkdir()
    (proj / "big.py").write_text(_big_py(50), encoding="utf-8")
    rc = demo.run_demo(str(proj))
    out = capsys.readouterr().out
    assert rc == 0
    assert "big.py" in out                 # spotlight names the largest file
    assert "Spotlight" in out
    assert "without keymd" in out and "with keymd" in out


def test_demo_tiny_corpus_is_friendly(tmp_path, capsys):
    proj = tmp_path / "tiny"
    proj.mkdir()
    (proj / "small.py").write_text("x = 1\n", encoding="utf-8")
    rc = demo.run_demo(str(proj))
    out = capsys.readouterr().out
    assert rc == 0                         # not a crash
    assert "too small" in out.lower() or "meaningful" in out.lower()


def test_demo_missing_path_returns_one(tmp_path, capsys):
    rc = demo.run_demo(str(tmp_path / "does_not_exist"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "not found" in out.lower() or "not a directory" in out.lower()


def test_demo_restores_environment(tmp_path, capsys):
    proj = tmp_path / "repo"
    proj.mkdir()
    (proj / "big.py").write_text(_big_py(30), encoding="utf-8")
    os.environ["KEYMD_PROJECT_ROOT"] = "SENTINEL_ROOT"
    os.environ["KEYMD_INDEX_PATH"] = "SENTINEL_INDEX"
    try:
        demo.run_demo(str(proj))
        capsys.readouterr()
        assert os.environ.get("KEYMD_PROJECT_ROOT") == "SENTINEL_ROOT"
        assert os.environ.get("KEYMD_INDEX_PATH") == "SENTINEL_INDEX"
    finally:
        os.environ.pop("KEYMD_PROJECT_ROOT", None)
        os.environ.pop("KEYMD_INDEX_PATH", None)
