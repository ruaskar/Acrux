from pathlib import Path

from keymd.engine import config, index, refresh
import keymd.engine.parsers.python  # noqa: F401


def test_refresh_creates_and_is_idempotent(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    key = Path(parser_py[:-3] + ".key.md")
    try:
        assert refresh.refresh_one(parser_py) is True            # created
        assert key.exists()
        assert "def parse_header(buf: bytes) -> dict" in key.read_text(encoding="utf-8")
        assert refresh.refresh_one(parser_py) is False           # no content change
    finally:
        key.unlink(missing_ok=True)
        Path(str(key) + ".tmp").unlink(missing_ok=True)


def test_refresh_rejects_outside_root(env_proj, tmp_path):
    outside = tmp_path / "x.py"
    outside.write_text("def f(): pass\n", encoding="utf-8")
    assert refresh.refresh_one(str(outside)) is False


def test_refresh_with_relative_path_populates(env_proj):
    # Regression: a RELATIVE path must resolve to the index's absolute key, not
    # render an empty sidecar (dogfood bug — fixture-only tests passed abs paths).
    import os
    index.build(verbose=False)
    abs_py = str(Path(env_proj) / "pkg" / "parser.py")
    rel_py = os.path.relpath(abs_py, os.getcwd())
    key = Path(abs_py[:-3] + ".key.md")
    try:
        assert refresh.refresh_one(rel_py) is True
        text = key.read_text(encoding="utf-8")
        assert "def parse_header(buf: bytes) -> dict" in text  # not an empty render
        assert "[python ·" in text
    finally:
        key.unlink(missing_ok=True)
        Path(str(key) + ".tmp").unlink(missing_ok=True)
