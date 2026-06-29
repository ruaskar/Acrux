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
