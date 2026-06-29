"""replay_engine.py — drive a trajectory through transform variants, counting
input tokens per turn with the shipped tiktoken counter. Efficiency only."""
from __future__ import annotations

from benchmarks import transforms
from benchmarks.trajectory import body_input_tokens
from benchmarks.offline_ab import _encoder
from benchmarks.transforms import t_bound, t_cache  # noqa: F401

_COUNT = _encoder()[1]
_MARKER = "⟪keymd-bounded:"


def _gate_bound(body):
    g, _ = transforms.t_gate(body)
    return transforms.t_bound(g)


def _gate_bound_cache(body):
    g, _ = transforms.t_gate(body)
    return transforms.t_cache(transforms.t_bound(g))


DEFAULT_VARIANTS = {
    "raw": transforms.t_raw,
    "gate": lambda b: transforms.t_gate(b)[0],
    "gate_bound": _gate_bound,
    "gate_bound_cache": _gate_bound_cache,
}


def replay(trajectory, *, variants=None):
    variants = variants or DEFAULT_VARIANTS
    totals = {k: 0 for k in variants}
    per_turn = []
    gated_turns = bounded_turns = 0
    for body in trajectory:
        row = {}
        _, g = transforms.t_gate(body)
        if g:
            gated_turns += 1
        for name, fn in variants.items():
            out = fn(body)
            row[name] = body_input_tokens(out, _COUNT)
            totals[name] += row[name]
        # did bounding fire on this turn? marker present in the bound variant
        bound_out = transforms.t_bound(body)
        if any(_MARKER in str(m) for m in bound_out.get("messages", [])):
            bounded_turns += 1
        per_turn.append(row)
    raw = totals.get("raw", 0) or 1
    reductions = {k: round(100 * (raw - v) / raw, 2) for k, v in totals.items()}
    return {"per_turn": per_turn, "totals": totals, "reductions": reductions,
            "counters": {"gated_turns": gated_turns, "bounded_turns": bounded_turns,
                         "n_turns": len(trajectory)}}
