from pathlib import Path

from keymd.engine import index
from keymd.proxy import engine, gate
from keymd.proxy.adapters.base import ToolCall
import keymd.engine.parsers.python  # noqa: F401


def test_classify(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    canon = engine.canon(parser_py)
    assert gate.classify(ToolCall("1", "keymd_impact", {"path": parser_py}),
                         summarized=set(), threshold=0).kind == "virtual"
    g = gate.classify(ToolCall("2", "Read", {"file_path": parser_py}),
                      summarized=set(), threshold=0)
    assert g.kind == "gated" and g.path == canon
    assert gate.classify(ToolCall("3", "Bash", {"command": "ls"}),
                         summarized=set(), threshold=0).kind == "host"
    # loop-guard: already-summarized path passes through as host
    assert gate.classify(ToolCall("4", "Read", {"file_path": parser_py}),
                         summarized={canon}, threshold=0).kind == "host"
    # not-indexed read => host
    assert gate.classify(ToolCall("5", "Read", {"file_path": str(Path(env_proj) / "nope.py")}),
                         summarized=set(), threshold=0).kind == "host"


def test_classify_read_tool_case_insensitive(env_proj):
    # OpenClaw emits a lowercase "read" tool; Claude Code emits "Read". Both — and
    # any case variant of the known read tools — must gate.
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    canon = engine.canon(parser_py)
    for name in ("read", "Read", "READ", "read_file", "View", "CAT"):
        d = gate.classify(ToolCall("x", name, {"file_path": parser_py}),
                          summarized=set(), threshold=0)
        assert d.kind == "gated" and d.path == canon, f"{name!r} should gate"
    # a tool that merely contains 'read' is NOT a read tool -> host
    assert gate.classify(ToolCall("y", "reader", {"file_path": parser_py}),
                         summarized=set(), threshold=0).kind == "host"


def test_summarized_paths_from_transcript():
    msgs = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x",
         "content": "⟪keymd-summary:/abs/parser.py⟫\n# parser..."}]}]
    assert "/abs/parser.py" in gate.summarized_paths(msgs)


def test_summarized_paths_responses_function_call_output():
    # OpenAI Responses wire: tool result is a function_call_output item whose text
    # lives under "output" (not "content"). Missing this re-gates every inner turn.
    msgs = [{"type": "function_call_output", "call_id": "c1",
             "output": "⟪keymd-summary:/abs/foo.py⟫\n# foo..."}]
    assert "/abs/foo.py" in gate.summarized_paths(msgs)


def test_summary_result_marker_and_deterministic(env_proj):
    index.build(verbose=False)
    canon = engine.canon(str(Path(env_proj) / "pkg" / "parser.py"))
    text = gate.summary_result(canon)
    assert text.startswith(f"⟪keymd-summary:{canon}⟫")
    assert "keymd_read_full" in text
    # deterministic: no live timestamp leaks in (stripped)
    assert "refreshed:" not in text
    assert gate.summary_result(canon) == text  # stable across calls


def test_loop_guard_round_trip(env_proj):
    # produce a summary, feed it back through the transcript, confirm re-read is host
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    canon = engine.canon(parser_py)
    tool_result_text = gate.summary_result(canon)
    msgs = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": tool_result_text}]}]
    summarized = gate.summarized_paths(msgs)
    d = gate.classify(ToolCall("2", "Read", {"file_path": parser_py}),
                      summarized=summarized, threshold=0)
    assert d.kind == "host"  # not re-gated
