# Acrux (keymd) Benchmark Suite

How much does keymd cut an agent's tokens, and does it cost task quality? This
document is the canonical, reproducible answer. It covers the **two questions
separately** because they are measured on different substrates and must never be
blended into one number:

1. **Token efficiency** — how much smaller is keymd's view than full source?
   Measured **deterministically** (tiktoken, no API, no agent).
2. **Degradation guard** — does an agent reading keymd summaries get **worse**
   at code tasks than one reading full source? Measured **live** with paired
   agents + a blind judge.

> **Honest framing up front.** Efficiency is a clean, deterministic number.
> Degradation is an agentic measurement with a small N and known artifacts; we
> report it with its boundaries, not as a headline. Where the current evidence is
> thin, this document says so.

---

## 1. What keymd does (the mechanism under test)

keymd is a transparent proxy between an agent and its LLM. On an **indexed code
repo**, when the agent reads a large file, keymd substitutes a compact,
line-anchored `.key.md` summary (API signatures + deps + a call-graph of
`calls:`/`called_by:`), and the agent pulls full source only when it needs to via
a `keymd_read_full` escape. (It also bounds oversized grep/ls results and injects
prompt-cache breakpoints; those are exercised by the Phase-1 corpus.) keymd
**no-ops without a code index** — so the whole benchmark targets indexed code
repos with reading-heavy work, which is where the lever exists.

---

## 2. Efficiency benchmark (deterministic, $0)

### 2.1 Method
A **trajectory** (a sequence of LLM request bodies) is replayed through keymd's
**shipped** transforms — the gate, the grep/ls bounder, the cache injector — and
the input tokens are counted with `tiktoken o200k_base`. Four variants per turn:
`raw` (baseline) → `gate` → `gate+bound` → `gate+bound+cache`. A guard test
asserts the benchmark calls the **real** proxy modules, not a reimplementation, so
the number can't drift from the product.

Code: [`replay_engine.py`](replay_engine.py), [`transforms.py`](transforms.py),
[`trajectory.py`](trajectory.py). CLI: [`ab_harness.py`](ab_harness.py).

### 2.2 Reproduce
```bash
python -m benchmarks.ab_harness                 # the synthetic validation corpus
```

### 2.3 Results — synthetic validation fixtures
Hand-authored trajectories of the canonical shapes (these are *validation*
fixtures, de-gamed to be realistic — see §5):

| Workload | reduction (gate+bound) |
|---|--:|
| large file read → summary (`cat_large`) | **−75.5%** |
| broad grep, clustered+capped (`grep_heavy`) | **−26.1%** |
| recursive listing, ranked+capped (`ls_recursive`) | **−41.3%** |
| growing multi-turn history (`growing_history`) | **−18.4%** |

### 2.4 Results — real keymd source (the §3 battery files)
Control view (full source) vs keymd treatment view, per question's file set,
`tiktoken o200k_base`:

| Q | type | control tok | treatment tok | save |
|---|---|--:|--:|--:|
| T1 | comprehension | 3,062 | 1,358 | **−55.6%** |
| T2 | structure (4 files) | 7,499 | 2,264 | **−69.8%** |
| T3 | trace | 817 | 439 | **−46.3%** |
| T4 | locate (3 files) | 4,287 | 1,663 | **−61.2%** |
| T5 | detail/fix (large file) | 1,152 | 305 | **−73.5%** |
| T6 | detail/fix (small file) | 842 | 848 | **+0.7%** |
| **TOTAL** | | **17,659** | **6,877** | **−61.1%** |

**Read:** the save is **task-shaped** — large on multi-file / large-file work
(−70% T2, −74% T5), near-**zero on a small file** (T6 +0.7%, where a summary is no
smaller than the source). The headline (**−61% aggregate**) is real; the small-file
floor is disclosed, not hidden.

---

## 3. Degradation guard (live, $0, local paired subagents)

### 3.1 Method
For each question over an indexed repo (here: keymd's own repo, a 6-question
battery seeded from the proven `enforced_gate_eval` set):
- a **control** agent answers reading **full source**;
- a **treatment** agent answers reading keymd **summaries** (+ the
  `keymd_read_full` escape);
- a **blind judge** (labels randomized per question) scores both against a
  grep-verified ground-truth key.

