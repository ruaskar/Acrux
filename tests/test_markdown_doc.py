"""Phase B1: Markdown documents get a Table-of-Contents summary + section anchors."""
import pytest

from keymd.engine import config, db, index
from keymd.engine.keymd_render import render_keymd
from keymd.engine.parsers.markdown import MarkdownParser
from keymd.proxy import engine

MD = """# Title

intro text

## Installation

install stuff

```bash
# this is a code comment, not a heading
echo hi
```

## Usage

usage text

### Advanced

advanced text

## Installation

duplicate heading
"""  # 24 lines


@pytest.fixture
def doc_proj(monkeypatch, tmp_path):
    (tmp_path / "doc.md").write_text(MD, encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    index.build(verbose=False)
    return tmp_path


def _md(root):
    return engine.canon(str(root / "doc.md"))


# --- parser ----------------------------------------------------------------
def test_parser_sections_spans_fence_and_dedupe(tmp_path):
    p = tmp_path / "d.md"
    p.write_text(MD, encoding="utf-8")
    syms = {s.name: s for s in MarkdownParser().parse(p).symbols}
    assert set(syms) == {"Title", "Installation", "Usage", "Advanced",
                         "Installation #2"}          # duplicate heading deduped
    assert syms["Installation"].line == 5 and syms["Installation"].end_line == 13
    assert syms["Title"].end_line == 24              # top section spans to EOF
    assert syms["Advanced"].line == 18               # nested under Usage
    # a `#` inside the fenced code block is NOT a section
    assert not any("comment" in n for n in syms)


def test_mismatched_fence_markers_do_not_leak(tmp_path):
    # a ``` block containing a ~~~ line must NOT close early (~~~ ≠ ```), so the
    # `#` inside stays code, not a heading.
    p = tmp_path / "f.md"
    p.write_text("# Real\n\n```\n~~~\n# not a heading\n```\n\n## After\n\ntext\n",
                 encoding="utf-8")
    names = {s.name for s in MarkdownParser().parse(p).symbols}
    assert names == {"Real", "After"}


# --- ToC render -------------------------------------------------------------
def test_render_is_a_toc_with_anchors(doc_proj):
    con = db.connect(config.index_path())
    text = render_keymd(con, _md(doc_proj))
    con.close()
    assert "sections:" in text
    assert "# L5-13" in text                          # Installation span anchor
    assert "Installation" in text and "Usage" in text
    assert "api:" not in text and "called_by:" not in text   # not the code layout


# --- ranged reads work on doc sections (Phase A reuse) ----------------------
def test_read_range_and_symbol_pull_a_section(doc_proj):
    ap = _md(doc_proj)
    assert "install stuff" in engine.read_range(ap, 5, 13)
    assert "install stuff" in engine.read_symbol(ap, "Installation")
    assert "advanced text" not in engine.read_symbol(ap, "Installation")


# --- keymd's own sidecars must NOT be indexed as documents ------------------
def test_key_md_sidecars_not_indexed_as_docs(doc_proj):
    (doc_proj / "foo.key.md").write_text("# Not A Doc\n", encoding="utf-8")
    index.build(verbose=False)
    con = db.connect(config.index_path())
    n = con.execute("SELECT COUNT(*) FROM files WHERE path LIKE '%foo.key.md'").fetchone()[0]
    con.close()
    assert n == 0
