"""Tests for benchmarks/enforced_gate_eval.py — the real-gate context builder.

Exercises the MECHANISM against the fixture repo (env_proj), independent of the
live keymd tree: a large file is gated (summary + real marker), a small file is
passed through full (no marker), and the read_full escape stays confined to the
project root.
"""
import sys
from pathlib import Path

from keymd.engine import index

BENCH = Path(__file__).resolve().parent.parent / "benchmarks"
sys.path.insert(0, str(BENCH))
import enforced_gate_eval as ege  # noqa: E402


def test_large_file_is_gated_with_marker(env_proj):
    index.build(verbose=False)
    p = ege.gated_payload("pkg/pipeline.py", threshold=3)  # 8 loc > 3 → gated
    assert p["gated"] is True
    assert "⟪keymd-summary:" in p["payload"]   # the REAL proxy marker
    assert p["tokens"] > 0


def test_small_file_passes_through_full(env_proj):
    index.build(verbose=False)
    p = ege.gated_payload("pkg/parser.py", threshold=50)  # 7 loc ≤ 50 → full
    assert p["gated"] is False
    assert "⟪keymd-summary:" not in p["payload"]
    src = (Path(env_proj) / "pkg" / "parser.py").read_text(encoding="utf-8")
    assert p["payload"] == src                 # literal source, untouched
    assert p["tokens"] > 0


def test_read_full_refuses_outside_root(env_proj):
    # This test file lives OUTSIDE the fixture root → the escape must refuse it
    # (the keymd_read_full exfiltration guard).
    text, tokens = ege.read_full(str(Path(__file__).resolve()))
    assert "refused" in text
    assert tokens > 0
