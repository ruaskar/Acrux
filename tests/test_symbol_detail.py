"""query.symbol_detail() — per-function detail behind the graph panel."""
import os

import keymd.engine.parsers.python  # noqa: F401
from keymd.engine import config, index, query


def _abs(rel):
    return config.canonical(os.path.join(str(config.project_root()), rel))


def test_callees_and_callers(env_proj):
    index.build(verbose=False)
    pipeline = _abs(os.path.join("pkg", "pipeline.py"))
    parser = _abs(os.path.join("pkg", "parser.py"))

    run = query.symbol_detail(pipeline, "run")
    assert run["name"] == "run"
    assert run["signature"].startswith("def run(")
    # downstream: run() calls parse_header, which lives cross-file in parser.py
    callee_files = {(c["name"], c["file"]) for c in run["callees"]}
    assert ("parse_header", os.path.join("pkg", "parser.py")) in callee_files

    ph = query.symbol_detail(parser, "parse_header")
    # upstream: parse_header is called from pipeline.py
    caller_files = {c["file"] for c in ph["callers"]}
    assert os.path.join("pkg", "pipeline.py") in caller_files


def test_leaf_name_resolves_to_method(env_proj):
    index.build(verbose=False)
    parser = _abs(os.path.join("pkg", "parser.py"))
    d = query.symbol_detail(parser, "parse")     # leaf → Parser.parse
    assert d["name"] == "Parser.parse"
    assert d["signature"].startswith("def parse(")


def test_symbol_detail_doc_extracted(monkeypatch, tmp_path):
    import keymd.engine.parsers.python  # noqa: F401
    proj = tmp_path / "proj"
    (proj / "pkg").mkdir(parents=True)
    (proj / "pkg" / "m.py").write_text(
        'def go(x: int) -> int:\n    """Double the input and return it."""\n    return x*2\n',
        encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(proj))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    index.build(verbose=False)
    d = query.symbol_detail(config.canonical(str(proj / "pkg" / "m.py")), "go")
    assert d["doc"] == "Double the input and return it."


def test_symbol_detail_missing(env_proj):
    index.build(verbose=False)
    parser = _abs(os.path.join("pkg", "parser.py"))
    assert query.symbol_detail(parser, "nonexistent_fn") == {"error": "symbol not found"}


def test_symbol_detail_no_index(monkeypatch, tmp_path):
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "nope.db"))
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    assert query.symbol_detail(str(tmp_path / "x.py"), "f") == {"error": "no index"}
