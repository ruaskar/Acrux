# tests/test_phase2_score.py
import json
from benchmarks.phase2 import score


def _v(id, c, t):
    return {"id": id, "control": c, "treatment": t, "rationale": "x"}


def test_no_degradation_all_pass():
    s = score.summarize([_v("a", True, True), _v("b", True, True)])
    assert s["control_pass"] == 2 and s["treatment_pass"] == 2
    assert s["mcnemar_stat"] == 0.0 and s["mcnemar_p"] == 1.0


def test_discordant_counts_and_stat():
    # 3 control-only correct, 1 treatment-only → degradation signal
    v = [_v("a", True, False), _v("b", True, False), _v("c", True, False),
         _v("d", False, True), _v("e", True, True)]
    s = score.summarize(v)
    assert s["discordant"] == {"c_only": 3, "t_only": 1}
    # (|3-1|-1)^2/(3+1) = 1/4 = 0.25
    assert abs(s["mcnemar_stat"] - 0.25) < 1e-9
    assert 0.0 < s["mcnemar_p"] <= 1.0


def test_load_verdicts(tmp_path):
    (tmp_path / "q1.json").write_text(json.dumps(_v("q1", True, True)))
    (tmp_path / "q2.json").write_text(json.dumps(_v("q2", False, True)))
    got = score.load_verdicts(str(tmp_path))
    assert {r["id"] for r in got} == {"q1", "q2"}
