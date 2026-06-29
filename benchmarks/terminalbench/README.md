# Terminal-Bench Corpus Builder

Derives real agent trajectories from [Terminal-Bench](https://github.com/harbor-framework/terminal-bench) task reference solutions (`solve.sh` files) for use in the Acrux offline token-efficiency benchmark.

## How to fetch Terminal-Bench tasks

**Option A — Harbor CLI:**

```bash
harbor run -d terminal-bench@2.0
```

This pulls the task suite from the public Harbor registry and writes task folders into the current directory.

**Option B — Clone directly:**

```bash
git clone https://github.com/harbor-framework/terminal-bench
```

Task folders live under `terminal-bench/tasks/` (or the registry-unpacked equivalent).

## Task folder layout

Each task folder contains:

```
<task-name>/
  instruction.md   # natural-language task description shown to the agent
  Dockerfile       # builds the task filesystem (files, binaries, configs)
  solve.sh         # reference solution — shell commands the agent should run
  test.sh          # oracle that grades whether the task was solved
```

## Requirements

- **Docker is required** for filesystem materialization (`synthesize_trajectory`). Without Docker the builder skips all tasks and reports `included 0 / skipped N (docker unavailable x N)`.
- The **parser alone** (`parse_solve_sh`) is pure Python and is what CI tests — no Docker needed.

## Usage

```bash
python -m benchmarks.terminalbench.build_corpus \
    --tasks /path/to/terminal-bench/tasks \
    --out   /path/to/output/trajectories
```

Output: one `<task-name>.json` per included task, each a list of Anthropic request bodies (assistant `tool_use` + user `tool_result` per read, with growing history).

Every skipped task is printed with its reason — there is no silent truncation.

## Conservative-floor rationale

`solve.sh` contains the minimal reference commands needed to solve the task. A real agent explores more than the reference solution does, so the derived trajectories **understate** the token savings Acrux produces. This makes the benchmark a defensible conservative floor: if savings are measured against these leaner trajectories, real-world savings are at least as large.
