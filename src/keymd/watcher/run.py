"""run.py — watchdog wiring over the debouncer + dispatcher.

Pure logic (dispatch, debounce) is unit-tested directly; this module is the
thin OS-watch shell. `keymd watch` runs it until interrupted."""
from __future__ import annotations

import time
from pathlib import Path

from keymd.engine import config
from keymd.engine.parsers.base import get_parser_for
from keymd.watcher.debounce import Debouncer
from keymd.watcher.dispatch import on_change


def _relevant(path: str) -> bool:
    if config.is_excluded(path):
        return False
    return path.endswith(".key.md") or get_parser_for(Path(path)) is not None


def build_observer(root: str, delay: float = 0.6):
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    deb = Debouncer(delay=delay, fn=on_change)

    class _Handler(FileSystemEventHandler):
        def _maybe(self, path: str) -> None:
            if _relevant(path):
                deb.submit(path, now=time.monotonic())

        def on_modified(self, event):
            if not event.is_directory:
                self._maybe(event.src_path)

        def on_created(self, event):
            if not event.is_directory:
                self._maybe(event.src_path)

    obs = Observer()
    obs.schedule(_Handler(), root, recursive=True)
    obs._keymd_debouncer = deb  # exposed for the flush loop + smoke test
    return obs


def serve(root: str | None = None, delay: float = 0.6) -> None:
    root = root or str(config.project_root())
    obs = build_observer(root, delay=delay)
    deb = obs._keymd_debouncer
    obs.start()
    print(f"keymd watch on {root} (debounce {delay}s) — Ctrl-C to stop")
    try:
        while True:
            time.sleep(delay / 2)
            deb.flush_due(now=time.monotonic())
    except KeyboardInterrupt:
        pass
    finally:
        obs.stop()
        obs.join()
