"""The write-gate. Every side effect on an external app passes through here.

Forbidden effects are declared before the run, enforced in code, and counted.
A blocked attempt is recorded, never silently dropped: the trace shows
"attempted -> BLOCKED -> reason", which is what a reviewer needs to see.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class Blocked(Exception):
    pass


@dataclass
class Effect:
    app: str          # stripe | gmail | sheets | slack
    action: str       # e.g. "disputes.update", "messages.send"
    target: str       # dispute id, thread id, channel...
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    """One agent execution = one trace. Spans nest under it."""
    run_id: str
    dispute_id: str
    spans: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.time)

    def span(self, kind: str, name: str, **data: Any) -> dict[str, Any]:
        s = {"t": round(time.time() - self.started, 3), "kind": kind, "name": name, **data}
        self.spans.append(s)
        return s

    def dump(self, root: Path = Path("runs")) -> Path:
        root.mkdir(exist_ok=True)
        p = root / f"{self.run_id}.json"
        p.write_text(json.dumps({"run_id": self.run_id, "dispute_id": self.dispute_id, "spans": self.spans}, indent=1))
        return p


Rule = Callable[[Effect, "GateState"], str | None]  # returns a reason to block, or None


@dataclass
class GateState:
    approved: set[str] = field(default_factory=set)       # dispute ids a human approved in Slack
    emailed: set[str] = field(default_factory=set)        # customers already notified (per dispute)
    acted: set[str] = field(default_factory=set)          # dispute ids already filed
    uncited_claims: int = 0                                # set by the packet builder before submit
    called: set[str] = field(default_factory=set)         # dispute ids the customer was already called about


# ---- Forbidden effects, declared up front. Names appear verbatim in the README. ----

def no_submit_without_approval(e: Effect, s: GateState) -> str | None:
    if e.app == "stripe" and e.action == "disputes.update" and e.params.get("submit") is True:
        if e.target not in s.approved:
            return "SUBMIT_WITHOUT_HUMAN_APPROVAL"
    return None


def no_double_filing(e: Effect, s: GateState) -> str | None:
    if e.app == "stripe" and e.action == "disputes.update" and e.params.get("submit") is True:
        if e.target in s.acted:
            return "DUPLICATE_FILING_SAME_DISPUTE"
    return None


def no_uncited_claims(e: Effect, s: GateState) -> str | None:
    if e.app == "stripe" and e.action == "disputes.update" and s.uncited_claims > 0:
        return f"UNCITED_CLAIMS_IN_PACKET({s.uncited_claims})"
    return None


def no_ce3_prefilled_edits(e: Effect, s: GateState) -> str | None:
    # Stripe pre-populates the disputed_transaction IP and product description; editing them
    # breaks CE3.0 eligibility. The agent may only ADD identifiers, never overwrite these two.
    ce3 = (e.params.get("evidence", {}).get("enhanced_evidence", {}).get("visa_compelling_evidence_3", {}))
    dt = ce3.get("disputed_transaction", {})
    if "customer_purchase_ip" in dt or "product_description" in dt:
        return "EDITED_CE3_PREFILLED_FIELD"
    return None


def one_customer_notice_per_dispute(e: Effect, s: GateState) -> str | None:
    # one notice per dispute across channels: an email OR a text, never both, never twice
    if e.app in ("gmail", "photon") and e.action == "messages.send":
        if e.target in s.emailed:
            return "SECOND_NOTICE_TO_CUSTOMER"
    return None


def one_call_per_dispute(e: Effect, s: GateState) -> str | None:
    if e.app == "calle" and e.action == "calls.create":
        if e.target in s.called:
            return "SECOND_CALL_TO_CUSTOMER"
    return None


def no_refunds(e: Effect, s: GateState) -> str | None:
    if e.app == "stripe" and e.action.startswith("refunds."):
        return "REFUND_OUTSIDE_SCOPE"
    return None


FORBIDDEN: list[Rule] = [
    no_submit_without_approval,
    no_double_filing,
    no_uncited_claims,
    no_ce3_prefilled_edits,
    one_customer_notice_per_dispute,
    one_call_per_dispute,
    no_refunds,
]


class Gate:
    def __init__(self, trace: Trace, state: GateState | None = None, rules: list[Rule] | None = None):
        self.trace = trace
        self.state = state or GateState()
        self.rules = rules or FORBIDDEN
        self.blocked = 0
        self.allowed = 0

    def __call__(self, effect: Effect, do: Callable[[], Any]) -> Any:
        for rule in self.rules:
            why = rule(effect, self.state)
            if why:
                self.blocked += 1
                self.trace.span("effect", f"{effect.app}.{effect.action}", target=effect.target, result="BLOCKED", reason=why)
                raise Blocked(why)
        out = do()
        self.allowed += 1
        self.trace.span("effect", f"{effect.app}.{effect.action}", target=effect.target, result="OK")
        # bookkeeping the rules depend on
        if effect.app in ("gmail", "photon") and effect.action == "messages.send":
            self.state.emailed.add(effect.target)
        if effect.app == "calle" and effect.action == "calls.create":
            self.state.called.add(effect.target)
        if effect.app == "stripe" and effect.action == "disputes.update" and effect.params.get("submit") is True:
            self.state.acted.add(effect.target)
        return out
