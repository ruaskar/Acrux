"""curate.py — select and materialize Terminal-Bench tasks for the Acrux benchmark.

Selection heuristic (pure, CI-tested):
  is_code_nav_task(task_meta, solve_sh) -> (selected: bool, reason: str)

  A task is selected when BOTH:
    1. It has a code-repo signal: task_meta["has_repo"] is True, OR the
       instruction mentions a recognisable language project keyword.
    2. solve.sh reads ≥2 DISTINCT source files (extensions: .py .js .ts
       .java .c .cpp .go .rs .rb .sh .php .cs .swift .kt .scala .lua .ex
       .exs .hs .ml .r .jl .m).  Source reads are detected via
       terminalbench.build_corpus.parse_solve_sh() so the same conservative
       floor applies (reads after '&&', inside backticks etc. are missed).

Materialization (Docker-gated):
  materialize_and_index(task_dir, out_dir) -> indexed_path | None

  Builds the task Docker image, copies the repo out of a container, runs
  `keymd build` over it, and returns the indexed path.  Returns None (+ logs)
  when Docker is absent so CI can run the heuristic tests without Docker.

main(argv):
  --tasks DIR --out DIR
  Walks tasks DIR; for each passing task calls materialize_and_index; writes
  a manifest JSON listing curated repos (path + battery file to attach);
  prints "selected N / skipped M (reasons)" with NO silent truncation.

  Materialised repos feed NEW per-repo batteries (authored like
  keymd_self.json) for the S1 subagent protocol.
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

from benchmarks.terminalbench.build_corpus import parse_solve_sh

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source-file extensions we consider "code"
# ---------------------------------------------------------------------------
_SOURCE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp",
    ".go", ".rs", ".rb",
    ".php", ".cs", ".swift", ".kt", ".scala",
    ".lua", ".ex", ".exs", ".hs", ".ml", ".r", ".jl", ".m",
}

# Keywords that suggest a code-project in the instruction when has_repo is missing
_CODE_KEYWORDS = re.compile(
    r"\b(package|module|function|class|method|bug|test|lint|build|"
    r"compile|deploy|refactor|debug|import|script|library|api|endpoint)\b",
    re.IGNORECASE,
)

# Tools that carry a direct `path` key from parse_solve_sh
_PATH_TOOLS = {"cat", "less", "head", "tail"}

# Tools whose `args` field may embed a path we can extract
_SEARCH_TOOLS = {"grep", "rg"}


def _is_source_path(p: str) -> bool:
    """Return True when *p* has a recognised source-file extension."""
    _, ext = os.path.splitext(p)
    return ext.lower() in _SOURCE_EXTS


def _extract_source_paths(records: list[dict]) -> set[str]:
    """Return the set of distinct source-file paths visible in parsed records.

    * For path-tool records (cat/less/head/tail): check path directly.
    * For search-tool records (grep/rg): scan the args tokens for any token
      that looks like a source file (has a source extension).  Directory args
      (e.g. src/app/) are not counted — they carry no unique file identity.
    """
    paths: set[str] = set()
    for rec in records:
        tool = rec.get("tool", "")
        if tool in _PATH_TOOLS:
            p = rec.get("path", "")
            if _is_source_path(p):
                paths.add(p)
        elif tool in _SEARCH_TOOLS:
            args = rec.get("args", "")
            for token in args.split():
                if not token.startswith("-") and _is_source_path(token):
                    paths.add(token)
    return paths


def _has_code_repo_signal(meta: dict) -> bool:
    """Return True when the task carries a code-repo indicator."""
    if meta.get("has_repo"):
        return True
    instruction = meta.get("instruction", "")
    return bool(_CODE_KEYWORDS.search(instruction))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_code_nav_task(task_meta: dict, solve_sh: str) -> tuple[bool, str]:
    """Pure selection heuristic for Terminal-Bench code-navigation tasks.

    Returns (selected, reason).  When selected is False, reason explains why
    (always mentions "read" or "code" so callers can log it verbatim).
    """
    if not _has_code_repo_signal(task_meta):
        return False, "no code-repo signal (has_repo is False and instruction lacks code keywords)"

    records = parse_solve_sh(solve_sh)
    source_paths = _extract_source_paths(records)

    if len(source_paths) < 2:
        n = len(source_paths)
        return (
            False,
            f"too few distinct source-file reads: found {n}, need ≥2 "
            f"(paths: {sorted(source_paths) or 'none'}; "
            "check that solve.sh reads code files, not only docs/binaries)",
        )

    return True, f"selected: code-repo signal present; {len(source_paths)} distinct source reads"


def materialize_and_index(task_dir: str, out_dir: str) -> str | None:
    """Materialise a Terminal-Bench task repo and index it with keymd.

    Docker-gated: returns None (+ logs a warning) when Docker is absent,
    so CI heuristic tests can run without Docker.

    Steps:
      1. Build the task Dockerfile inside *task_dir*.
      2. Create a throwaway container, copy /repo out to *out_dir*.
      3. Remove the container.
      4. Run `keymd build` over the extracted repo.
      5. Return the indexed repo path.
    """
    if shutil.which("docker") is None:
        log.warning(
            "materialize_and_index: Docker not found — skipping materialisation "
            "of %s.  Install Docker to enable this step.",
            task_dir,
        )
        return None

    task_name = os.path.basename(os.path.normpath(task_dir))
    image_tag = f"acrux-task-{task_name}:latest"
    repo_out = os.path.join(out_dir, task_name)
    os.makedirs(repo_out, exist_ok=True)

    # Build image
    log.info("Building Docker image %s from %s", image_tag, task_dir)
    subprocess.run(
        ["docker", "build", "-t", image_tag, task_dir],
        check=True,
        capture_output=True,
        text=True,
    )

    # Create a container (don't start it), copy /repo out, remove container
    create_result = subprocess.run(
        ["docker", "create", image_tag],
        check=True,
        capture_output=True,
        text=True,
    )
    container_id = create_result.stdout.strip()
    try:
        subprocess.run(
            ["docker", "cp", f"{container_id}:/repo/.", repo_out],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        subprocess.run(
            ["docker", "rm", container_id],
            capture_output=True,
            text=True,
        )

    # Index with keymd build
    log.info("Running keymd build in %s", repo_out)
    subprocess.run(
        [sys.executable, "-m", "keymd", "build"],
        cwd=repo_out,
        check=True,
    )

    return repo_out


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Select, materialise, and index Terminal-Bench code-navigation tasks.

    Prints: selected N / skipped M (reasons) — NO silent truncation.
    Writes: <out_dir>/manifest.json listing curated repos + battery files.
    """
    parser = argparse.ArgumentParser(
        description="Curate Terminal-Bench tasks for the Acrux degradation benchmark"
    )
    parser.add_argument("--tasks", required=True, metavar="DIR",
                        help="Root directory containing task sub-folders")
    parser.add_argument("--out", required=True, metavar="DIR",
                        help="Output directory for materialised repos and manifest")
    args = parser.parse_args(argv)

    tasks_root = args.tasks
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    selected_tasks: list[dict] = []
    skipped: list[tuple[str, str]] = []  # (task_name, reason)

    task_names = sorted(
        e.name for e in os.scandir(tasks_root) if e.is_dir()
    )

    for task_name in task_names:
        task_dir = os.path.join(tasks_root, task_name)
        solve_sh_path = os.path.join(task_dir, "solve.sh")
        meta_path = os.path.join(task_dir, "metadata.json")

        # Load solve.sh
        if not os.path.isfile(solve_sh_path):
            reason = "no solve.sh found (not a valid task folder)"
            print(f"  SKIP {task_name}: {reason}")
            skipped.append((task_name, reason))
            continue

        with open(solve_sh_path, encoding="utf-8") as f:
            solve_sh = f.read()

        # Load metadata (optional)
        meta: dict = {}
        if os.path.isfile(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)

        selected, reason = is_code_nav_task(meta, solve_sh)

        if not selected:
            print(f"  SKIP {task_name}: {reason}")
            skipped.append((task_name, reason))
            continue

        # Materialise + index (Docker-gated)
        indexed_path = materialize_and_index(task_dir, out_dir)
        battery_file = os.path.join(
            os.path.dirname(__file__), "battery", f"{task_name}.json"
        )
        selected_tasks.append({
            "task": task_name,
            "indexed_path": indexed_path,
            "battery_file": battery_file,
            "reason": reason,
        })
        print(f"  SELECT {task_name}: {reason}")

    # Write manifest
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"curated": selected_tasks}, f, indent=2)

    n_sel = len(selected_tasks)
    n_skip = len(skipped)

    print(f"\nselected {n_sel} / skipped {n_skip}")
    if skipped:
        print("Skip reasons:")
        for task_name, reason in skipped:
            print(f"  {task_name}: {reason}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
