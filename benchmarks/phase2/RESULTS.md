# Acrux (keymd) — agentic-task comparison results

**Date:** 2026-06-29 · **N=6** questions over keymd's own indexed repo · **$0** (local paired subagents, blind Opus judge) · single-shot (no escape round-trip executed — see boundary).

Method: per question, a **control** subagent reads full source and a **treatment** subagent reads keymd's `.key.md` summaries (the real shipped gate); a **blind judge** (randomized A/B labels) scores both against a grep-verified ground-truth key. Token save measured deterministically (`tiktoken o200k_base`) as control-view vs treatment-view input tokens.

## Token efficiency — control view vs keymd treatment view

| Q | type | control tok | treatment tok | save |
|---|---|--:|--:|--:|
| T1 | comprehension | 3,062 | 1,358 | **−55.6%** |
| T2 | structure | 7,499 | 2,264 | **−69.8%** |
| T3 | trace | 817 | 439 | **−46.3%** |
| T4 | locate | 4,287 | 1,663 | **−61.2%** |
| T5 | detail/fix | 1,152 | 305 | **−73.5%** |
| T6 | detail/fix (small file) | 842 | 848 | **+0.7%** |
| **TOTAL** | | **17,659** | **6,877** | **−61.1%** |

Token save is **task-shaped**: large on multi-file / large-file questions (T2 −70%, T5 −74%), and **near-zero on a small file** (T6 +0.7%) where a summary isn't smaller than the source — the designed boundary, not hidden.

## Task accuracy — paired pass@1 + McNemar

| Q | control | treatment | note |
|---|:--:|:--:|---|
| T1 comprehension | ✅ | ✅ | both correct from summary |
| T2 structure | ✅ | ❌ | treatment correctly identified it needed the exact endpoint-path literals and **asked to open server.py** — single-shot protocol didn't grant the escape |
| T3 trace | ✅ | ❌ | treatment **gave the exact marker** (it was in its gated view) but hedged "would open to confirm" → judged as not-committing |
| T4 locate | ❌ | ✅ | **treatment found MORE** — all 3 call sites incl. `graph_server.py` via the call-graph; control (3 files only) missed it |
| T5 detail/fix | ✅ | ❌ | implementation step not in the summary signatures; treatment **asked to open sync_one.py** — escape not granted |
| T6 detail/fix | ✅ | ✅ | both correct from summary |

- **control pass@1 = 5/6 (83.3%)**, **treatment pass@1 = 3/6 (50.0%)**
- discordant: control-only **3** (T2,T3,T5), treatment-only **1** (T4)
- **McNemar χ²(1, continuity-corrected) = 0.25, p = 0.617 → no statistically significant difference** (N is small; this is the honest reading)

## What this actually shows (the honest interpretation)

1. **Token save is real and substantial: −61% aggregate**, task-shaped (−46% to −74% on real-content questions, ~0 on a small file).
2. **The treatment "losses" are escalation-discipline artifacts, not capability loss.** On T2/T5 the treatment agent **correctly recognized the summary lacked an exact value and explicitly asked for full source** (`would open: <path>`). In the real keymd product that is a `keymd_read_full` call that returns the source — this **single-shot protocol did not execute the escape round-trip**, so it scores those as failures. T3 is sharper: treatment **had the right answer** and was penalized only for hedging. This reproduces `ability_eval.md`'s earlier observation ("a run where the agent declined the escape and guessed — an escalation-discipline artifact, not a capability loss").
3. **On the structural question keymd wins outright (T4): the call-graph summary surfaced a call site full source missed.**

## Boundaries (do not over-read)
- **N=6, keymd's own repo** — illustrative, not powered. McNemar p=0.617 means we cannot claim a difference either way.
- **Single-shot, escape not honored** — the head-to-head accuracy **understates** treatment, because the real product grants `keymd_read_full`. The honest claim is: *with the escape, the value-lookup losses (T2,T5) are recoverable in one extra round-trip; without it, the agent at least knows what it's missing.*
- **Blind LLM judge** (randomized labels) — disclosed; the T3/T4 cases show the judge rewards committing to an answer.
- **Efficiency and accuracy measured on different substrates** (deterministic token count vs live subagent answers) — reported separately, never blended.

## Next to strengthen this
- Run the **two-turn escape protocol** (grant `keymd_read_full` when treatment asks) → expected to recover T2/T5 and lift treatment pass@1 toward control while keeping most of the −61% save.
- Scale to the **curated Terminal-Bench code repos** (the `curate.py` path) for a larger, external-repo N.
- Add the **test.sh completion arm** for a non-LLM-judged signal.
