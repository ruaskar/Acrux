"""config.py — env / auto-detect path resolution for the keymd engine.

Precedence for project root: KEYMD_PROJECT_ROOT → git toplevel → cwd.
Other env overrides:
  KEYMD_INDEX_PATH       absolute path to .keymd/index.db
  KEYMD_INDEX_DIRS       colon-separated subdir names to walk
  KEYMD_EXCLUDE_PATTERNS colon-separated extra path-substring exclusions
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

# Source-file extensions that have a registered parser. parsers.base appends to
# this set at import time; config keeps it so index.py can ask without importing
# parsers (avoids a cycle).
REGISTERED_EXTENSIONS: set[str] = set()

DEFAULT_EXCLUDES = (
    "/__pycache__/", "/.git/", "/.venv/", "/venv/", "/node_modules/",
    "/.next/", "/dist/", "/build/", "/.ruff_cache/", "/.keymd/",
    "/.claude/", "/.pytest_cache/", "/.mypy_cache/",
)
SKIP_TOP_DIRS = {
    "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".next", ".git", ".keymd", ".ruff_cache", ".claude", ".pytest_cache",
    ".mypy_cache", "target",
}


@lru_cache(maxsize=1)
def _git_toplevel() -> Path | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, timeout=2,
        )
        p = Path(r.stdout.strip())
        return p if p.exists() else None
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired):
        return None


def _env_path(name: str) -> Path | None:
    v = os.environ.get(name)
    if not v:
        return None
    v = os.path.expanduser(os.path.expandvars(v))
    p = Path(v)
    return p if p.exists() else None


def project_root() -> Path:
    p = _env_path("KEYMD_PROJECT_ROOT")
    if p:
        return Path(os.path.realpath(p))
    gt = _git_toplevel()
    if gt:
        return Path(os.path.realpath(gt))
    return Path(os.path.realpath(Path.cwd()))


def canonical(path: str | Path) -> str:
    """The single canonical path key used by EVERY faculty — build, query,
    refresh, sync_one, the proxy, and the watcher. realpath resolves symlinks
    AND normalizes on-disk case, so a path keyed by one faculty is always found
    by another regardless of casing, relative form, or symlinked roots.
    (os.path.abspath does NOT case-normalize, which silently split the faculties.)"""
    return os.path.realpath(path)


def index_path() -> Path:
    v = os.environ.get("KEYMD_INDEX_PATH")
    if v:
        return Path(os.path.expanduser(os.path.expandvars(v)))
    return project_root() / ".keymd" / "index.db"


def index_extensions() -> tuple[str, ...]:
    return tuple(sorted(REGISTERED_EXTENSIONS)) or (".py",)


def index_roots() -> list[Path]:
    pr = project_root()
    v = os.environ.get("KEYMD_INDEX_DIRS")
    if v:
        out = []
        for d in v.split(":"):
            d = d.strip()
            if not d:
                continue
            d = os.path.expanduser(os.path.expandvars(d))
            p = Path(d)
            out.append(p if p.is_absolute() else pr / p)
        return out
    out = []
    for child in sorted(pr.iterdir()):
        if (not child.is_dir() or child.name.startswith(".")
                or child.name in SKIP_TOP_DIRS):
            continue
        try:
            for ext in index_extensions():
                if next(child.rglob(f"*{ext}"), None):
                    out.append(child)
                    break
        except (PermissionError, OSError):
            continue
    return out


def exclude_patterns() -> tuple[str, ...]:
    extra = os.environ.get("KEYMD_EXCLUDE_PATTERNS", "")
    extras = tuple(p for p in extra.split(":") if p)
    return DEFAULT_EXCLUDES + extras


def is_excluded(path: str) -> bool:
    norm = path.replace(os.sep, "/")
    return any(pat in norm for pat in exclude_patterns())


@lru_cache(maxsize=1)
def project_pkg_prefixes() -> set[str]:
    """Top-level package names used by the import-gate heuristic in graph.py."""
    return {r.name for r in index_roots()}
