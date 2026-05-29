from pathlib import Path

from keymd.engine import config


def test_project_root_from_env(env_proj):
    assert config.project_root() == Path(env_proj).resolve()


def test_index_path_from_env(env_proj, tmp_path):
    assert config.index_path().name == "index.db"


def test_index_roots_autodiscovers_pkg(env_proj):
    names = {r.name for r in config.index_roots()}
    assert "pkg" in names


def test_pkg_prefixes_contains_pkg(env_proj):
    assert "pkg" in config.project_pkg_prefixes()


def test_is_excluded():
    assert config.is_excluded("/x/__pycache__/y.py")
    assert not config.is_excluded("/x/pkg/y.py")
