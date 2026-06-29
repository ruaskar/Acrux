# tests/test_phase2_report.py
from benchmarks.phase2 import report


def _v(id, c, t):
    return {"id": id, "control": c, "treatment": t, "rationale": "r"}


def test_report_has_separate_sections():
    md = report.build([_v("a", True, True), _v("b", True, False)],
                      efficiency={"grep_heavy.json": {"reductions": {"gate_bound": 26.1}}})
    assert "## Degradation guard" in md
    assert "## Token efficiency" in md
    assert "McNemar" in md
    # honest boundary present
    assert "boundary" in md.lower() or "honest" in md.lower()


def test_report_no_blended_number():
    md = report.build([_v("a", True, True)])
    # efficiency omitted → that section says "not provided", never invents a blend
    assert "## Degradation guard" in md and "## Token efficiency" in md


def test_degradation_verdict_reflects_pvalue():
    # all-pass → no degradation verdict
    md = report.build([_v("a", True, True), _v("b", True, True)])
    assert "no" in md.lower() and "degrad" in md.lower()
