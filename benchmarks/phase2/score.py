"""score.py — paired-binary scoring of the degradation arm: pass@1 per arm and
McNemar's test (continuity-corrected) on the discordant pairs."""
from __future__ import annotations

import glob
import json
import math
import os


def load_verdicts(dir_path: str) -> list[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(dir_path, "*.json"))):
        with open(p, encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out


def _chi2_sf_1df(x: float) -> float:
    # survival function of chi-square with 1 dof = erfc(sqrt(x/2))
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2.0))


def summarize(verdicts: list[dict]) -> dict:
    n = len(verdicts)
    cp = sum(1 for v in verdicts if v["control"])
    tp = sum(1 for v in verdicts if v["treatment"])
    b = sum(1 for v in verdicts if v["control"] and not v["treatment"])   # control-only
    c = sum(1 for v in verdicts if v["treatment"] and not v["control"])   # treatment-only
    if b + c == 0:
        stat, p = 0.0, 1.0
    else:
        stat = (abs(b - c) - 1) ** 2 / (b + c)
        stat = max(stat, 0.0)
        p = _chi2_sf_1df(stat)
    return {"n": n, "control_pass": cp, "treatment_pass": tp,
            "control_rate": round(cp / n, 4) if n else 0.0,
            "treatment_rate": round(tp / n, 4) if n else 0.0,
            "discordant": {"c_only": b, "t_only": c},
            "mcnemar_stat": round(stat, 6), "mcnemar_p": round(p, 6)}
