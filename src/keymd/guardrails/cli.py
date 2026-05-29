"""cli.py — `keymd guard <action>` dispatch (exit non-zero on a violation)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from keymd.guardrails import checks


def run(action: str, rest: list[str]) -> int:
    if action == "check-push":
        branch = (rest[0] if rest else "").strip()
        if checks.is_protected_push(branch):
            print(f"[keymd guard] refusing push to protected branch '{branch}' "
                  f"(set KEYMD_PROTECTED_BRANCHES to change). Use a PR.")
            return 1
        return 0

    if action == "check-dup":
        if not rest:
            return 0
        new = rest[0]
        d = Path(new).parent
        siblings = [p.name for p in d.glob("*") if p.is_file()] if d.exists() else []
        cands = checks.duplicate_candidates(Path(new).name, siblings)
        if cands:
            print(f"[keymd guard] '{Path(new).name}' overlaps existing files: "
                  f"{', '.join(cands)} — extend one instead of adding a near-duplicate?")
            return 1
        return 0

    if action == "install":
        root = Path(os.environ.get("KEYMD_PROJECT_ROOT") or ".").resolve()
        hooks = root / ".git" / "hooks"
        if not hooks.parent.exists():
            print(f"[keymd guard] no .git at {root}")
            return 1
        hooks.mkdir(parents=True, exist_ok=True)
        pre_push = hooks / "pre-push"
        # Bake the absolute interpreter that ran `install` (not bare `keymd`),
        # so the hook can't fail closed with 'command not found' (exit 127) and
        # block EVERY push when keymd isn't on the hook's PATH. The script's
        # exit = check-push's exit (0 allow / 1 protected), so no `|| exit 1`.
        py = sys.executable.replace("\\", "/")
        pre_push.write_text(
            "#!/bin/sh\n"
            "# keymd guard: block pushes to protected branches\n"
            "branch=$(git rev-parse --abbrev-ref HEAD)\n"
            f'"{py}" -m keymd.cli guard check-push "$branch"\n',
            encoding="utf-8")
        try:
            os.chmod(pre_push, 0o755)
        except OSError:
            pass
        print(f"[keymd guard] installed pre-push hook at {pre_push}")
        return 0

    print(f"[keymd guard] unknown action: {action}")
    return 2
