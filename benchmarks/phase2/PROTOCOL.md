# Phase-2 Paired-Subagent Dispatch Protocol

This document is the **exact recipe** the human controller follows to run the
Acrux Phase-2 paired comparison.  Nothing here is automated — every subagent
dispatch is a deliberate controller action via the Agent tool.

---

## Overview

Two measurement arms are defined in `benchmarks/phase2/score.py`:

| Arm | Context given to the solving agent |
|-----|-------------------------------------|
| **Control** | Full source (`views.control_view`) |
| **Treatment** | keymd summary-first view (`views.treatment_view`), with escape available |

For each question/task the controller dispatches subagents, collects verdicts,
and writes a JSON verdict file to `benchmarks/phase2/run_log/`.  The scorer
(`benchmarks.phase2.score.load_verdicts`) reads these files; the report
(`benchmarks.phase2.report`) renders them.

---

## Setup

Before running, import the two view builders into your Python session or script:

```python
from benchmarks.phase2.views import control_view, treatment_view, escape
```

- `control_view(files: list[str]) -> str`  
  Returns a single string containing every file in `files` in full, each
  preceded by a `===== <rel_path>  [FULL SOURCE] =====` header.

- `treatment_view(files: list[str], threshold: int = 50) -> str`  
  Returns the keymd summary-first view (via `enforced_gate_eval.build_treatment_context`).
  Files with ≥ `threshold` lines are shown as `.key.md` summaries preceded by a
  `⟪keymd-summary:<abspath>⟫` marker; shorter files are shown in full.

- `escape(path: str) -> (str, int)`  
  Returns `(full_source_text, line_count)` for `path`.  The controller calls
  this to supply full source when the treatment agent declares it needs a file.

The battery files live in `benchmarks/phase2/battery/`.  The canonical
self-benchmark battery is `benchmarks/phase2/battery/keymd_self.json`.
Curated third-party batteries are produced by `curate.py` (see S2 below).

---

## S1 — Q&A arm (per battery question record)

Each record in a battery JSON has the shape:

```json
{
  "id": "T4",
  "type": "locate",
  "q": "Which file(s) call engine.summary()?",
  "files": ["src/keymd/proxy/engine.py", "src/keymd/proxy/gate.py", "src/keymd/proxy/tools.py"],
  "key": "Two call sites: gate.py (gate.summary_result) and tools.py (tools.answer, the keymd_read virtual tool).",
  "test_sh": null
}
```

Process **one question per subagent**.  Never run multiple questions inside the
same subagent context — answers would bleed across.

### Step 1 — Dispatch the CONTROL subagent

Build the context:

```python
context = control_view(record["files"])
```

Dispatch a subagent (Agent tool) with this prompt — substitute `{q}` and
`{context}` literally:

```
{q}

--- CONTEXT ---
{context}
--- END CONTEXT ---

Answer ONLY from the provided context. Be concise and specific.
```

Capture the subagent's full text response as `control_answer`.

### Step 2 — Dispatch the TREATMENT subagent

Build the context:

```python
context = treatment_view(record["files"])
```

**Escape mechanism (option a — single-shot, pre-attached note):**  
Pre-attach a note about the escape so the agent can declare which paths it
would open, keeping the exchange single-shot with clean context.  Dispatch
a subagent with this prompt:

```
{q}

--- CONTEXT ---
{context}
--- END CONTEXT ---

You are seeing a keymd summary-first view.  Files whose source exceeds the
threshold are shown as .key.md summaries, preceded by a ⟪keymd-summary:…⟫
marker.  If answering requires the full source of any path, state in your
answer which path(s) you would open (e.g. "I would read full source for
src/keymd/proxy/gate.py").  Answer to the best of your ability from the
summaries provided.
```

Capture the subagent's full text response as `treatment_answer`.

**If the treatment agent declares specific paths it needs:** the controller
MAY (optionally) call `escape(path)` for each declared path and supply the
full source in a second dispatch.  This is a single clarification round only.
Document in the verdict rationale whether a second round was used.

### Step 3 — Dispatch the BLIND JUDGE subagent

**Randomize the label assignment per question.** Flip a coin (or use
`random.random() < 0.5`).  Record which arm got which label:

```python
import random
flip = random.random() < 0.5
if flip:
    A_answer, B_answer = control_answer, treatment_answer
    A_arm,    B_arm    = "control",       "treatment"
else:
    A_answer, B_answer = treatment_answer, control_answer
    A_arm,    B_arm    = "treatment",       "control"
```

