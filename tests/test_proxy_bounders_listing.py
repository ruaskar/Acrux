# tests/test_proxy_bounders_listing.py
from keymd.proxy.bounders import bound_listing


def test_groups_by_dir_and_caps():
    paths = [f"src/pkg/m{i}.py" for i in range(80)]
    out = bound_listing("\n".join(paths), centrality={}, max_entries=60)
    assert out is not None
    assert "src/pkg" in out
    assert "(+20 more" in out


def test_central_files_ranked_first():
    text = "src/a.py\nsrc/b.py\nsrc/c.py"
    out = bound_listing(text, centrality={"src/b.py": 9, "src/a.py": 1}, max_entries=60)
    # b.py (centrality 9) appears before a.py (1) and c.py (0)
    assert out.index("b.py") < out.index("a.py") < out.index("c.py")


def test_non_listing_returns_none():
    assert bound_listing("error: command failed\nstack trace here", centrality={}) is None
