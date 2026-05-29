from keymd.watcher.debounce import Debouncer


def test_coalesces_rapid_calls():
    calls = []
    d = Debouncer(delay=1.0, fn=calls.append)
    d.submit("a.py", now=0.0)
    d.submit("a.py", now=0.3)
    d.flush_due(now=0.5); assert calls == []          # still within quiet window
    d.flush_due(now=1.4); assert calls == ["a.py"]    # fired once after delay


def test_independent_paths():
    calls = []
    d = Debouncer(delay=1.0, fn=calls.append)
    d.submit("a.py", now=0.0); d.submit("b.py", now=0.6)
    d.flush_due(now=1.1); assert calls == ["a.py"]
    d.flush_due(now=1.7); assert calls == ["a.py", "b.py"]