Dispatch a subagent with this prompt:

```
Question: {q}

Ground truth: {key}

Answer A:
{A_answer}

Answer B:
{B_answer}

For each of answer A and answer B, decide if it correctly captures the key
facts stated in the ground truth.  Return a JSON object with this exact shape:

{
  "A": {"correct": true|false, "rationale": "<one sentence>"},
  "B": {"correct": true|false, "rationale": "<one sentence>"}
}

You do NOT know which system produced which answer.  Do not speculate.
Judge solely on factual coverage of the ground truth.
```

Parse the judge's JSON response.  The judge model used must be disclosed when
reporting results (see Honesty Rules below).

### Step 4 — De-randomize and write the verdict file

Map the judge's A/B verdicts back to arms using the recorded `A_arm`/`B_arm`
labels (Step 3 recorded which arm each label refers to):

```python
# Step 3 recorded: A_arm, B_arm  (each is "control" or "treatment")
arm_of = {"A": A_arm, "B": B_arm}                      # label -> arm name
by_arm = {arm_of[L]: judge[L]["correct"] for L in ("A", "B")}
verdict = {
    "id": record["id"],
    "control":   by_arm["control"],
    "treatment": by_arm["treatment"],
    "rationale": f"A={judge['A']['rationale']} | B={judge['B']['rationale']}",
}
# write verdict to benchmarks/phase2/run_log/<id>.json
```

Write to `benchmarks/phase2/run_log/<id>.json`:

```python
import json, os
path = os.path.join("benchmarks/phase2/run_log", f"{record['id']}.json")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(verdict, fh, indent=2)
```

This is exactly the shape `benchmarks.phase2.score.load_verdicts` consumes.

---

## S2 — test.sh arm (per curated task with a real `test_sh`)

Records with `"test_sh": "<path to test script>"` in the curated battery use
the S2 protocol.  This arm measures whether the treatment agent can still
**solve** a task when large source files are replaced on disk by summaries.

### Preparation

For each curated task the controller needs two ephemeral repo copies:

1. **CONTROL repo** — the task repo as materialized and indexed by `curate.py`
   (`materialize_and_index`), untouched.

2. **TREATMENT repo** — a copy of the same repo where every large source file
   (≥ 50 lines, already indexed) is replaced on disk by its `.key.md` summary,
   and a shell escape script is placed at the repo root.

To materialize the treatment repo:

```bash
cp -r <control_repo>/ <treatment_repo>/
```

Then, for each file that `treatment_view` would gate (i.e., each file whose
line count ≥ threshold and whose `.key.md` exists alongside it):

```bash
# Replace the source file with its summary
cp <file>.key.md <file>
```

Place the escape script at `<treatment_repo>/keymd_read_full`:

```bash
cat > <treatment_repo>/keymd_read_full <<'EOF'
#!/usr/bin/env bash
# Usage: keymd_read_full <relative-path>
# Prints the full source of the requested path from the CONTROL repo.
CONTROL_ROOT="<absolute_path_to_control_repo>"
cat "$CONTROL_ROOT/$1"
EOF
chmod +x <treatment_repo>/keymd_read_full
```

### Step 1 — Dispatch CONTROL solving subagent

Dispatch a subagent given `instruction.md` for the task and the CONTROL repo
path.  The subagent is told it may freely read and modify files in the control
repo to satisfy the task.

### Step 2 — Dispatch TREATMENT solving subagent

Dispatch a subagent given `instruction.md` for the task and the TREATMENT repo
path.  The subagent is told:

- Large files may appear as `.key.md` summaries in place of source files.
- It may call `./keymd_read_full <rel-path>` to retrieve any file's full source.
- It should modify the repo to pass the task's `test.sh`.

### Step 3 — Run test.sh in each repo

```bash
bash <control_repo>/<test_sh>
control_pass=$?   # 0 = PASS

bash <treatment_repo>/<test_sh>
treatment_pass=$?  # 0 = PASS
```

### Step 4 — Write the verdict file

```python
verdict = {
    "id": record["id"],
    "control":   control_pass == 0,
    "treatment": treatment_pass == 0,
    "rationale": f"test.sh exit status: control={control_pass}, treatment={treatment_pass}"
}
```

Write to `benchmarks/phase2/run_log/<id>.json` (same format as S1).

---

## Honesty Rules

These rules are non-negotiable.  Violating them invalidates the comparison.

