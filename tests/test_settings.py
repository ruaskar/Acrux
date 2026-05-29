import pytest

from keymd.engine import settings


def test_missing_file_returns_defaults(tmp_path):
    s = settings.load(root=tmp_path)
    assert s.threshold == 400 and s.host == "127.0.0.1" and s.port == 8787
    assert s.wire == "openai" and s.upstream is None


def test_reads_values(tmp_path):
    (tmp_path / "keymd.toml").write_text(
        '[keymd]\nthreshold = 50\n[keymd.serve]\n'
        'host = "0.0.0.0"\nport = 9000\nwire = "anthropic"\n'
        'upstream = "https://x.test"\n', encoding="utf-8")
    s = settings.load(root=tmp_path)
    assert (s.threshold, s.host, s.port, s.wire, s.upstream) == (
        50, "0.0.0.0", 9000, "anthropic", "https://x.test")


def test_malformed_raises_clear_error(tmp_path):
    (tmp_path / "keymd.toml").write_text("not = = valid", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        settings.load(root=tmp_path)
    assert "keymd.toml" in str(e.value)
