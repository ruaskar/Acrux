# Ability-retention benchmark — does the gate degrade the agent?

**Question:** if an agent reads keymd's compact `.key.md` summaries instead of full
source, does it get *worse* at answering questions about the code? **Result: no —
accuracy holds. 5/5 on the voluntary run, and 15/15 across 3 strict-enforcement
trials when the agent uses the `keymd_read_full` escape per keymd's own directive.
Token savings, separately, are *task-shaped*: large on structural / "where is X"
questions, ~0 on value-lookup questions (where a correct answer means opening the
file). See the [Enforced-gate variant](#enforced-gate-variant-summary-first-explicit-escape)
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
under the **real enforced gate**, served by keymd's actual gate code.

**Method.** `benchmarks/enforced_gate_eval.py` builds each task's treatment
context from `gate.summary_result` (the exact `.key.md` payload + `⟪keymd-summary:…⟫`
marker the proxy injects), deterministically. The treatment agent gets **only** that
context and **no raw source**; if a summary lacks the asked-for fact it must escalate
with an explicit `keymd_read_full`, served by the same confined `engine.full` the
proxy uses — every escape **logged and counted**. The escalation instruction mirrors
keymd's own `SYSTEM_DIRECTIVE` ("call `keymd_read_full` only when the summary is
genuinely insufficient"). Tokens are deterministic, not self-reported: control = the
candidate file set read in full; treatment = the enforced payloads **plus** any
escalated full source. Run **N=3 trials** (Sonnet); a blind Opus judge scores every
answer against a ground-truth key.

### Accuracy holds; tokens are governed by how often the agent must escalate

The headline number you pick is really a point on a frontier set by the **escalation
discipline** — and accuracy survives all of them:

| regime | accuracy | token cut (this battery) |
|---|:--:|:--:|
| voluntary — agent keeps Read, opens full every time | 5/5 | 5.8% |
| conservative — *declines* the escape, guesses | 4/5 | 17.9% |
| **escalate-when-unsure — faithful to keymd's directive (N=3)** | **15/15** | **5.0%** |

The conservative single run's one miss (T1) was the agent **guessing instead of
escalating** — not a capability loss. Told to escalate when the summary lacks the
fact (which is what keymd actually instructs), **all 3 trials escalated and scored
5/5**.

### Per-task, faithful run (escalate-when-unsure, gate @ 75 loc, `tiktoken o200k_base`)

| task | type | control tok | treatment tok | cut | escalated? | ✓ (3 trials) |
|---|---|--:|--:|--:|:--:|:--:|
| T1 | comprehension (enum value) | 1,660 | 1,598 | 3.7% | gate.py | 3/3 |
| T2 | structure (URL strings) | 5,750 | 5,505 | 4.3% | server.py | 3/3 |
| T3 | trace (marker literal) | 746 | 1,040 | −39.4% | gate.py | 3/3 |
| T4 | **locate (call-graph)** | 2,350 | 1,542 | **34.4%** | **— none** | 3/3 |
| T5 | detail/fix (code step) | 1,072 | 1,311 | −22.3% | sync_one.py | 3/3 |
| **TOTAL** | | **11,578** | **10,996** | **5.0%** | 4/5 | **15/15** |

## Honest reading (enforced)

- **Ability is retained — 15/15.** Under strict enforcement, with the agent using the
  escape keymd tells it to use, the summary-fed agent answered every task as well as
  the full-source control. The gate is not a capability tax.
- **Token savings are task-shaped, and this battery is a worst case for them.** Four
  of five tasks ask for a **value** — an enum literal (`"gated"`), URL path strings,
  the marker, a code-level step. A *structural* summary by design carries signatures +
  the call-graph, **not** values, so a correct answer requires escalating to the full
  file ⇒ ~0 net saving on that task (T3/T5 even cost more: summary *then* full). The
  benchmark is value-heavy on purpose — it stresses accuracy, not tokens.
- **Where the gate wins is visible in the one structural task.** T4 ("which files call
  `engine.summary`") was answered from the **call-graph alone at −34%**, no escape —
  both call sites straight from the summary's `called_by`. That is the shape of most
  real agent work ("understand this module / where do I change X / what depends on Y"),
  and it is where the corpus-wide **offline 53–78%** comes from: an agent navigates
  many files by summary and opens full source only for the few it edits.
- **One concrete keymd improvement this surfaced:** summaries omit module-level
  constants/enum literals, which forced the escape on T1. Emitting them in
  `render_keymd` would let definitional questions resolve without a full read.
- **Reproduce:** `python benchmarks/enforced_gate_eval.py --print T4` prints the exact
  enforced context (the real gate payload); `--list` shows the per-file gated/token
  table. Builder covered by `tests/test_enforced_gate_eval.py`.
- **Caveats:** N=3, single repo, Sonnet agent (non-deterministic); escalation was
  orchestrated round-by-round (the agent decided *when* to escalate; source served by
  the real `engine.full`). The 5.0% is specific to this value-heavy battery — a
  navigation-heavy workload trends toward the offline 53–78%, a deep-edit workload
  toward 0. Accuracy (the headline) was stable across all three trials.
