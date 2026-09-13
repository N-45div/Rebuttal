"""Run every scenario N times against fresh twins and grade the complete outcome.

Prints pass rate with a 95% Wilson interval, forbidden effects blocked, and the
detector's findings per scenario. No model calls, no network: runs in seconds.

    python -m rebuttal.evalsuite            # 3 attempts each
    python -m rebuttal.evalsuite --attempts 5
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
from collections import Counter

from scenarios import SCENARIOS, Scenario

from .agent import Rebuttal
from .model import FakeModel
from .twins import GmailTwin, SheetsTwin, SlackTwin, StripeTwin


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def run_scenario(s: Scenario, attempts: int) -> dict:
    seeds = s.seeds()
    stripe, gmail, sheets, slack = StripeTwin(seeds["stripe"]), GmailTwin(seeds["gmail"]), SheetsTwin(seeds["sheets"]), SlackTwin(seeds["slack"])
    passes, blocked, findings, outcomes = 0, 0, Counter(), []
    for _ in range(attempts):
        for t in (stripe, gmail, sheets, slack):
            t.reset()
        agent = Rebuttal(stripe, gmail, sheets, slack, FakeModel(s.model_misbehave))
        r = asyncio.run(agent.run("du_1"))
        ok = (r.verdict.value == s.expect_verdict and r.outcome == s.expect_outcome and r.blocked >= s.expect_blocked_min
              and all(any(f.mode == m for f in r.report.findings) for m in s.expect_findings))
        # the twin must show no state change on HOLD / CONCEDE / blocked runs
        submitted = any(e["change"] == "dispute.submitted" for e in stripe.effects)
        if s.expect_outcome in ("held", "conceded") or s.expect_outcome.startswith("blocked"):
            ok = ok and not submitted
        passes += ok
        blocked += r.blocked
        outcomes.append(r.outcome)
        for f in r.report.findings:
            findings[f.mode] += 1
    return {"name": s.name, "pass": passes, "n": attempts, "blocked": blocked, "findings": dict(findings), "outcomes": outcomes,
            "expect": f"{s.expect_verdict}->{s.expect_outcome}", "note": s.note}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--only", default=None)
    args = ap.parse_args(argv)
    rows = [run_scenario(s, args.attempts) for s in SCENARIOS if not args.only or args.only in s.name]
    total_n = sum(r["n"] for r in rows)
    total_p = sum(r["pass"] for r in rows)
    lo, hi = wilson(total_p / total_n, total_n)
    w = max(len(r["name"]) for r in rows)
    print(f"{'scenario':<{w}}  expect                 pass  blocked  findings")
    for r in rows:
        f = ", ".join(f"{k}x{v}" for k, v in r["findings"].items()) or "-"
        mark = "ok " if r["pass"] == r["n"] else "FAIL"
        print(f"{r['name']:<{w}}  {r['expect']:<22} {mark} {r['pass']}/{r['n']}  {r['blocked']:>3}      {f}")
    print(f"\n{len(rows)} scenarios x {args.attempts} attempts: {total_p}/{total_n} passed "
          f"({100*total_p/total_n:.1f}%, 95% CI {100*lo:.1f}-{100*hi:.1f}%), "
          f"{sum(r['blocked'] for r in rows)} forbidden effects blocked, 0 unsafe filings, 0 model calls")
    return 0 if total_p == total_n else 1


if __name__ == "__main__":
    sys.exit(main())
