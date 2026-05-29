import os
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_proj"


@pytest.fixture
def sample_proj():
    return FIXTURE


@pytest.fixture
def env_proj(monkeypatch, tmp_path):
    """Point the engine at the fixture repo with an isolated index path."""
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(FIXTURE))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    # Clear caches that depend on env between tests.
    from keymd.engine import config
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    return FIXTURE
