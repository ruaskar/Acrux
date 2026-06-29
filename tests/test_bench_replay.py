# tests/test_bench_replay.py
import keymd.proxy.engine as eng
from benchmarks import replay_engine


def _grep_body(n=400):
    big = "\n".join(f"src/a.py:{i}:hit{i}" for i in range(n))
    return {"messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "grep", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big}]}]}


def test_replay_reports_reduction(monkeypatch):
    monkeypatch.setattr(eng, "centrality_map", lambda: {})
    traj = [_grep_body(), _grep_body(200)]
    rep = replay_engine.replay(traj)
    assert rep["totals"]["raw"] > rep["totals"]["gate_bound"]   # bounding saved tokens
    assert rep["reductions"]["gate_bound"] > 0
    assert rep["counters"]["bounded_turns"] == 2
    assert rep["counters"]["n_turns"] == 2


def test_raw_variant_equals_input_tokens(monkeypatch):
    monkeypatch.setattr(eng, "centrality_map", lambda: {})
    rep = replay_engine.replay([_grep_body()])
    # raw total == direct body_input_tokens of the one body
    from benchmarks.trajectory import body_input_tokens
    from benchmarks.offline_ab import _encoder
    assert rep["totals"]["raw"] == body_input_tokens(_grep_body(), _encoder()[1])