Outcomes are paired binary → **pass@1 per arm + McNemar's test** (the correct
paired-binary significance test). Code: [`phase2/views.py`](phase2/views.py)
(reuses the shipped gate), [`phase2/score.py`](phase2/score.py),
[`phase2/report.py`](phase2/report.py),
[`phase2/battery/keymd_self.json`](phase2/battery/keymd_self.json). The
controller dispatch recipe is [`phase2/PROTOCOL.md`](phase2/PROTOCOL.md); verdicts
land in `phase2/run_log/*.json`.

> **Two protocol variants — read this before the numbers.** The degradation arm
> only means something if the treatment agent gets the **escape it has in the real
> product**. There are two ways to run it:
> - **Escape-honored** (the real product): when the treatment agent says it needs a
>   file, it gets `keymd_read_full(path)` and finishes. This is the fair test.
> - **Single-shot** (no escape granted): the agent answers in one turn; if it asks
>   to open a file, that request is scored as a non-answer.
>
> **The escape-honored result is the headline; the single-shot is a preliminary,
> harness-limited data point** that exists because we have not yet automated the
> two-turn escape loop (§6). Do not cite the single-shot pass@1 as keymd's quality
> cost — it isn't.

### 3.2 Reproduce
```bash
# score the recorded verdicts + render the combined report:
python -m benchmarks.phase2.report --run-log benchmarks/phase2/run_log \
    --efficiency-corpus benchmarks/fixtures/trajectories
```
(Generating fresh verdicts requires a controller to run the §3.1 protocol — a
Python script cannot dispatch agents. See PROTOCOL.md.)

### 3.3 Headline result — escape-honored (the real product), measured on this battery
This run grants the `keymd_read_full` escape exactly as the shipped product does:
when the treatment agent says it needs a file, it gets that file's full source and
re-answers. **Measured, N=6** (verdicts in
[`phase2/run_log_escape/`](phase2/run_log_escape/)):

| Q | type | control | treatment | what happened |
|---|---|:--:|:--:|---|
| T1 | comprehension | ✅ | ✅ | both correct from the summary (no escape needed) |
| T2 | structure | ✅ | ✅ | treatment correct **after** `keymd_read_full(server.py)` — all 3 endpoint paths |
| T3 | trace | ✅ | ✅ | treatment correct **after** `keymd_read_full(gate.py)` — exact marker, committed |
| T4 | locate | ❌ | ✅ | treatment **found more** — all 3 call sites incl. `graph_server.py` via the call-graph; control (3 files) missed it |
| T5 | detail/fix | ✅ | ✅ | treatment correct **after** `keymd_read_full(sync_one.py)` — the LOST-leaves NULL step |
| T6 | detail/fix | ✅ | ✅ | both correct from the summary (no escape needed) |

- **control pass@1 = 5/6 (83.3%)**, **treatment pass@1 = 6/6 (100%)**
- discordant: control-only **0**, treatment-only **1** (T4) → **McNemar χ²=0, p=1.0**
- **Treatment matched or beat control on every question** — zero degradation; it
  *won* T4 because the call-graph surfaced a call site full source couldn't see.

Consistent with the prior study ([`ability_eval.md`](ability_eval.md),
[`enforced_gate_eval.py`](enforced_gate_eval.py)): **5/5 voluntary** and **15/15
across 3 enforced-gate trials** — accuracy retained whenever the escape is used.

**keymd's degradation answer: reading summaries instead of full source costs zero
answer quality, because full source is always one escape away.**

### 3.4 Contrast — the same battery WITHOUT the escape (why the escape matters)
The same 6 questions, run **single-shot** (the agent answers in one turn; a request
to open a file is scored as a non-answer). This is **not** a quality claim about
keymd — it isolates what the escape buys:

| Q | control | treatment (single-shot) | delta vs escape-honored |
|---|:--:|:--:|---|
| T2 | ✅ | ❌ | treatment **asked to open** server.py — not granted |
| T3 | ✅ | ❌ | treatment gave the exact marker but **hedged** "would open to confirm" |
| T5 | ✅ | ❌ | treatment **asked to open** sync_one.py — not granted |
| T1,T4,T6 | (5/6) | same as escape-honored | — |

