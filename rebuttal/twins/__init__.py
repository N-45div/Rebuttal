"""Local stateful twins of the four apps.

Seedable, resettable, and they record every call and every state change.
The eval suite runs against these; the live demo runs against the real apps.
Both go through the same client interface, so the agent code is identical.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Call:
    app: str
    op: str
    args: dict[str, Any]
    result: Any = None


class Twin:
    app = "twin"

    def __init__(self, seed: dict[str, Any] | None = None):
        self._seed = copy.deepcopy(seed or {})
        self.reset()

    def reset(self) -> None:
        self.state = copy.deepcopy(self._seed)
        self.calls: list[Call] = []
        self.effects: list[dict[str, Any]] = []   # state changes, for the evidence log

    def _rec(self, op: str, result: Any = None, **args: Any) -> Any:
        self.calls.append(Call(self.app, op, args, result))
        return result

    def _effect(self, what: str, **data: Any) -> None:
        self.effects.append({"app": self.app, "change": what, **data})


class StripeTwin(Twin):
    """Mirrors the slice of the disputes API the agent touches, including the CE3.0 validator."""
    app = "stripe"

    def dispute(self, dispute_id: str) -> dict[str, Any]:
        return self._rec("disputes.retrieve", copy.deepcopy(self.state["disputes"][dispute_id]), id=dispute_id)

    def charge(self, charge_id: str) -> dict[str, Any]:
        return self._rec("charges.retrieve", copy.deepcopy(self.state["charges"][charge_id]), id=charge_id)

    def charges_for_fingerprint(self, fingerprint: str, customer: str | None = None) -> list[dict[str, Any]]:
        out = [c for c in self.state["charges"].values() if c.get("fingerprint") == fingerprint and not c.get("disputed")]
        return self._rec("charges.search", copy.deepcopy(out), fingerprint=fingerprint)

    def update_dispute(self, dispute_id: str, evidence: dict[str, Any], submit: bool) -> dict[str, Any]:
        d = self.state["disputes"][dispute_id]
        if d["status"] != "needs_response":
            raise RuntimeError("dispute is not open")
        d["evidence"] = evidence
        d["ce3_status"] = self._grade_ce3(d, evidence)
        self._effect("dispute.evidence_staged", id=dispute_id, ce3=d["ce3_status"])
        if submit:
            d["status"] = "under_review"
            d["submission_count"] = d.get("submission_count", 0) + 1
            self._effect("dispute.submitted", id=dispute_id)
            # test-mode style verdict: won iff the packet clears the reason-code checklist
            d["status"] = "won" if d.get("_would_win") else "lost"
            self._effect("dispute.closed", id=dispute_id, status=d["status"])
        return self._rec("disputes.update", copy.deepcopy(d), id=dispute_id, submit=submit)

    @staticmethod
    def _grade_ce3(d: dict[str, Any], evidence: dict[str, Any]) -> str:
        """Same rule Stripe applies in test mode: two prior undisputed charges on the card and
        two of four identifiers matching across them, at least one being IP or device."""
        ce3 = evidence.get("enhanced_evidence", {}).get("visa_compelling_evidence_3", {})
        priors = ce3.get("prior_undisputed_transactions", [])
        if len(priors) < 2:
            return "requires_action:missing_prior_undisputed_transactions"
        dt = ce3.get("disputed_transaction", {})
        keys = ["customer_purchase_ip", "customer_device_fingerprint", "customer_account_id", "shipping_address"]
        strong = {"customer_purchase_ip", "customer_device_fingerprint"}
        base = {k: dt.get(k) or d.get("prefilled", {}).get(k) for k in keys}
        matched = [k for k in keys if base[k] and all(p.get(k) == base[k] for p in priors)]
        if len(matched) >= 2 and strong & set(matched):
            return "qualified"
        return "requires_action:missing_customer_identifiers"


class GmailTwin(Twin):
    app = "gmail"

    def search(self, email: str) -> list[dict[str, Any]]:
        out = [m for m in self.state.get("messages", []) if m["from"] == email or m["to"] == email]
        return self._rec("messages.list", copy.deepcopy(out), q=email)

    def send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        msg = {"id": f"msg_{len(self.state.setdefault('sent', [])) + 1}", "to": to, "subject": subject, "body": body}
        self.state["sent"].append(msg)
        self._effect("message.sent", to=to, subject=subject)
        return self._rec("messages.send", msg, to=to)


class SheetsTwin(Twin):
    """The order ledger: one row per order, with tracking and refund columns."""
    app = "sheets"

    def order(self, order_id: str) -> dict[str, Any] | None:
        row = next((r for r in self.state.get("orders", []) if r["order_id"] == order_id), None)
        return self._rec("values.get", copy.deepcopy(row), order_id=order_id)

    def append_outcome(self, row: dict[str, Any]) -> None:
        self.state.setdefault("outcomes", []).append(row)
        self._effect("row.appended", sheet="outcomes", dispute=row.get("dispute_id"))
        self._rec("values.append", None, **row)


class SlackTwin(Twin):
    app = "slack"

    def post(self, channel: str, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        msg = {"ts": f"{len(self.state.setdefault('posts', [])) + 1}.0", "channel": channel, "text": text, "blocks": blocks or []}
        self.state["posts"].append(msg)
        self._effect("message.posted", channel=channel)
        return self._rec("chat.postMessage", msg, channel=channel)

    def await_approval(self, ts: str) -> bool:
        # In the twin the scenario decides what the human clicks.
        return self._rec("interaction.wait", bool(self.state.get("human_clicks_approve", True)), ts=ts)


class PhotonTwin(Twin):
    """Texts only land in threads that already exist; a cold number raises, like the real line."""
    app = "photon"

    def send(self, to: str, text: str) -> dict[str, Any]:
        if to not in self.state.get("threads", []):
            self._rec("messages.send", None, to=to)
            raise RuntimeError("photon send failed: no_existing_thread")
        msg = {"id": f"txt_{len(self.state.setdefault('sent', [])) + 1}", "to": to, "text": text}
        self.state["sent"].append(msg)
        self._effect("message.sent", to=to)
        return self._rec("messages.send", msg, to=to)
