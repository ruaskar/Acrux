"""Phase B2: PDF + DOCX binary documents — text extraction cache, ToC, ranged reads.

Skips cleanly when the optional `docs` extra (pypdf / python-docx) is absent.
"""
import shutil
from pathlib import Path

import pytest

from keymd.engine import config, db, index
from keymd.engine.keymd_render import render_keymd
from keymd.proxy import engine

FIXTURES = Path(__file__).parent / "fixtures"


def test_build_sections_never_inverts_on_shared_line():
    # two bookmarks pointing at the same page share a line; the span must not invert
    from keymd.engine.parsers.base import build_sections
    syms = build_sections([(1, "A", 5), (1, "B", 5)], 10)
    for s in syms:
        assert s.end_line >= s.line


def _proj(monkeypatch, tmp_path):
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()


def _toc(ap):
    con = db.connect(config.index_path())
    try:
        return render_keymd(con, ap)
    finally:
        con.close()


def _cached(ap):
    con = db.connect(config.index_path())
    try:
        row = con.execute("SELECT text FROM doc_text WHERE path=?", (ap,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


# ---------------------------------------------------------------- DOCX --------
def test_docx_sections_cache_and_reads(monkeypatch, tmp_path):
    docxlib = pytest.importorskip("docx")
    d = docxlib.Document()
    d.add_heading("Introduction", level=1)
    d.add_paragraph("intro paragraph text")
    d.add_heading("Methods", level=1)
    d.add_paragraph("methods paragraph text")
    d.add_heading("Details", level=2)
    d.add_paragraph("nested detail text")
    path = tmp_path / "report.docx"
    d.save(str(path))

    _proj(monkeypatch, tmp_path)
    index.build(verbose=False)
    ap = engine.canon(str(path))

    assert "methods paragraph text" in (_cached(ap) or "")     # extracted + cached
    toc = _toc(ap)
    assert "sections" in toc and "Introduction" in toc and "Methods" in toc
    assert "# L" in toc                                          # anchors present
    # ranged section read serves the EXTRACTED text (not the binary)
    assert "methods paragraph text" in engine.read_symbol(ap, "Methods")
    assert "intro paragraph text" in engine.read_symbol(ap, "Introduction")
    # a binary doc cannot be edited as text
    assert "binary document" in engine.edit(ap, "intro paragraph text", "x")


# ---------------------------------------------------------------- PDF ---------
def test_pdf_outline_sections(monkeypatch, tmp_path):
    pytest.importorskip("pypdf")
    src = FIXTURES / "sample.pdf"
    if not src.exists():
        pytest.skip("sample.pdf fixture missing")
    path = tmp_path / "sample.pdf"
    shutil.copy(src, path)

    _proj(monkeypatch, tmp_path)
    index.build(verbose=False)
    ap = engine.canon(str(path))

    toc = _toc(ap)
    for sect in ("Introduction", "Methods", "Results"):
        assert sect in toc
    assert "# L" in toc
    assert "introduction section" in engine.read_symbol(ap, "Introduction").lower()
    assert "binary document" in engine.edit(ap, "Results", "x")


def test_pdf_without_outline_falls_back_to_pages(monkeypatch, tmp_path):
    pytest.importorskip("pypdf")
    src = FIXTURES / "sample_plain.pdf"
    if not src.exists():
        pytest.skip("sample_plain.pdf fixture missing")
    path = tmp_path / "plain.pdf"
    shutil.copy(src, path)

    _proj(monkeypatch, tmp_path)
    index.build(verbose=False)
    toc = _toc(engine.canon(str(path)))
    assert "Page 1" in toc and "Page 2" in toc       # per-page fallback
