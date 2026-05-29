"""ab_harness.py — paired A/B token benchmark for the keymd gate.  *** NOT RUN ***

REQUIRES a real LLM API key and SPENDS TOKENS. It is intentionally NOT executed
here (keymd's policy: no unprompted API spend). Run it yourself, on a PUBLIC
repo, to reproduce the token-savings claim.

Method (paired, controlled):
  For each task in a "read + edit a large file" battery:
    A) control: agent talks to the upstream directly (no proxy)
    B) treatment: agent talks to `keymd serve` (gate on)
  Measure, per run: input tokens to the model, lines of file content that
  entered context, and task success (did the edit pass the task's check).
  Report deltas (target ballpark from the source benchmark: -29% tokens,
  -85% lines read, accuracy retained).

Honest threats to validity to report alongside results: small N, single
codebase, model/version drift, and that the gate's benefit is largest on
read-heavy tasks over large files (it does little on small-file or
write-heavy tasks).

Skeleton below is a placeholder for the harness; wire it to your agent runner
and a public fixture repo before running.
"""
from __future__ import annotations

TASKS: list[dict] = [
    # {"repo": "<public repo path>", "prompt": "...", "check": <callable>},
]


def run_pair(task: dict, *, proxy: bool) -> dict:
    raise NotImplementedError(
        "Wire to your agent runner. Return {'input_tokens', 'lines_read', 'success'}.")


def main() -> None:
    raise SystemExit(
        "ab_harness is a scaffold and is intentionally not run (it spends API "
        "tokens). Implement run_pair() against your agent runner + a public repo.")


if __name__ == "__main__":
    main()
