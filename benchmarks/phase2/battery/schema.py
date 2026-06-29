"""schema.py — Phase-2 degradation battery: per-repo questions with ground-truth.

A record mirrors enforced_gate_eval.BATTERY: {id, type, q, files, key} plus an
optional test_sh path (the completion arm). load_battery validates every record."""
from __future__ import annotations

import json

_TYPES = {"comprehension", "structure", "trace", "locate", "detail/fix"}


def validate_record(rec: dict) -> None:
    rid = rec.get("id", "<no-id>")
    if not rec.get("id") or not rec.get("q") or not rec.get("key"):
        raise ValueError(f"battery record {rid}: id, q, and key must be non-empty")
    if not isinstance(rec.get("files"), list) or not rec["files"]:
        raise ValueError(f"battery record {rid}: files must be a non-empty list")
    if rec.get("type") not in _TYPES:
        raise ValueError(f"battery record {rid}: type must be one of {_TYPES}")


def load_battery(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        recs = json.load(fh)
    for r in recs:
        validate_record(r)
    return recs
