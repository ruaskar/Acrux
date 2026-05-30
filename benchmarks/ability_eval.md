# Ability-retention benchmark — does the gate degrade the agent?

**Question:** if an agent reads keymd's compact `.key.md` summaries instead of full
source, does it get *worse* at answering questions about the code? **Result: no —
100% accuracy retained on this battery.**

## Method (paired clean-context agents + blind judge)

Mirrors the source aotc-harness A/B (paired Sonnet subagents). For a 5-task battery
over keymd's own repo:

- **Control agent** (Sonnet): answers each task reading full `.py` source as needed.
- **Treatment agent** (Sonnet): answers each task preferring the `.key.md` summary
  (API signatures + deps + call-graph), opening full source *only* when a summary is
  genuinely insufficient.
- **Judge** (Opus, blind to which answer is which): scores both answers against a
  ground-truth key — correct only if it captures the key facts.

Then each agent's self-reported read-set is tokenized post-hoc (`tiktoken o200k_base`)
for the token/line figures.

## Tasks

| # | Type | Question (abbrev.) |
|---|---|---|
| T1 | comprehension | What does `gate.classify` return; which kind replaces a read with a summary? |
| T2 | structure | The wire adapters and the endpoint path each serves |
| T3 | trace | What the gate injects for an un-summarized large Read, and the exact marker |
| T4 | locate | Which file calls `engine.summary()` |
| T5 | detail/fix | The `sync_one` step that prevents a dangling edge on symbol rename/remove |

## Result

| task | control tok | treat tok | tok cut | control ✓ | treat ✓ |
|---|--:|--:|--:|:--:|:--:|
| T1 (multi-file) | 2,161 | 1,482 | **31.4%** | ✓ | ✓ |
| T2 (structural) | 5,750 | 5,073 | **11.8%** | ✓ | ✓ |
| T3 (trace) | 1,247 | 990 | **20.6%** | ✓ | ✓ |
| T4 (single symbol) | 746 | 1,529 | −105% | ✓ | ✓ |
| T5 (single-file detail) | 1,072 | 1,268 | −18% | ✓ | ✓ |
| **TOTAL** | **10,976** | **10,342** | **5.8%** | **5/5** | **5/5** |

Lines read: 1,083 → 834 (**−23%**). **Accuracy retained: 5/5 = 5/5 (100%).** On T4 the
treatment agent found *more* than control — both call sites of `engine.summary`
(`gate.summary_result` **and** `tools.answer`) — surfaced directly by the call-graph
summary.

## Honest reading

- **The headline is accuracy, and it held:** reading summaries cost zero answer quality.
  That is the claim this benchmark exists to support — keymd is a token lever, not a
  capability tax.
- **This is the cautious-agent *floor* for tokens.** The treatment agent voluntarily
  opened full source on every task (and on single-file deep tasks T4/T5 that costs
  *more* than just reading the one file). The **enforced** proxy is stronger: it serves
  the summary *in place of* the read, so the model only pays for full source when it
  explicitly calls `keymd_read_full`. The enforced-gate savings are the 53–78% in the
  README's *Measured token savings* (offline, deterministic).
- **Where summaries help most:** broad comprehension / structural / multi-file tasks
  (T1 −31%, T2 −12%) — exactly where an agent would otherwise read many files. On
  single-file implementation detail, the summary is a cheap *index* to the right file,
  not a replacement for it.
- **Caveats:** N=5, single repo, single run, self-reported read-sets, Sonnet agents
  (non-deterministic). Treat as directional. Re-run with a stricter summary-first
  treatment to probe the enforced-gate ceiling.
