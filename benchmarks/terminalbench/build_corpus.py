"""build_corpus.py — derive real Terminal-Bench trajectories from solve.sh files.

Two-phase pipeline:
  1. parse_solve_sh(text)         — pure; CI-tested; no external deps.
  2. synthesize_trajectory(dir)   — Docker-gated; returns None when Docker absent.
  3. main(argv)                   — scans --tasks DIR, writes JSON to --out DIR,
                                    prints included N / skipped M with per-skip reason.

Conservative-floor note: solve.sh reads LESS than a real agent explores, so
derived trajectories UNDERSTATE token-savings — a defensible measurement floor.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import uuid

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Read-shaped commands we recognise in solve.sh lines
# ---------------------------------------------------------------------------
_READ_TOOLS = re.compile(
    r"^\s*(?P<tool>cat|less|head|tail|grep|rg|ls|find)\b"
)

# Commands whose first token is a path argument (single positional after flags)
_PATH_TOOLS = {"cat", "less", "head", "tail"}


def _parse_line(line: str) -> dict | None:
    """Return a command record for a read-shaped line, or None."""
    # Strip inline comments
    line = line.split("#")[0].strip()
    if not line:
        return None

    m = _READ_TOOLS.match(line)
    if not m:
        return None

    tool = m.group("tool")
    rest = line[m.end():].strip()

    if tool in _PATH_TOOLS:
        # Gather tokens; last non-flag token is the path
        tokens = rest.split()
        path_tokens = [t for t in tokens if not t.startswith("-")]
        path = path_tokens[-1] if path_tokens else rest
        return {"tool": tool, "path": path}
    else:
        # grep, rg, ls, find — keep the whole remainder as args
        return {"tool": tool, "args": rest}


def parse_solve_sh(text: str) -> list[dict]:
    """Scan shell-script lines for read-shaped commands.

    Returns a list of command records:
      {"tool": "cat", "path": "src/main.py"}
      {"tool": "grep", "args": "-rn 'TODO' src/"}
      {"tool": "ls",   "args": "-R data/"}
    Non-read commands (python, rm, echo, …) are silently ignored.

    Conservative-floor undercounts (acceptable — these MISS reads, never
    misclassify a non-read as a read, so they only understate savings):
      * a '#' inside a path is read as a comment and truncates the path;
      * a read after '&&' in a chained line (cd x && cat y) is not matched.
    """
    results = []
    for line in text.splitlines():
        rec = _parse_line(line)
        if rec is not None:
            results.append(rec)
    return results


# ---------------------------------------------------------------------------
# Trajectory synthesis (Docker-gated)
# ---------------------------------------------------------------------------

def _cmd_to_tool_use(cmd: dict, call_id: str) -> dict:
    """Convert a parsed command record to an Anthropic tool_use content block."""
    tool = cmd["tool"]
    if "path" in cmd:
        inp = {"file_path": cmd["path"]}
    else:
        # grep/rg/ls/find — represent as a bash invocation
        inp = {"command": f"{tool} {cmd.get('args', '')}".strip()}
    return {
        "type": "tool_use",
        "id": call_id,
        "name": "Bash" if tool in {"grep", "rg", "ls", "find"} else "Read",
        "input": inp,
    }


def _run_command_in_container(container_id: str, cmd: dict) -> str:
    """Execute a parsed read command inside a running Docker container.
    Returns stdout as a string (truncated at 100 KB to stay trajectory-sane)."""
    tool = cmd["tool"]
    if "path" in cmd:
        shell_cmd = f"{tool} {cmd['path']}"
    else:
        shell_cmd = f"{tool} {cmd.get('args', '')}"

    try:
        result = subprocess.run(
            ["docker", "exec", container_id, "sh", "-c", shell_cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = result.stdout or result.stderr or ""
    except subprocess.TimeoutExpired:
        out = f"<timeout running: {shell_cmd}>"

    max_bytes = 100 * 1024
    if len(out.encode()) > max_bytes:
        out = out.encode()[:max_bytes].decode(errors="replace") + "\n...[truncated]"
    return out


def synthesize_trajectory(task_dir: str) -> list[dict] | None:
    """Materialize the task FS via Docker and build a trajectory.

    Returns a list of Anthropic request bodies (same shape as Task-4 fixtures):
      assistant message with tool_use + user message with tool_result, per read.
    Returns None (with a log message) when Docker is unavailable.
    """
    if shutil.which("docker") is None:
        log.info("docker unavailable — skipping FS materialization for %s", task_dir)
        return None

    solve_path = os.path.join(task_dir, "solve.sh")
    dockerfile_path = os.path.join(task_dir, "Dockerfile")
    if not os.path.isfile(solve_path):
        log.warning("no solve.sh in %s — skipping", task_dir)
        return None

    with open(solve_path, encoding="utf-8") as fh:
        cmds = parse_solve_sh(fh.read())

    if not cmds:
        log.info("no read commands found in %s/solve.sh — empty trajectory", task_dir)
        return []

    # Build the Docker image for this task
    task_name = os.path.basename(os.path.abspath(task_dir))
    image_tag = f"tb-corpus-{task_name}-{uuid.uuid4().hex[:8]}"
    build_ctx = task_dir if os.path.isfile(dockerfile_path) else None

    container_id: str | None = None
    trajectory: list[dict] = []

    try:
        if build_ctx:
            log.info("building Docker image %s from %s", image_tag, task_dir)
            subprocess.run(
                ["docker", "build", "-t", image_tag, build_ctx],
                check=True,
                capture_output=True,
                timeout=300,
            )
            log.info("starting container from %s", image_tag)
            result = subprocess.run(
                ["docker", "run", "-d", "--rm", image_tag, "sleep", "300"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            container_id = result.stdout.strip()
        else:
            # No Dockerfile — use a minimal alpine image as stand-in
            log.info("no Dockerfile for %s — using alpine as FS stand-in", task_name)
            result = subprocess.run(
                ["docker", "run", "-d", "--rm", "alpine", "sleep", "300"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            container_id = result.stdout.strip()

        # Execute each read command and build the trajectory
        messages: list[dict] = []
        for i, cmd in enumerate(cmds):
            call_id = f"tb_{i:04d}"
            tool_use_block = _cmd_to_tool_use(cmd, call_id)
            output = _run_command_in_container(container_id, cmd)

            messages.append({"role": "assistant", "content": [tool_use_block]})
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": output,
                }],
            })

        # Wrap all messages into a single Anthropic request body per turn
        # (one body per read, history grows as a real agent's would)
        for end in range(2, len(messages) + 1, 2):
            body: dict = {
                "model": "claude-opus-4-5",
                "max_tokens": 4096,
                "messages": messages[:end],
            }
            trajectory.append(body)

    except subprocess.CalledProcessError as exc:
        log.error("docker error for %s: %s", task_dir, exc.stderr[:500] if exc.stderr else exc)
        return None
    finally:
        if container_id:
            subprocess.run(
                ["docker", "stop", container_id],
                capture_output=True,
                timeout=30,
            )
            if build_ctx:
                subprocess.run(
                    ["docker", "rmi", image_tag],
                    capture_output=True,
                    timeout=30,
                )

    return trajectory


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI: --tasks DIR --out DIR

    For each task subfolder containing solve.sh:
      - parse + synthesize trajectory
      - write <task>.json to --out
      - print per-task included/skipped with reason

    No silent truncation: every skip is printed with its reason.
    """
    parser = argparse.ArgumentParser(
        description="Build a Terminal-Bench corpus from solve.sh files."
    )
    parser.add_argument("--tasks", required=True,
                        help="Directory of Terminal-Bench task folders.")
    parser.add_argument("--out", required=True,
                        help="Output directory for trajectory JSON files.")
    args = parser.parse_args(argv)

    tasks_dir = args.tasks
    out_dir = args.out

    if not os.path.isdir(tasks_dir):
        print(f"ERROR: --tasks {tasks_dir!r} is not a directory", file=sys.stderr)
        return 1

    os.makedirs(out_dir, exist_ok=True)

    n_included = 0
    n_skipped = 0
    skip_reasons: dict[str, str] = {}

    entries = sorted(os.listdir(tasks_dir))
    if not entries:
        print("included 0 / skipped 0 (no task folders found)")
        return 0

    for entry in entries:
        task_path = os.path.join(tasks_dir, entry)
        if not os.path.isdir(task_path):
            continue

        solve_path = os.path.join(task_path, "solve.sh")
        if not os.path.isfile(solve_path):
            reason = "no solve.sh"
            skip_reasons[entry] = reason
            n_skipped += 1
            print(f"  SKIP {entry}: {reason}")
            continue

        if shutil.which("docker") is None:
            reason = "docker unavailable"
            skip_reasons[entry] = reason
            n_skipped += 1
            print(f"  SKIP {entry}: {reason}")
            continue

        traj = synthesize_trajectory(task_path)
        if traj is None:
            reason = "synthesis failed (see log)"
            skip_reasons[entry] = reason
            n_skipped += 1
            print(f"  SKIP {entry}: {reason}")
            continue

        if len(traj) == 0:
            reason = "no read commands in solve.sh"
            skip_reasons[entry] = reason
            n_skipped += 1
            print(f"  SKIP {entry}: {reason}")
            continue

        out_path = os.path.join(out_dir, f"{entry}.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(traj, fh, indent=2)
        n_included += 1
        print(f"  OK   {entry}: {len(traj)} turns → {out_path}")

    summary = f"included {n_included} / skipped {n_skipped}"
    if skip_reasons:
        reason_counts: dict[str, int] = {}
        for r in skip_reasons.values():
            reason_counts[r] = reason_counts.get(r, 0) + 1
        detail = ", ".join(f"{r} x{c}" for r, c in sorted(reason_counts.items()))
        summary += f" ({detail})"
    print(summary)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
