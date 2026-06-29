"""Tests for the flagged per-request token ledger (Phase-2 live capture).

Default-off: path=None is a strict no-op.
"""
import json
from keymd.proxy import token_ledger
from keymd.proxy.adapters.anthropic import AnthropicAdapter


def test_record_appends_jsonl(tmp_path):
    p = tmp_path / "ledger.jsonl"
    body = {"messages": [{"role": "user", "content": "hello world"}]}
    resp = {"usage": {"output_tokens": 7}}
    token_ledger.record(str(p), body_in=body, resp=resp, adapter=AnthropicAdapter())
    line = json.loads(p.read_text().strip())
    assert line["tokens_out"] == 7
    assert line["tokens_in_est"] > 0


def test_default_off_writes_nothing(tmp_path):
    p = tmp_path / "none.jsonl"
    token_ledger.record(None, body_in={}, resp={}, adapter=AnthropicAdapter())
    assert not p.exists()


def test_write_failure_is_isolated(tmp_path):
    """Verify that write failures do not propagate and crash the request."""
    # Path to a nonexistent parent directory — this will fail to open.
    p = str(tmp_path / "nope" / "sub" / "ledger.jsonl")
    body = {"messages": [{"role": "user", "content": "test"}]}
    resp = {"usage": {"output_tokens": 5}}
    # Should not raise; must return normally.
    token_ledger.record(p, body_in=body, resp=resp, adapter=AnthropicAdapter())
    # Verify no file was created.
    assert not (tmp_path / "nope").exists()
