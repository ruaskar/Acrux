"""ab_harness.py — OFFLINE token-efficiency report (Phase 1). $0, no API.
Replays trajectories through Acrux's shipped transforms and prints token cuts.
Efficiency only — task-degradation is the separate paid live A/B (Phase 2)."""
from __future__ import annotations

import argparse, json, glob, os
from benchmarks.trajectory import load_trajectory
from benchmarks import replay_engine

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "trajectories")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=_FIX)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = {}
    for path in sorted(glob.glob(os.path.join(a.corpus, "*.json"))):
        rep = replay_engine.replay(load_trajectory(path))
        rows[os.path.basename(path)] = rep
    if a.json:
        print(json.dumps(rows, indent=2)); return 0
    print(f"{'fixture':28} {'raw':>8} {'gate':>8} {'+bound':>8} {'+cache':>8}  red%")
    for name, r in rows.items():
        t = r["totals"]
        print(f"{name:28} {t['raw']:>8} {t['gate']:>8} {t['gate_bound']:>8} "
              f"{t['gate_bound_cache']:>8}  {r['reductions']['gate_bound']:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
