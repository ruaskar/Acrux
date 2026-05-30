"""wire.py — patch a coding agent's config to route through the keymd proxy.

`keymd init -g` writes the agent's base-URL into its settings file in place,
idempotently, with a one-time backup (<name>.keymd.bak) and a clean undo that
restores the user's prior value. Pure file ops live here; the base URL and the
agent's config path are resolved by `onboarding.wire_global`.
"""
from __future__ import annotations

import json
from pathlib import Path

_BAK_SUFFIX = ".keymd.bak"
_CLAUDE_KEY = "ANTHROPIC_BASE_URL"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _backup_once(path: Path) -> None:
    """Snapshot the original config exactly once, so undo can restore it."""
    bak = path.with_name(path.name + _BAK_SUFFIX)
    if path.exists() and not bak.exists():
        bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def apply_claude(cfg_path, base: str) -> Path:
    """Set env.ANTHROPIC_BASE_URL=<base> in a Claude Code settings.json, idempotently.
    Backs the original up once; creates the file (and parents) if absent. Refuses
    (raises ValueError, leaving the file untouched) if `env` exists but isn't an
    object — rather than silently discarding the user's data."""
    cfg_path = Path(cfg_path)
    data = _load(cfg_path)
    env = data.get("env")
    if env is not None and not isinstance(env, dict):
        raise ValueError(
            f'{cfg_path} has a non-object "env" ({type(env).__name__}); refusing to '
            "modify it — fix or remove that key, then re-run `keymd init -g`")
    _backup_once(cfg_path)                  # only after we've decided to write
    if env is None:
        env = data["env"] = {}
    env[_CLAUDE_KEY] = base
    _dump(cfg_path, data)
    return cfg_path


def undo_claude(cfg_path) -> bool:
    """Reverse apply_claude: restore env.ANTHROPIC_BASE_URL to its pre-keymd value
    (from the backup) or remove it if there was none. Returns True if anything changed."""
    cfg_path = Path(cfg_path)
    data = _load(cfg_path)
    env = data.get("env")
    if not isinstance(env, dict) or _CLAUDE_KEY not in env:
        return False
    bak = cfg_path.with_name(cfg_path.name + _BAK_SUFFIX)
    prior = _load(bak).get("env", {}).get(_CLAUDE_KEY) if bak.exists() else None
    if prior is None:
        env.pop(_CLAUDE_KEY, None)
        if not env:
            data.pop("env", None)
    else:
        env[_CLAUDE_KEY] = prior
    _dump(cfg_path, data)
    if bak.exists():
        bak.unlink()
    return True
