"""live.py — optional background filesystem watcher for serve/graph.

Reuses keymd's tested watcher (engine watches files, not the agent's tools), so
.key.md + the index + search stay fresh on every edit AND new file — including
edits made with the agent's native tools or your own editor, which keymd_edit
alone would miss. Daemon thread: dies with the process. Soft dependency on the
`watch` extra (watchdog) — returns None (no live refresh) if it's not installed,
never raises."""
from __future__ import annotations


def spawn_watcher(root: str, delay: float = 0.6):
    """Start keymd's filesystem observer as a daemon thread. Returns the running
    observer (call .stop()/.join() to end early) or None if watchdog is absent."""
    try:
        from keymd.watcher.run import build_observer
    except ImportError:
        return None
    try:
        obs = build_observer(root, delay=delay)
    except ImportError:          # watchdog imported lazily inside build_observer
        return None
    deb = obs._keymd_debouncer
    import threading
    import time

    def _flush_loop():
        while obs.is_alive():
            time.sleep(delay / 2)
            deb.flush_due(now=time.monotonic())

    obs.daemon = True
    obs.start()
    t = threading.Thread(target=_flush_loop, daemon=True)
    t.start()
    return obs
