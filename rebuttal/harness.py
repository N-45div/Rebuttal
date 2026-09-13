"""Self-improving harness. Tightens only.

After runs, read the outcomes and propose policy changes:
  * a SUBMIT that LOST  -> the evidence that was absent on that run becomes REQUIRED for that reason code
  * a HOLD that a human overrode and then WON -> reported, never applied (loosening is a human edit)

Changes are written to policy_overrides.json as additions to `must`. The harness can add a
requirement; it can never remove one. So the agent gets stricter with every loss and never
looser on its own. A human loosens by editing the file.

    python -m rebuttal.harness            # propose + apply from runs/ and the ledger
    python -m rebuttal.harness --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .policy import POLICY, Evidence, Requirement

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "policy_overrides.json"

ALL = [e.value for e in Evidence]


@dataclass
class Proposal:
    reason: str
    kind: str
    add: list[str]        # evidence values to add to `must`
    because: str          # run id / dispute id


def load_overrides(path: Path = OVERRIDES) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def apply_overrides(overrides: dict[str, list[str]], policy: dict[tuple[str, str], Requirement] = POLICY) -> None:
    """Additions only. Unknown evidence names are ignored, never invented."""
    for key, adds in overrides.items():
        reason, kind = key.split("/")
        req = policy.get((reason, kind))
        if req is None:
            continue
        for v in adds:
            if v in ALL:
                req.must.add(Evidence(v))


def propose(outcomes: list[dict[str, Any]]) -> list[Proposal]:
    """outcomes: rows with reason, kind, verdict, outcome, have (evidence present on that run), run_id."""
    out: list[Proposal] = []
    for row in outcomes:
        if row.get("verdict") == "submit" and row.get("outcome") == "lost":
            have = set(row.get("have", []))
            # candidate tightenings: evidence that is meaningful for this reason and was absent
            candidates = [v for v in _relevant(row["reason"]) if v not in have]
            if candidates:
                out.append(Proposal(row["reason"], row.get("kind", "physical"), candidates, row.get("run_id", "?")))
    return out


def _relevant(reason: str) -> list[str]:
    table = {
        "product_not_received": [Evidence.TRACKING_SIGNATURE, Evidence.SHIPPING_ADDRESS_MATCH, Evidence.CUSTOMER_COMMUNICATION],
        "fraudulent": [Evidence.TRACKING_SIGNATURE, Evidence.SHIPPING_ADDRESS_MATCH, Evidence.CUSTOMER_COMMUNICATION],
        "duplicate": [Evidence.CUSTOMER_COMMUNICATION],
        "product_unacceptable": [Evidence.TRACKING_SIGNATURE, Evidence.REFUND_POLICY_SHOWN],
        "credit_not_processed": [Evidence.TRACKING_DELIVERED],
        "unrecognized": [Evidence.TRACKING_SIGNATURE, Evidence.CUSTOMER_COMMUNICATION],
    }
    return [e.value for e in table.get(reason, [])]


def tighten(proposals: list[Proposal], overrides: dict[str, list[str]]) -> dict[str, list[str]]:
    """Merge proposals into overrides. Set-union only: nothing is ever removed."""
    merged = {k: list(v) for k, v in overrides.items()}
    for p in proposals:
        key = f"{p.reason}/{p.kind}"
        cur = set(merged.get(key, []))
        cur |= set(p.add)
        merged[key] = sorted(cur)
    return merged


def read_outcomes(runs_dir: Path = ROOT / "runs") -> list[dict[str, Any]]:
    rows = []
    for f in sorted(runs_dir.glob("*.json")):
        try:
            t = json.loads(f.read_text())
        except Exception:
            continue
        spans = t.get("spans", [])
        dec = next((s for s in spans if s.get("name") == "policy.decide"), None)
        rep = next((s for s in spans if s.get("kind") == "report"), None)
        if not dec or not rep:
            continue
        text = rep.get("text", "")
        outcome = text.split("->")[1].split("|")[0].strip() if "->" in text else ""
        rows.append({"run_id": t.get("run_id"), "reason": dec.get("reason_code", ""), "kind": dec.get("fulfilment", "physical"),
                     "verdict": dec.get("verdict"), "outcome": outcome, "have": dec.get("have", [])})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    rows = read_outcomes()
    props = propose(rows)
    before = load_overrides()
    after = tighten(props, before)
    for p in props:
        print(f"tighten {p.reason}/{p.kind}: require {', '.join(p.add)}  (run {p.because} lost)")
    if not props:
        print("no losses on file: nothing to tighten")
    added = {k: sorted(set(after.get(k, [])) - set(before.get(k, []))) for k in after}
    added = {k: v for k, v in added.items() if v}
    print("new requirements:", json.dumps(added) if added else "none")
    if not args.dry_run and added:
        OVERRIDES.write_text(json.dumps(after, indent=1))
        print("wrote", OVERRIDES.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
