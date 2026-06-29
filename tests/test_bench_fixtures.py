import importlib
from pathlib import Path
import keymd.proxy.engine as eng
from benchmarks import replay_engine
from benchmarks.trajectory import load_trajectory

FIX = Path(__file__).parent.parent / "benchmarks" / "fixtures" / "trajectories"


def test_grep_fixture_shows_reduction(monkeypatch):
    monkeypatch.setattr(eng, "centrality_map", lambda: {})
    rep = replay_engine.replay(load_trajectory(str(FIX / "grep_heavy.json")))
    assert rep["reductions"]["gate_bound"] > 10     # grep-heavy → real cut
    assert rep["counters"]["bounded_turns"] >= 1


def test_growing_history_cache_helps(monkeypatch):
    monkeypatch.setattr(eng, "centrality_map", lambda: {})
    rep = replay_engine.replay(load_trajectory(str(FIX / "growing_history.json")))
    assert rep["counters"]["n_turns"] >= 3
    assert rep["reductions"]["gate_bound"] > 10  # growing tail re-billed per turn → real cut


def test_transforms_call_shipped_modules():
    # guard: the benchmark must measure the real product, not a fork
    from benchmarks import transforms
    import keymd.proxy.result_bound as rb
    import keymd.proxy.cache_inject as ci
    assert transforms.result_bound is rb
    assert transforms.cache_inject is ci
