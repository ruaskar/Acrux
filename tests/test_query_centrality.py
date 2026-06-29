# tests/test_query_centrality.py
from keymd.engine import query


def test_centrality_map_returns_dict(env_proj):
    from keymd.engine import index
    index.build(verbose=False)
    cm = query.centrality_map()
    assert isinstance(cm, dict)
    # every value is a non-negative dependent-count
    assert all(isinstance(v, int) and v >= 0 for v in cm.values())


def test_centrality_map_absent_index(monkeypatch, tmp_path):
    """Returns {} (never raises) when the index doesn't exist."""
    import os
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "nonexistent.db"))
    from keymd.engine import config
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    cm = query.centrality_map()
    assert cm == {}
