"""enforced_gate_eval.py — build the EXACT enforced-gate context for the ability
battery, deterministically, from keymd's REAL gate.  NO API spend.

Why this exists: the voluntary ability A/B (benchmarks/ability_eval.md) let the
treatment agent keep a normal Read tool, so it over-read (summary AND full
source) — its token number is only a floor. This builds the *enforced* context
instead: for each battery file the real gate either serves the .key.md summary
(`gate.summary_result`, the same payload + marker the proxy injects) or passes a
small file through full (the host's behavior for sub-threshold files). The
treatment subagent answers from THIS text only, escaping to source solely via
`read_full()` — the same confined `engine.full` the `keymd_read_full` tool uses,
logged + token-counted. Result: accuracy UNDER enforcement plus the *realized*
enforced-token ceiling the prior doc asked for.

No LLM is called here. The reasoning half (control / treatment / judge subagents)
is dispatched live — see benchmarks/ability_eval.md "Enforced-gate variant".

Usage:
  python benchmarks/enforced_gate_eval.py --list
  python benchmarks/enforced_gate_eval.py --print T1 [--threshold 75]
"""
from __future__ import annotations

import argparse
import functools
import sys
from pathlib import Path

from keymd.engine import config, index
from keymd.engine.refresh import _confined
from keymd.proxy import engine, gate
import keymd.engine.parsers.python  # noqa: F401  (register .py parser)
try:
    import keymd.engine.parsers.treesitter  # noqa: F401  (JS/TS if installed)
except Exception:
    pass

# Reuse the offline A/B tokenizer + pct so token numbers are apples-to-apples.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from offline_ab import _encoder, _pct  # noqa: E402

THRESHOLD = 75  # headline gate, matches offline_ab.HEADLINE_THR

# The SAME T1–T5 battery as ability_eval.md. `files` is the candidate set an agent
# would consult (a few files, NOT just the answer file — so the context doesn't
# leak the answer); `key` is the ground truth the blind judge scores against.
BATTERY = [
    {
        "id": "T1", "type": "comprehension",
        "q": "What does gate.classify return, and which Decision kind replaces a "
             "file read with a summary?",
        "files": ["src/keymd/proxy/gate.py", "src/keymd/proxy/engine.py"],
        "key": "Returns a Decision dataclass whose kind is one of "
               "{virtual, gated, host}; kind == 'gated' is the one that replaces "
               "the read with a .key.md summary.",
    },
    {
        "id": "T2", "type": "structure",
        "q": "List the wire adapters and the HTTP endpoint path each one serves.",
        "files": ["src/keymd/proxy/server.py",
                  "src/keymd/proxy/adapters/anthropic.py",
                  "src/keymd/proxy/adapters/openai.py",
                  "src/keymd/proxy/adapters/responses.py"],
        "key": "Anthropic Messages -> /v1/messages (+ /v1/messages/count_tokens); "
               "OpenAI Chat -> /v1/chat/completions; OpenAI Responses -> /v1/responses.",
    },
    {
        "id": "T3", "type": "trace",
        "q": "What exactly does the gate inject in place of an un-summarized large "
             "Read, and what is the exact marker string?",
        "files": ["src/keymd/proxy/gate.py"],
        "key": "gate.summary_result injects the .key.md summary wrapped by the marker "
               "line `⟪keymd-summary:{abspath}⟫`, then the summary body, then "
               "a footer telling the model to call keymd_read_full for full source.",
    },
    {
        "id": "T4", "type": "locate",
        "q": "Which file(s) call engine.summary()?",
        "files": ["src/keymd/proxy/engine.py", "src/keymd/proxy/gate.py",
                  "src/keymd/proxy/tools.py"],
        "key": "Two call sites: gate.py (gate.summary_result) and tools.py "
               "(tools.answer, the keymd_read virtual tool).",
    },
    {
        "id": "T5", "type": "detail/fix",
        "q": "Which step in sync_one prevents a dangling edge when a symbol is "
             "renamed or removed?",
        "files": ["src/keymd/engine/sync_one.py"],
        "key": "Before the global re-resolve it computes the leaf names LOST from the "
               "file (old leaves minus new leaves) and NULLs their stale incoming "
               "edges: UPDATE edges SET to_path=NULL WHERE to_path=<file> AND "
               "to_name IN (lost).",
    },
]


@functools.lru_cache(maxsize=1)
def _counter():
    return _encoder()  # (name, count_fn) — built once


