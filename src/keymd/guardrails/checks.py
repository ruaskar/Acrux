"""checks.py — portable, framework-agnostic guardrail checks.

NOT token-saving (explicitly a separate concern from the engine/proxy). Pure
functions, env-configurable, no project-specific paths — generalized from the
aotc-harness hooks with all AOTC narratives/paths scrubbed. Wire them into git
hooks via `keymd guard install`, or call from any host's pre-action hook.
"""
from __future__ import annotations

import os
import re

PROTECTED_DEFAULT = ("main", "master")


def protected_branches() -> tuple[str, ...]:
    v = os.environ.get("KEYMD_PROTECTED_BRANCHES")
    if v:
        return tuple(b.strip() for b in v.split(",") if b.strip())
    return PROTECTED_DEFAULT


def is_protected_push(target_branch: str, protected: tuple[str, ...] | None = None) -> bool:
    """True if pushing to target_branch should be blocked (PR-only workflow)."""
    protected = protected if protected is not None else protected_branches()
    return target_branch in protected


_TOKEN_SPLIT = re.compile(r"[_\-.]+")


def _tokens(name: str) -> set[str]:
    stem = name.replace("\\", "/").rsplit("/", 1)[-1]
    stem = stem.split(".", 1)[0]            # drop extension(s)
    return {t for t in _TOKEN_SPLIT.split(stem) if len(t) >= 3}


def duplicate_candidates(new_name: str, sibling_names: list[str],
                         min_shared: int = 2) -> list[str]:
    """Sibling files sharing >= min_shared name-tokens with new_name (tokenize on
    _-. , drop tokens < 3 chars) — the script-proliferation guard."""
    nt = _tokens(new_name)
    if len(nt) < min_shared:
        return []
    out = []
    for s in sibling_names:
        if s == new_name:
            continue
        if len(nt & _tokens(s)) >= min_shared:
            out.append(s)
    return out


def uncommitted_in_scope(changed_paths: list[str], scope_prefixes: list[str]) -> list[str]:
    """Changed paths under any build-scope prefix — the commit-before-build guard
    (don't bake unrecorded code into an image)."""
    norm = [p.replace("\\", "/") for p in scope_prefixes]
    return [p for p in changed_paths
            if any(p.replace("\\", "/").startswith(s) for s in norm)]
