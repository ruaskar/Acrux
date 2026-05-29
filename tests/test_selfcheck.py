"""selfcheck.run_inprocess — the in-process gate + synthesized-SSE check used by
`keymd doctor --wire` (local stub, no API spend)."""
import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
from keymd.proxy import selfcheck  # noqa: E402


def test_selfcheck_inprocess_gate_fires():
    res = selfcheck.run_inprocess(threshold=10)
    assert res["ok"] is True
    assert res["gate_fired"] is True
    assert res["chunks"] >= 2


def test_selfcheck_restores_env(monkeypatch):
    # run_inprocess must not leak KEYMD_PROJECT_ROOT/INDEX_PATH into the process
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", "/sentinel/root")
    monkeypatch.setenv("KEYMD_INDEX_PATH", "/sentinel/idx.db")
    selfcheck.run_inprocess(threshold=10)
    import os
    assert os.environ["KEYMD_PROJECT_ROOT"] == "/sentinel/root"
    assert os.environ["KEYMD_INDEX_PATH"] == "/sentinel/idx.db"