1. **Judge is blind and labels are randomized.**  The judge subagent sees only
   "Answer A" and "Answer B", never "control" or "treatment".  A fresh random
   coin flip is performed *per question*; the mapping is recorded by the
   controller and used only in Step 4 de-randomization.

2. **Disclose the judge model.**  When reporting results, state which model was
   used as the blind judge (e.g., "claude-sonnet-4-6 as judge").  The judge
   model may differ from the solving agents, but must be the same for all
   questions in a run.

3. **Never reveal which arm is keymd.**  Do not include the words "keymd",
   "treatment", "control", "summary-first", or "gated" in any prompt given to
   a solving agent.  The treatment agent is told it is seeing summaries and may
   request full source — that is all.

4. **The controller must not coach either agent.**  No hints, no steering.  The
   prompt is identical for both arms modulo the view block (and the escape note
   in the treatment arm).  Any asymmetry in prompting invalidates the question.

5. **One question per subagent (clean context).**  Each of the three subagents
   per question (control solver, treatment solver, judge) runs in an isolated
   context with no history from other questions or other arms.

6. **No post-hoc verdict editing.**  Once a verdict JSON is written, it is
   immutable for that run.  Re-running a question requires deleting the existing
   file and re-running the full S1/S2 loop from Step 1.  _Distinction:_ editing
   a verdict file after seeing it is forbidden (results tampering).  Fixing a
   verified-stale ground-truth key in the battery is different and is allowed,
   but only when: (a) the correction is objectively verifiable against source
   (e.g. `grep`/`Read` confirms it), (b) it is done before scaled results are
   recorded (e.g. during the dry-run), (c) it is logged, and (d) the affected
   question is re-judged from Step 1 — the verdict is not hand-patched.
   Precedent: the T4 dry-run found the inherited key listed 2 call sites of
   `engine.summary()`; grep confirmed 3 (including `graph_server.py:76`); the
   key was corrected and T4 was re-judged from Step 1.

---

## Verdict File Format

Each question produces exactly one JSON file in `benchmarks/phase2/run_log/`:

```
benchmarks/phase2/run_log/<id>.json
```

Shape (all fields required):

```json
{
  "id":        "T4",
  "control":   true,
  "treatment": true,
  "rationale": "A: correctly named both call sites. B: identified gate.py but missed tools.py."
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `id` | string | Matches the `id` field in the battery record |
| `control` | bool | `true` if the control arm answer was judged correct (S1) or test passed (S2) |
| `treatment` | bool | `true` if the treatment arm answer was judged correct (S1) or test passed (S2) |
| `rationale` | string | One line from the judge (S1) or test exit statuses (S2) |

`benchmarks.phase2.score.load_verdicts(dir_path)` reads all `*.json` files in
`run_log/` sorted by filename, returning `list[dict]` in that order.
`benchmarks.phase2.report.build(verdicts)` renders the degradation section
from these dicts.

---

## Running the Report

After collecting verdict files, render the combined report:

```bash
python -m benchmarks.phase2.report \
  --run-log benchmarks/phase2/run_log \
  --efficiency-corpus benchmarks/fixtures/trajectories
```

The report prints two **separate** sections:

- **Degradation guard** — pass@1 per arm, discordant pair counts, McNemar
  chi-squared (continuity-corrected), and a one-line verdict.
- **Token efficiency (Phase 1)** — per-fixture token-reduction table from
  deterministic replay.  Never blended with the degradation numbers.

A small-N honest-boundary block is always appended:

> **Honest boundary:** small repo-N; blind LLM judge (randomized labels);
> test.sh arm illustrative-few, not powered; efficiency and degradation
> measured on different substrates (deterministic replay vs live subagents) —
> reported separately, never blended.

Omit `--efficiency-corpus` to skip the Phase-1 section (useful for a quick
degradation-only check).

---

## Quick Reference: Per-Question Checklist

```
[ ] 1. Fetch the battery record (id, type, q, files, key)
[ ] 2. Build control_view(files) and treatment_view(files)
[ ] 3. Dispatch CONTROL subagent → capture control_answer
[ ] 4. Dispatch TREATMENT subagent (with escape note) → capture treatment_answer
[ ] 5. Flip coin → record A_arm / B_arm
[ ] 6. Dispatch BLIND JUDGE subagent with randomized A/B → parse JSON
[ ] 7. De-randomize → write benchmarks/phase2/run_log/<id>.json
[ ] 8. Confirm file shape matches the verdict format above
```