- single-shot: **control 5/6 (83%) vs treatment 3/6 (50%)**, McNemar p=0.617 (still
  not significant). All 3 deltas are the **escape being withheld** — the agent knew
  exactly which file it needed. Grant it (→ §3.3) and treatment goes 3/6 → 6/6.

This is the earlier `ability_eval` observation, now reproduced both ways:
*summaries don't reduce
what the agent can know; an un-honored escape reduces what it commits to.*

---

## 4. Headline (with its boundaries)

> **Efficiency:** on reading-heavy code work, keymd's view is **−61% tokens**
> (deterministic, task-shaped: −46% to −74% on real-content questions, ~0 on small
> files).
>
> **Quality:** with the `keymd_read_full` escape honored — i.e. the real product —
> a measured N=6 run on this battery scored **control 5/6 (83%) vs treatment 6/6
> (100%)**: treatment matched or beat full-source on every question (§3.3),
> consistent with the prior **5/5 voluntary and 15/15 enforced-gate** studies. The
> same battery run **single-shot** (escape withheld) drops treatment to 3/6 — a gap
> that is *not* significant (McNemar p=0.62) and is **entirely** the withheld
> escape: grant it and 3/6 → 6/6 (§3.4). **Do not cite the single-shot 3/6 as
> keymd's quality cost** — keymd ships the escape.

---

## 5. Boundaries — what this does NOT yet show

- **Degradation N is small (6) and on keymd's own repo** — illustrative, not
  powered. Both runs are at N=6: escape-honored p=1.0 (treatment 6/6 ≥ control),
  single-shot p=0.62. Neither is a powered claim; the direction (no degradation,
  often a gain) is consistent with the larger prior 15/15 study.
- **Blind LLM judge** (randomized labels, disclosed) — the T3/T4 cases show the
  judge rewards committing to an answer; a non-LLM cross-check (the `test.sh`
  completion arm) is **built but not yet run**.
- **Efficiency fixtures are validation shapes; the §2.4 numbers are on keymd's own
  repo** — a compact, small-file repo *understates* the lever vs. a large external
  codebase.
- **Efficiency and degradation are different substrates** (deterministic token
  count vs live agent answers) — reported separately, **never blended**.

## 6. Strengthening this (the roadmap, already scaffolded)
- **Scale N** — the escape-honored run is done (§3.3) but N=6 on one repo. The next
  lever is a **larger battery on external repos** for statistical power, not a new
  protocol.
- **Curated Terminal-Bench code repos** — [`phase2/curate.py`](phase2/curate.py)
  selects reading-heavy code tasks and Docker-materializes+indexes them for a
  larger, external-repo N.
- **`test.sh` completion arm** — a non-LLM-judged, real-task-completion signal
  (PROTOCOL.md §S2).

## 7. File map
| Path | Role |
|---|---|
| [`replay_engine.py`](replay_engine.py) · [`transforms.py`](transforms.py) · [`trajectory.py`](trajectory.py) | efficiency replay over the shipped transforms |
| [`ab_harness.py`](ab_harness.py) | efficiency CLI |
| [`fixtures/trajectories/`](fixtures/trajectories/) | synthetic validation corpus (§2.3) |
| [`terminalbench/build_corpus.py`](terminalbench/build_corpus.py) | derive real trajectories from Terminal-Bench `solve.sh` |
| [`enforced_gate_eval.py`](enforced_gate_eval.py) · [`ability_eval.md`](ability_eval.md) | the prior single-turn gate-ability study this generalizes |
| [`phase2/views.py`](phase2/views.py) | control vs treatment views (reuses the shipped gate) |
| [`phase2/score.py`](phase2/score.py) | pass@1 + McNemar |
| [`phase2/report.py`](phase2/report.py) | combined report (separate sections) |
| [`phase2/battery/keymd_self.json`](phase2/battery/keymd_self.json) | the 6-question battery + ground-truth keys |
| [`phase2/PROTOCOL.md`](phase2/PROTOCOL.md) | controller dispatch protocol (S1 Q&A + S2 test.sh) |
| [`phase2/RESULTS.md`](phase2/RESULTS.md) | the detailed N=6 run record (§3 here summarizes it) |
| [`phase2/run_log/`](phase2/run_log/) | per-question verdict JSONs |
