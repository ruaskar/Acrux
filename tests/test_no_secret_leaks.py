"""Registry-wide secret-leak conformance test.

keymd's core security guarantee: a hardcoded string VALUE (a credential) must
NEVER reach a summary surface — not a Symbol signature, not an edge target, not
extracted document text — for ANY registered parser. The Python parser enforces
this structurally (it emits string values as `<str>`); this test proves the same
holds for every OTHER registered language, and FAILS if a new parser is added
without leak coverage (so "add a parser" can't silently mean "add a leak").

It runs each REAL registered parser over a fixture whose every string literal is
an unmistakable secret token, then asserts no token survives in any output field.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import keymd.engine.parsers  # noqa: F401  (registers every available parser)
from keymd.engine import config
from keymd.engine.parsers.base import get_parser_for

# Distinct, unmistakable credential tokens. Assertions check these INNER tokens
# (not full URLs), since a credentialed-URL scrub may legitimately leave the host.
API = "sk-ant-api03-DEADBEEFcafe1234567890XY"
CRED = "S3cretPwLeak"
GH = "ghp_ABCDEF0123456789abcdef0123456789ZZ"
SECRETS = (API, CRED, GH)

# Code source embedding secrets in every channel a code parser can emit:
#   - function / method / arrow parameter DEFAULTS  (the #18-class leak)
#   - a credentialed import specifier                (the edge-target channel)
_JS = (
    f'import client from "https://user:{CRED}@registry.host/m.js";\n'
    f'export function connect(url = "postgres://admin:{CRED}@db:5432/prod") {{\n'
    "  return client(url);\n"
    "}\n"
    f'const auth = (apiKey = "{API}") => apiKey;\n'
    "class C {\n"
    f'  send(token = "{GH}") {{ return token; }}\n'
    "}\n"
)
_TS = (
    f'export function connect(url: string = "postgres://admin:{CRED}@db:5432/prod"): string {{\n'
    "  return url;\n"
    "}\n"
    f'const auth = (apiKey: string = "{API}"): string => apiKey;\n'
)
_PY = (
    "from typing import Literal\n"
    f'API_KEY = "{API}"\n'
    f'def connect(url="postgres://admin:{CRED}@db:5432/prod"):\n'
    "    return url\n"
    f'def mode(m: Literal["{CRED}"]) -> None: ...\n'   # secret inside a type annotation
    "from dataclasses import dataclass\n"
    "@dataclass\n"
    "class Cfg:\n"
    f'    token: str = "{GH}"\n'
)
_MD = (
    f"# Config with {API}\n\n"
    f"Connect using postgres://admin:{CRED}@db:5432/prod for the database.\n"
)

# ext -> (filename, source) for the text-source parsers
_CODE_FIXTURES = {
    ".py": ("m.py", _PY),
    ".js": ("m.js", _JS),
    ".jsx": ("m.jsx", _JS),
    ".mjs": ("m.mjs", _JS),
    ".cjs": ("m.cjs", _JS),
    ".ts": ("m.ts", _TS),
    ".tsx": ("m.tsx", _TS),
    ".md": ("m.md", _MD),
}

# Parsers gated behind optional extras: skip (don't fail) when the extra is absent,
# but the coverage assertion below still counts them as "addressed".
_OPTIONAL = {
    ".js": "tree_sitter_javascript",
    ".jsx": "tree_sitter_javascript",
    ".mjs": "tree_sitter_javascript",
    ".cjs": "tree_sitter_javascript",
    ".ts": "tree_sitter_typescript",
    ".tsx": "tree_sitter_typescript",
    ".pdf": "pypdf",
    ".docx": "docx",
}


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def _leaks(parser, path: Path) -> list[str]:
    """Return the list of secret tokens that leaked into any output field."""
    r = parser.parse(path)
    blob = "\n".join(
        [s.signature or "" for s in r.symbols]
        + [s.name or "" for s in r.symbols]
        + [e.to_name or "" for e in r.edges]
        + [r.text or ""]
    )
    return [sec for sec in SECRETS if sec in blob]


@pytest.mark.parametrize("ext", sorted(_CODE_FIXTURES))
def test_text_source_parser_hides_secret_values(ext, tmp_path):
    mod = _OPTIONAL.get(ext)
    if mod and not _has(mod):
        pytest.skip(f"{mod} not installed")
    name, src = _CODE_FIXTURES[ext]
    f = tmp_path / name
    f.write_text(src, encoding="utf-8")
    parser = get_parser_for(f)
    assert parser is not None, f"no parser registered for {ext}"
    leaked = _leaks(parser, f)
    assert not leaked, f"{ext} parser leaked secret value(s): {leaked}"


def test_docx_hides_secret_values(tmp_path):
    docxlib = pytest.importorskip("docx")
    d = docxlib.Document()
    d.add_heading(f"Overview {API}", level=1)
    d.add_paragraph(f"Connect with postgres://admin:{CRED}@db:5432/prod here.")
    f = tmp_path / "report.docx"
    d.save(str(f))
    parser = get_parser_for(f)
    assert parser is not None
    leaked = _leaks(parser, f)
    assert not leaked, f"docx parser leaked secret value(s): {leaked}"


def test_pdf_hides_secret_values(tmp_path):
    pytest.importorskip("pypdf")
    rc = pytest.importorskip("reportlab.pdfgen.canvas")
    f = tmp_path / "doc.pdf"
    c = rc.Canvas(str(f))
    c.drawString(72, 800, f"Overview {API}")
    c.drawString(72, 770, f"db postgres://admin:{CRED}@db:5432/prod end")
    c.showPage()
    c.save()
    parser = get_parser_for(f)
    assert parser is not None
    leaked = _leaks(parser, f)
    assert not leaked, f"pdf parser leaked secret value(s): {leaked}"


def test_every_registered_extension_has_leak_coverage():
    """The kernel of D: a parser cannot enter the registry without this test
    exercising it. If a new extension is registered but not covered by a fixture
    above, this fails — forcing a leak test for the new surface."""
    covered = set(_CODE_FIXTURES) | {".pdf", ".docx"}
    registered = set(config.index_extensions())
    uncovered = registered - covered
    assert not uncovered, (
        f"registered parser extension(s) {sorted(uncovered)} have no secret-leak "
        f"coverage in test_no_secret_leaks.py — add a fixture so the no-leak "
        f"guarantee is proven for them"
    )


def test_docstring_secret_is_redacted(tmp_path):
    """A keyworded secret in a module docstring must not reach the summary lead."""
    from keymd.engine.parsers.python import PythonParser
    f = tmp_path / "leaky.py"
    f.write_text('"""Connects with api_key=sk-ant-SECRETSECRETSECRET123456."""\ndef go(): pass\n',
                 encoding="utf-8")
    r = PythonParser().parse(f)
    doc = {s.name: s for s in r.symbols}["<module>"]
    assert "sk-ant-SECRETSECRETSECRET123456" not in doc.signature   # keyworded -> redacted
    assert "<redacted>" in doc.signature


def test_docstring_bare_opaque_blob_redacted(tmp_path):
    """No keyword, just a long opaque token -- caught by the parser's opaque=True pass,
    which runs BEFORE __post_init__'s opaque=False. Proves the stronger bar for docstrings."""
    from keymd.engine.parsers.python import PythonParser
    f = tmp_path / "blob.py"
    f.write_text('"""Default token deadbeef0123456789abcdef0123456789abcdef00 used here."""\n'
                 'def go(): pass\n', encoding="utf-8")
    r = PythonParser().parse(f)
    sig = {s.name: s for s in r.symbols}["<module>"].signature
    assert "deadbeef0123456789abcdef0123456789abcdef00" not in sig
    assert "<redacted>" in sig
