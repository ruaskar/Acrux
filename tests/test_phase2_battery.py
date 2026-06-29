# tests/test_phase2_battery.py
import json
import pytest
from benchmarks.phase2.battery import schema

REPO = __import__("pathlib").Path(__file__).parent.parent
SELF = REPO / "benchmarks" / "phase2" / "battery" / "keymd_self.json"


def test_loads_and_validates_self_battery():
    recs = schema.load_battery(str(SELF))
    assert len(recs) >= 5                      # power: several questions
    for r in recs:
        assert r["id"] and r["q"] and r["key"]
        assert isinstance(r["files"], list) and r["files"]
        assert r["type"] in {"comprehension", "structure", "trace", "locate", "detail/fix"}


def test_rejects_empty_key(tmp_path):
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps([{"id": "X", "type": "locate", "q": "q?",
                                "files": ["a.py"], "key": ""}]))
    with pytest.raises(ValueError, match="X"):
        schema.load_battery(str(bad))


def test_every_self_file_exists():
    recs = schema.load_battery(str(SELF))
    for r in recs:
        for f in r["files"]:
            assert (REPO / f).exists(), f"{r['id']} references missing {f}"
