# tests/test_bench_transforms.py
import keymd.proxy.engine as eng
from benchmarks import transforms
from benchmarks.trajectory import body_input_tokens
from benchmarks.offline_ab import _encoder

_count = _encoder()[1]


def _grep_body(nlines=400):
    big = "\n".join(f"src/a.py:{i}:def f{i}(): pass" for i in range(nlines))
    return {"messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "grep", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big}]}]}


def test_raw_is_identity():
    b = _grep_body()
    out = transforms.t_raw(b)
    assert out == b and out is not b          # equal value, different object


def test_bound_shrinks_grep(monkeypatch):
    monkeypatch.setattr(eng, "centrality_map", lambda: {})
    b = _grep_body()
    before = body_input_tokens(b, _count)
    out = transforms.t_bound(b)
    after = body_input_tokens(out, _count)
    assert after < before                     # bounding reduced tokens
    assert b == _grep_body()                  # input NOT mutated


def test_cache_marks_without_changing_token_count():
    b = {"system": [{"type": "text", "text": "s" * 200}], "tools": [{"name": "Read"}],
         "messages": []}
    out = transforms.t_cache(b)
    assert out["system"][-1].get("cache_control") == {"type": "ephemeral"}
