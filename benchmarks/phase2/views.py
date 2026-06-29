"""views.py — the two views a paired subagent sees: CONTROL (full source) vs
TREATMENT (keymd summary-first + escape). Treatment reuses the SHIPPED gate via
enforced_gate_eval so the degradation arm tests the real product."""
from __future__ import annotations

from benchmarks.enforced_gate_eval import (
    build_treatment_context, gated_payload, read_full,  # noqa: F401  (re-exported for the guard test)
)
from benchmarks.enforced_gate_eval import _full_text


def control_view(files: list[str]) -> str:
    parts = []
    for rel in files:
        parts.append(f"===== {rel}  [FULL SOURCE] =====\n{_full_text(rel)}")
    return "\n\n".join(parts)


def treatment_view(files: list[str], threshold: int = 50) -> str:
    return build_treatment_context(files, threshold)


def escape(path: str):
    return read_full(path)
