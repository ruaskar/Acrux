"""report.py — combined Phase-2 report: degradation guard + Phase-1 token
efficiency, always in SEPARATE sections, never blended into one number.

Public API:
  build(verdicts, *, efficiency=None) -> str
  main(argv) -> int
"""
from __future__ import annotations

import argparse
import glob
import json
import os

from benchmarks.phase2 import score


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_section_degradation(s: dict) -> str:
    """Render the ## Degradation guard section from a summarize() dict."""
    lines = ["## Degradation guard", ""]

    # pass@1 table
    lines.append(f"| Arm       | Pass | N  | Rate   |")
    lines.append(f"|-----------|------|----|--------|")
    lines.append(
        f"| Control   | {s['control_pass']:4d} | {s['n']:2d} | {s['control_rate']:.4f} |"
    )
    lines.append(
        f"| Treatment | {s['treatment_pass']:4d} | {s['n']:2d} | {s['treatment_rate']:.4f} |"
    )
    lines.append("")

    # discordant counts
    d = s["discordant"]
    lines.append(
        f"Discordant pairs — control-only: **{d['c_only']}**, treatment-only: **{d['t_only']}**"
    )
    lines.append("")

    # McNemar stat + p
    lines.append(
        f"McNemar chi2(1, continuity-corrected) = {s['mcnemar_stat']:.6f}, "
        f"p = {s['mcnemar_p']:.6f}"
    )
    lines.append("")

    # one-line verdict
    p = s["mcnemar_p"]
    cr = s["control_rate"]
    tr = s["treatment_rate"]
    if p >= 0.05:
        verdict = f"no statistically significant degradation (p={p:.6f})"
    elif tr < cr:
        verdict = f"significant degradation detected (p={p:.6f})"
    else:
        verdict = f"treatment outperformed control (p={p:.6f})"

    lines.append(f"**Verdict:** {verdict}")
    lines.append("")
    return "\n".join(lines)


def _fmt_section_efficiency(efficiency: dict | None) -> str:
    """Render the ## Token efficiency (Phase 1) section."""
    lines = ["## Token efficiency (Phase 1)", ""]

    if efficiency is None:
        lines.append("efficiency not provided")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Fixture | Variant | Reduction (%) |")
    lines.append("|---------|---------|---------------|")
    for fixture, data in sorted(efficiency.items()):
        reductions = data.get("reductions", {})
        for variant, pct in sorted(reductions.items()):
            lines.append(f"| {fixture} | {variant} | {pct:.1f} |")
    lines.append("")
    lines.append(
        "_Measured via deterministic token-count replay — no live API calls._"
    )
    lines.append("")
    return "\n".join(lines)


_HONEST_BOUNDARY = (
    "> **Honest boundary:** small repo-N; blind LLM judge (randomized labels); "
    "test.sh arm illustrative-few, not powered; efficiency and degradation measured "
    "on different substrates (deterministic replay vs live subagents) — "
    "reported separately, never blended."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build(verdicts: list[dict], *, efficiency: dict | None = None) -> str:
    """Build a combined markdown report.

    The degradation section and the efficiency section are ALWAYS kept
    separate; no blended or combined score is ever computed.
    """
    s = score.summarize(verdicts)

    parts = [
        "# keymd Phase-2 Benchmark Report",
        "",
        _fmt_section_degradation(s),
        _fmt_section_efficiency(efficiency),
        _HONEST_BOUNDARY,
        "",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build combined Phase-2 report (degradation + efficiency)."
    )
    parser.add_argument("--run-log", required=True,
                        help="Directory containing verdict *.json files.")
    parser.add_argument("--efficiency-corpus", default=None,
                        help="Directory of trajectory *.json files for Phase-1 replay.")
    args = parser.parse_args(argv)

    verdicts = score.load_verdicts(args.run_log)
    if not verdicts:
        print("WARNING: no verdict files found in --run-log dir")

    efficiency = None
    if args.efficiency_corpus:
        from benchmarks.replay_engine import replay
        from benchmarks.trajectory import load_trajectory

        efficiency = {}
        pattern = os.path.join(args.efficiency_corpus, "*.json")
        for path in sorted(glob.glob(pattern)):
            name = os.path.basename(path)
            try:
                traj = load_trajectory(path)
                result = replay(traj)
                efficiency[name] = {"reductions": result["reductions"]}
            except Exception as exc:  # noqa: BLE001
                efficiency[name] = {"error": str(exc)}

    print(build(verdicts, efficiency=efficiency))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
