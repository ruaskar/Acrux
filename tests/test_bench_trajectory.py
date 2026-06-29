import json
from benchmarks.trajectory import body_input_tokens, load_trajectory
from benchmarks.offline_ab import _encoder

_count = _encoder()[1]


def test_counts_system_tools_and_messages():
    body = {
        "system": [{"type": "text", "text": "you are a helpful agent"}],
        "tools": [{"name": "Read", "description": "read a file"}],
        "messages": [
            {"role": "user", "content": "find the bug"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "grep", "input": {"q": "x"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "a.py:1:hit"}]},
        ],
    }
    n = body_input_tokens(body, _count)
    # must be > the bare user string alone (system+tools+toolresult all counted)
    assert n > _count("find the bug")
    # deterministic
    assert body_input_tokens(body, _count) == n


def test_string_system_and_plain_content():
    body = {"system": "sys", "messages": [{"role": "user", "content": "hello"}]}
    assert body_input_tokens(body, _count) >= _count("sys") + _count("hello")


def test_load_trajectory_roundtrip(tmp_path):
    p = tmp_path / "t.json"
    traj = [{"messages": [{"role": "user", "content": "x"}]}]
    p.write_text(json.dumps(traj))
    assert load_trajectory(str(p)) == traj
