"""CLI [path] target arg + empty-index guard for `keymd graph` / `keymd build`.

Regression for the reported bug: `keymd graph` run from a non-repo dir (e.g. ~)
silently built an empty index and served a blank graph. It must instead refuse
with guidance, and accept an explicit repo path.
"""
import os

import pytest

import keymd.engine.parsers.python  # noqa: F401
from keymd import cli
from keymd.engine import config


def _fresh_env(monkeypatch, tmp_path):
    # neutralize any ambient KEYMD_* so the test controls resolution
    for k in ("KEYMD_PROJECT_ROOT", "KEYMD_INDEX_PATH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()


def test_graph_empty_dir_refuses_and_does_not_serve(monkeypatch, tmp_path):
    # a directory with no indexable source (the ~ case)
    _fresh_env(monkeypatch, tmp_path)
    served = {"called": False}
    from keymd.proxy import graph_server
    monkeypatch.setattr(graph_server, "serve",
                        lambda **k: served.__setitem__("called", True))
    rc = cli.main(["graph"])
    assert rc == 1                       # non-zero: nothing to graph
    assert served["called"] is False     # MUST NOT open a server / blank browser


def test_graph_with_path_arg_indexes_that_repo(monkeypatch, tmp_path):
    # an explicit target repo elsewhere on disk
    _fresh_env(monkeypatch, tmp_path)
    repo = tmp_path / "myrepo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "a.py").write_text('"""A."""\ndef a(): return 1\n', encoding="utf-8")
    captured = {}
    from keymd.proxy import graph_server
    monkeypatch.setattr(graph_server, "serve",
                        lambda **k: captured.update(k) or None)
    rc = cli.main(["graph", str(repo)])
    assert rc == 0
    assert captured                                  # serve WAS called (non-empty)
    # the index was built against the target repo, not cwd
    assert config.project_root() == repo.resolve()
    import sqlite3
    from keymd.engine import db
    con = db.connect(config.index_path())
    n = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    con.close()
    assert n >= 1


def test_build_with_path_arg(monkeypatch, tmp_path, capsys):
    _fresh_env(monkeypatch, tmp_path)
    repo = tmp_path / "r2"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "b.py").write_text('"""B."""\ndef b(): return 2\n', encoding="utf-8")
    rc = cli.main(["build", str(repo), "--quiet"])
    assert rc == 0
    assert config.project_root() == repo.resolve()
    out = capsys.readouterr().out
    assert '"files": 1' in out or '"files":1' in out


def test_graph_bad_path_errors(monkeypatch, tmp_path):
    _fresh_env(monkeypatch, tmp_path)
    rc = cli.main(["graph", str(tmp_path / "does-not-exist")])
    assert rc == 1                       # clear error, not a traceback
