"""result_bound.py — bound oversized live tool-results inbound (Component A core).

Pure, deterministic, idempotent: a function of the inbound `body` only. Walks
tool_result blocks, routes large ones from recognized read-shaped tools to a
bounding rule, and stamps a marker so a re-pass is a no-op. Fail-open: a rule
returning None, or any guard, leaves the block byte-identical.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from keymd.proxy.adapters.base import WireAdapter

MARKER_RE = re.compile(r"⟪keymd-bounded:")


def _mark(kind: str, body_text: str) -> str:
    return f"⟪keymd-bounded:{kind}⟫\n{body_text}"


def bound_results(body: dict, adapter: WireAdapter,
                  rules: dict[str, Callable[[str], str | None]], *,
                  min_bytes: int = 1500, fresh_results: int = 2) -> dict:
    names = adapter.tool_call_names(body)
    refs = adapter.iter_tool_results(body)
    cutoff = len(refs) - fresh_results          # indices >= cutoff are "fresh"
    compiled = [(re.compile(pat, re.I), fn) for pat, fn in rules.items()]
    for i, ref in enumerate(refs):
        if i >= cutoff:                          # protect the active working set
            continue
        if MARKER_RE.search(ref.text):           # already bounded → idempotent
            continue
        if len(ref.text) < min_bytes:            # too small to bother
            continue
        name = names.get(ref.id, "")
        rule = next((fn for rx, fn in compiled if rx.fullmatch(name)), None)
        if rule is None:
            continue
        try:
            new = rule(ref.text)
        except Exception:        # fail-open: a misbehaving rule must never crash the turn
            continue
        if new is None:          # fail-open: None → leave as-is
            continue
        # kind = the tool name, lowercased, for marker provenance
        ref.set_text(_mark(name.lower(), new))
    return body
