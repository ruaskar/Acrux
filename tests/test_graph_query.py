"""Tests for query.graph_data() — the pure read behind `keymd graph`."""
import os

import pytest

import keymd.engine.parsers.python  # noqa: F401  (registers the .py parser for build)
from keymd.engine import index, query


def test_graph_data_shape_and_edges(env_proj):
    index.build(verbose=False)
    data = query.graph_data()

    assert set(data) == {"nodes", "edges"}
    ids = {n["id"] for n in data["nodes"]}
    parser = os.path.join("pkg", "parser.py")
    pipeline = os.path.join("pkg", "pipeline.py")
    assert parser in ids and pipeline in ids

    # every node carries loc + centrality
    by_id = {n["id"]: n for n in data["nodes"]}
    assert by_id[parser]["called_by"] >= 1          # pipeline.py calls into parser.py
    assert by_id[pipeline]["called_by"] == 0        # nothing calls pipeline.py
    assert isinstance(by_id[parser]["loc"], int)

    # the pipeline.py -> parser.py edge carries the crossing calls
    edge = next(e for e in data["edges"]
                if e["from"] == pipeline and e["to"] == parser)
    assert any(c["to_name"] == "parse_header" for c in edge["calls"])
    assert all({"from_name", "to_name", "line"} <= set(c) for c in edge["calls"])
    # no self-edges
    assert all(e["from"] != e["to"] for e in data["edges"])


def test_graph_data_empty_without_index(monkeypatch, tmp_path):
    # Point at a non-existent index → graceful empty, no SystemExit.
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "nope.db"))
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    from keymd.engine import config
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    assert query.graph_data() == {"nodes": [], "edges": []}


def test_polyglot_java_cross_file_graph(monkeypatch, tmp_path, capsys):
    """End-to-end: a Java repo builds into a connected file→file graph (the user's
    'tabs not mapping' bug) and the build prints a skip notice for an unsupported
    language. Self-contained tmp repo, not the shared fixture."""
    pytest.importorskip("tree_sitter_java")
    import keymd.engine.parsers.treesitter  # noqa: F401  (registers Java/C/C++)

    (tmp_path / "Main.java").write_text(
        "public class Main {\n"
        "  void run() {\n"
        "    Helper h = new Helper();\n"
        "    h.greet();\n"
        "  }\n"
        "}\n", encoding="utf-8")
    (tmp_path / "Helper.java").write_text(
        "public class Helper {\n"
        "  void greet() { System.out.println(1); }\n"
        "}\n", encoding="utf-8")
    (tmp_path / "skip.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")

    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / ".keymd" / "index.db"))
    from keymd.engine import config
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()

    index.build(verbose=True)
    out = capsys.readouterr().out
    assert ".go (1)" in out                              # never-silent skip notice

    data = query.graph_data()
    ids = {n["id"] for n in data["nodes"]}
    assert "Main.java" in ids and "Helper.java" in ids   # both Java files are nodes
    # Main.java → Helper.java edge exists (new Helper() creation OR greet() call resolves)
    assert any(e["from"] == "Main.java" and e["to"] == "Helper.java"
               for e in data["edges"])
