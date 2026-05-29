import pytest

pytest.importorskip("watchdog")

from keymd.watcher import run  # noqa: E402
from keymd.watcher.dispatch import on_change  # noqa: E402
import keymd.engine.parsers.python  # noqa: F401,E402


def test_build_observer_wires_debouncer_and_filter(env_proj):
    obs = run.build_observer(str(env_proj), delay=0.5)
    deb = obs._keymd_debouncer
    assert deb.fn is on_change and deb.delay == 0.5
    # relevance filter: source + .key.md in, excluded dirs out
    assert run._relevant(str(env_proj / "pkg" / "parser.py")) is True
    assert run._relevant(str(env_proj / "pkg" / "parser.key.md")) is True
    assert run._relevant(str(env_proj / ".git" / "config")) is False
    # do NOT start the observer in CI (no real OS watch)
