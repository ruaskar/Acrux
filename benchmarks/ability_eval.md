# Ability-retention benchmark — does the gate degrade the agent?

**Question:** if an agent reads keymd's compact `.key.md` summaries instead of full
source, does it get *worse* at answering questions about the code? **Result: 100%
retained on the voluntary run (5/5); 4/5 (80%) under the strict enforced gate — the
one miss a non-escalated definitional detail, recoverable with one `keymd_read_full`.
See the [Enforced-gate variant](#enforced-gate-variant-summary-first-explicit-escape)
below.**

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

---

## Enforced-gate variant (summary-first, explicit escape)

The run above is a *floor*: the treatment agent kept a normal Read tool and
over-read. This variant removes that confound — it answers the **same T1–T5**
under the **real enforced gate**.

**Method.** `benchmarks/enforced_gate_eval.py` builds each task's treatment
context from keymd's actual gate (`gate.summary_result` — the same `.key.md`
payload + `⟪keymd-summary:…⟫` marker the proxy injects), deterministically. The
treatment agent gets **only** that context and **no raw source**; if a summary is
insufficient it must escalate with an explicit `keymd_read_full`, served by the
same confined `engine.full` the proxy uses — every escape **logged and counted**.
Tokens are deterministic, not self-reported: control = the candidate file set read
in full; treatment = the enforced payloads **plus** any escalated full source.
Control (full source) and a blind Opus judge are unchanged.

**Result** (gate @ 75 loc, `tiktoken o200k_base`):

| task | type | control tok | enforced tok | cut | escalated | control ✓ | enforced ✓ |
|---|---|--:|--:|--:|:--:|:--:|:--:|
| T1 | comprehension | 1,660 | 852 | **48.7%** | — | ✓ | **✗** |
| T2 | structure | 5,750 | 5,505 | 4.3% | server.py | ✓ | ✓ |
| T3 | trace | 746 | 294 | **60.6%** | — | ✓ | ✓ |
| T4 | locate | 2,350 | 1,542 | **34.4%** | — | ✓ | ✓ |
| T5 | detail/fix | 1,072 | 1,311 | −22.3% | sync_one.py | ✓ | ✓ |
| **TOTAL** | | **11,578** | **9,504** | **17.9%** | 2/5 | **5/5** | **4/5** |

**Accuracy: control 5/5, enforced 4/5.** The realized enforced cut (**17.9%**) is
above the voluntary floor (5.8%) — the ceiling the prior section asked for — yet
well below the offline 53–78%, because savings depend on the **escalation rate**:
when the agent must escalate the biggest file, it pays summary *then* full (T5 even
nets −22%).

## Honest reading (enforced)

- **The one miss is the real finding, not a footnote.** On T1 the agent answered
  the *value* question ("which Decision kind") wrong — and did **not** escalate. The
  cause is structural: keymd's summary captures **signatures + the call-graph**, not
  **enum/constant literals** (`kind = "virtual"|"gated"|"host"` lives in the body, not
  a signature). So *definitional* questions need a `keymd_read_full`, and a real agent
  sometimes won't take it. This is honest evidence that the enforced gate is **not a
  free 100%** — it retains ability *when the agent escalates appropriately*. A natural
  keymd improvement: surface module-level constants in the summary.
- **Where the gate clearly wins (no escape needed):** T4 (locate) was answered from
  the **call-graph alone** — both call sites of `engine.summary` straight from the
  summary's `called_by`. T3 (trace) answered from the summary at −61% tokens. These
  are exactly the broad structural / "where is X" tasks an agent would otherwise
  read many files for.
- **Where it costs:** deep single-file detail (T5) — the summary is a cheap *index*
  to the right file, not a substitute, so summary + escalation > one full read.
- **Reproduce:** `python benchmarks/enforced_gate_eval.py --print T1` prints the exact
  enforced context (the real gate payload). `--list` shows the per-file gated/token
  table. The builder is covered by `tests/test_enforced_gate_eval.py`.
- **Caveats:** N=5, single repo, single run, Sonnet agent (non-deterministic); the
  escalation step was orchestrated round-by-round (the agent decided *when* to
  escalate; the source was served by the real `engine.full`). The 17.9% is specific
  to this battery's escalation pattern — a read-heavier battery trends toward the
  offline 53–78%, a deep-edit battery toward 0.