def _abs(rel: str) -> str:
    return engine.canon(str(config.project_root() / rel))


def _full_text(rel: str) -> str:
    return Path(_abs(rel)).read_text(encoding="utf-8", errors="replace")


def _task(task_id: str) -> dict:
    for t in BATTERY:
        if t["id"] == task_id:
            return t
    raise SystemExit(f"unknown task {task_id!r}; "
                     f"choose from {[t['id'] for t in BATTERY]}")


def gated_payload(rel: str, threshold: int = THRESHOLD) -> dict:
    """The EXACT bytes the enforced proxy would serve for a Read of `rel`.

    Large indexed file -> gate.summary_result (summary + the real marker).
    Otherwise the full source (the host passes sub-threshold files through —
    a RAW read, matching the host path, NOT the confined keymd_read_full escape).
    """
    ap = _abs(rel)
    if not _confined(ap):                       # defense-in-depth: battery paths
        raise ValueError(f"{rel} resolves outside the project root")
    count = _counter()[1]
    if engine.is_indexed_large(ap, threshold):
        payload, gated = gate.summary_result(ap), True
    else:
        payload, gated = _full_text(rel), False
    return {"rel": rel, "gated": gated, "payload": payload, "tokens": count(payload)}


def build_treatment_context(files: list[str], threshold: int = THRESHOLD) -> str:
    parts = []
    for rel in files:
        p = gated_payload(rel, threshold)
        tag = "SUMMARY (gated)" if p["gated"] else "FULL SOURCE (small file, passed through)"
        parts.append(f"===== {rel}  [{tag}] =====\n{p['payload']}")
    return "\n\n".join(parts)


def read_full(rel_or_abs: str) -> tuple[str, int]:
    """Grant a treatment escape via the SAME confined engine.full that the
    keymd_read_full tool uses. Returns (text, tokens). Refuses outside-root."""
    ap = engine.canon(rel_or_abs if Path(rel_or_abs).is_absolute()
                      else str(config.project_root() / rel_or_abs))
    text = engine.full(ap)
    return text, _counter()[1](text)


def _print_task(task: dict, threshold: int) -> None:
    ctx = build_treatment_context(task["files"], threshold)
    print(f"# TREATMENT PROMPT — {task['id']} ({task['type']})  @ gate {threshold} loc\n")
    print("You are answering a question about the keymd codebase. You may use ONLY")
    print("the context below (keymd's gated read payloads). Do NOT read raw source.")
    print("If a SUMMARY is insufficient, request full source by replying with a")
    print("single line `keymd_read_full: <path>` and nothing else; it will be")
    print("provided, then give your answer. Keep the answer tight and factual.\n")
    print(f"## QUESTION\n{task['q']}\n")
    print(f"## CONTEXT\n{ctx}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="enforced_gate_eval")
    ap.add_argument("--threshold", type=int, default=THRESHOLD,
                    help=f"gate at loc > this (default {THRESHOLD})")
    ap.add_argument("--list", action="store_true",
                    help="list the battery + per-file gated/token table")
    ap.add_argument("--print", dest="task", metavar="TASK",
                    help="emit the ready-to-paste treatment prompt for a task id")
    a = ap.parse_args(argv)

    for _s in (sys.stdout, sys.stderr):           # UTF-8 so glyphs don't mojibake
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    index.build(verbose=False)

    if a.task:
        _print_task(_task(a.task), a.threshold)
        return 0

    enc_name = _counter()[0]
    count = _counter()[1]
    print(f"keymd enforced-gate battery  —  gate {a.threshold} loc  —  tokenizer: {enc_name}")
    print("(payloads are the REAL gate output: gate.summary_result for large files)\n")
    for t in BATTERY:
        full_tok = enf_tok = 0
        for rel in t["files"]:
            p = gated_payload(rel, a.threshold)
            ft = count(_full_text(rel))
            full_tok += ft
            enf_tok += p["tokens"]
            mark = "summary" if p["gated"] else "full   "
            print(f"    [{mark}] {rel:<46} {ft:>6,} -> {p['tokens']:>6,} tok "
                  f"({_pct(ft, p['tokens']):>5.1f}%)")
        print(f"  {t['id']} ({t['type']}): context {full_tok:,} -> {enf_tok:,} tok  "
              f"({_pct(full_tok, enf_tok):.1f}% cut, before any escape)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
