"""The orchestrator. One dispute in, one of three verdicts out, every write gated.

    gather (3 sub-agents, concurrent) -> assess -> decide -> write -> review
        -> Slack (approve/hold) -> Stripe submit -> Gmail notice -> Sheets ledger -> Slack report
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .detector import Report, detect
from .gate import Blocked, Effect, Gate, GateState, Trace
from .model import Model
from .policy import PHYSICAL, Decision, Evidence, Verdict, decide
from .harness import apply_overrides, load_overrides

DISPUTE_FEE_CENTS = 1500
CE3_MIN_DAYS, CE3_MAX_DAYS = 120, 365


@dataclass
class Bundle:
    dispute: dict[str, Any]
    charge: dict[str, Any]
    order: dict[str, Any] | None
    thread: list[dict[str, Any]]
    priors: list[dict[str, Any]]
    facts: list[dict[str, Any]] = field(default_factory=list)   # [{id, text}]

    @property
    def record_ids(self) -> list[str]:
        return [f["id"] for f in self.facts]

    def as_dict(self) -> dict[str, Any]:
        return {"record_ids": self.record_ids, "facts": {f["id"]: f["text"] for f in self.facts}}


@dataclass
class RunResult:
    run_id: str
    dispute_id: str
    verdict: Verdict
    decision: Decision
    outcome: str                 # won | lost | held | conceded | blocked:<reason>
    amount_cents: int
    recovered_cents: int
    blocked: int
    report: Report
    trace: Trace
    ce3_status: str | None = None


def _order_id_from_charge(charge: dict[str, Any]) -> str:
    meta = charge.get("metadata") or {}
    if meta.get("order_id"):
        return str(meta["order_id"])
    parts = (charge.get("description") or "").split()
    return parts[1] if len(parts) > 1 else ""


class Rebuttal:
    def __init__(self, stripe, gmail, sheets, slack, model: Model, channel: str = "#rebuttal", now: datetime | None = None, photon=None):
        self.stripe, self.gmail, self.sheets, self.slack, self.model = stripe, gmail, sheets, slack, model
        self.photon = photon  # optional fifth app: text the customer instead of emailing, when a phone is on file
        apply_overrides(load_overrides())  # tighten-only requirements learned from past losses
        self.channel = channel
        self.now = now or datetime.now(timezone.utc)

    # ---------- gather: three sub-agents, dispatched concurrently ----------
    async def gather(self, dispute_id: str, trace: Trace) -> Bundle:
        dispute = self.stripe.dispute(dispute_id)
        charge = self.stripe.charge(dispute["charge"])
        order_id = _order_id_from_charge(charge)
        email = (charge.get("billing_details") or {}).get("email") or charge.get("receipt_email") or ""

        async def sheets_agent():
            if not order_id:
                trace.span("gather", "sheets.order", result="skipped", why="charge carries no order id")
                return None
            row = await asyncio.to_thread(self.sheets.order, order_id)
            trace.span("gather", "sheets.order", result="ok" if row else "empty")
            return row

        async def gmail_agent():
            if not email:
                trace.span("gather", "gmail.thread", result="skipped", why="charge carries no customer email")
                return []
            msgs = await asyncio.to_thread(self.gmail.search, email)
            trace.span("gather", "gmail.thread", result="ok" if msgs else "empty")
            return msgs

        async def stripe_prior_agent():
            card = (charge.get("payment_method_details") or {}).get("card") or {}
            fp = card.get("fingerprint") or charge.get("fingerprint")
            cust = charge.get("customer")
            priors = await asyncio.to_thread(self.stripe.charges_for_fingerprint, fp, cust) if fp else []
            priors = [p for p in priors if p["id"] != charge["id"]]
            trace.span("gather", "stripe.prior_charges", result="ok" if priors else "empty", count=len(priors))
            return priors

        order, thread, priors = await asyncio.gather(sheets_agent(), gmail_agent(), stripe_prior_agent())
        b = Bundle(dispute, charge, order, thread, priors)
        self._facts(b)
        return b

    def _facts(self, b: Bundle) -> None:
        c, o = b.charge, b.order
        b.facts.append({"id": f"stripe:{c['id']}", "text": f"Charge {c['id']} for ${c['amount']/100:.2f} on {c.get('created_iso', '')}; AVS {c.get('avs', 'n/a')}, CVC {c.get('cvc', 'n/a')}"})
        if o:
            b.facts.append({"id": f"sheets:{o['order_id']}", "text": f"Order {o['order_id']}: {o.get('items', '')} shipped {o.get('ship_date', '')} via {o.get('carrier', '')} to {o.get('ship_to', '')}; fulfilment {o.get('kind', PHYSICAL)}"})
            if o.get("tracking"):
                sig = "image on file" if o.get("signature_image") else (o.get("signed_by") or "none")
                b.facts.append({"id": f"carrier:{o['tracking']}", "text": f"Tracking {o['tracking']} status {o.get('tracking_status', '')} on {o.get('delivered_at', '')}; signature {sig}"})
            if o.get("refunded_at"):
                b.facts.append({"id": f"sheets:{o['order_id']}:refund", "text": f"Order {o['order_id']} was refunded on {o['refunded_at']}"})
        for m in b.thread[:3]:
            b.facts.append({"id": f"gmail:{m['id']}", "text": f"Email {m.get('date', '')} from {m.get('from', '')}: \"{m.get('snippet', '')}\""})
        for p in b.priors[:4]:
            b.facts.append({"id": f"stripe:{p['id']}", "text": f"Prior undisputed charge {p['id']} for ${p['amount']/100:.2f} on {p.get('created_iso', '')} (IP {p.get('ip', '')}, ship-to {p.get('ship_to', '')})"})

    # ---------- assess: deterministic evidence checks ----------
    def assess(self, b: Bundle) -> tuple[set[Evidence], str]:
        have: set[Evidence] = set()
        o, c = b.order, b.charge
        kind = (o or {}).get("kind", PHYSICAL)
        if o:
            have.add(Evidence.ORDER_RECORD)
            if o.get("tracking_status") == "delivered":
                have.add(Evidence.TRACKING_DELIVERED)
            if o.get("signature_image"):
                have.add(Evidence.TRACKING_SIGNATURE)
            if o.get("ship_to") and o.get("ship_to") == c.get("billing_address"):
                have.add(Evidence.SHIPPING_ADDRESS_MATCH)
            if o.get("refunded_at"):
                have.add(Evidence.ALREADY_REFUNDED)
            if o.get("refund_policy_shown"):
                have.add(Evidence.REFUND_POLICY_SHOWN)
            if o.get("access_log"):
                have.add(Evidence.DIGITAL_ACCESS_LOG)
            if o.get("distinct_from"):
                have.add(Evidence.DUPLICATE_CHARGE_DISTINCT)
        if b.thread:
            have.add(Evidence.CUSTOMER_COMMUNICATION)
        # CE3.0: two undisputed charges on the same card, 120-365 days old, two of four identifiers
        # matching across all three, at least one of them IP or device.
        eligible = [p for p in b.priors if CE3_MIN_DAYS <= p.get("age_days", 0) <= CE3_MAX_DAYS]
        if len(eligible) >= 2:
            have.add(Evidence.CE3_PRIOR_TRANSACTIONS)
            base = {"ip": c.get("ip"), "device": c.get("device"), "account": c.get("account_id"), "ship_to": (o or {}).get("ship_to")}
            matched = [k for k, v in base.items() if v and all(p.get(k) == v for p in eligible[:2])]
            if len(matched) >= 2 and ({"ip", "device"} & set(matched)):
                have.add(Evidence.CE3_ELEMENTS_MATCH)
        return have, kind

    # ---------- write: the model turns cited facts into claims; uncited ones are dropped and counted ----------
    def write(self, b: Bundle, reason: str, verdict: Verdict, trace: Trace) -> tuple[dict[str, Any], int]:
        claims = self.model.write(b.facts, reason, verdict.value)
        ids = set(b.record_ids)
        kept = [c for c in claims if c.get("source") in ids]
        dropped = len(claims) - len(kept)
        trace.span("generation", "model.write", claims=len(claims), dropped_uncited=dropped)
        return {"claims": kept, "raw_claims": claims}, dropped

    def _evidence_payload(self, b: Bundle, packet: dict[str, Any], have: set[Evidence]) -> dict[str, Any]:
        o = b.order or {}
        c = b.charge
        ev: dict[str, Any] = {
            "uncategorized_text": "\n".join(f"{cl['text']} [{cl['source']}]" for cl in packet["claims"]),
            "product_description": o.get("items"),
            "shipping_tracking_number": o.get("tracking"),
            "shipping_carrier": o.get("carrier"),
            "shipping_date": o.get("ship_date"),
            "customer_email_address": (c.get("billing_details") or {}).get("email"),
        }
        if Evidence.CE3_PRIOR_TRANSACTIONS in have:
            eligible = [p for p in b.priors if CE3_MIN_DAYS <= p.get("age_days", 0) <= CE3_MAX_DAYS][:2]
            ce3 = {
                # never customer_purchase_ip / product_description here: Stripe pre-fills those and editing breaks eligibility
                "disputed_transaction": {
                    "customer_account_id": c.get("account_id"),
                    "customer_device_fingerprint": c.get("device"),
                    "customer_email_address": (c.get("billing_details") or {}).get("email"),
                    "merchandise_or_services": "merchandise" if o.get("kind", PHYSICAL) == PHYSICAL else "services",
                    "shipping_address": o.get("ship_to_struct"),
                },
                "prior_undisputed_transactions": [
                    {"charge": p["id"], "customer_account_id": p.get("account"), "customer_device_fingerprint": p.get("device"),
                     "customer_email_address": p.get("email"), "customer_purchase_ip": p.get("ip"),
                     "product_description": p.get("items", "prior order"), "shipping_address": p.get("ship_to_struct")}
                    for p in eligible
                ],
            }
            ev["enhanced_evidence"] = {"visa_compelling_evidence_3": _strip(ce3)}
        return _strip(ev)

    # ---------- run ----------
    async def run(self, dispute_id: str, approve: bool | None = None) -> RunResult:
        run_id = uuid.uuid4().hex[:10]
        trace = Trace(run_id, dispute_id)
        gate = Gate(trace, GateState())
        b = await self.gather(dispute_id, trace)
        reason = b.dispute["reason"]
        amount = b.dispute["amount"]
        have, kind = self.assess(b)
        decision = decide(reason, kind, have)
        trace.span("decision", "policy.decide", verdict=decision.verdict.value, missing=[m.value for m in decision.missing], reason=decision.reason,
                   reason_code=reason, fulfilment=kind, have=sorted(e.value for e in have))

        packet, dropped = self.write(b, reason, decision.verdict, trace)
        gate.state.uncited_claims = dropped
        report = detect(trace.spans, {"claims": packet["raw_claims"]}, b.as_dict(), decision.verdict.value, stage="pre")
        trace.span("review", "detector.pre", findings=[f.mode for f in report.findings])

        text = self._slack_text(b, decision, packet, dropped, report)
        if decision.verdict == Verdict.SUBMIT and hasattr(self.slack, "post_approval"):
            post = gate(Effect("slack", "chat.postMessage", self.channel), lambda: self.slack.post_approval(text, dispute_id))
        else:
            post = gate(Effect("slack", "chat.postMessage", self.channel), lambda: self.slack.post(self.channel, text))
        outcome, recovered, ce3_status = "held", 0, None

        if decision.verdict == Verdict.SUBMIT:
            ok = approve if approve is not None else self.slack.await_approval(post["ts"])
            trace.span("interaction", "slack.approval", approved=ok)
            if ok:
                gate.state.approved.add(dispute_id)
                payload = self._evidence_payload(b, packet, have)
                try:
                    staged = gate(Effect("stripe", "disputes.update", dispute_id, {"submit": False, "evidence": payload}),
                                  lambda: self.stripe.update_dispute(dispute_id, payload, submit=False))
                    ce3_status = staged.get("ce3_status") or self._ce3_status(staged)
                    if reason == "fraudulent" and ce3_status and not ce3_status.startswith("qualified"):
                        outcome = "held"
                        trace.span("decision", "ce3.validator", status=ce3_status, action="held: Stripe says not qualified")
                    else:
                        final = gate(Effect("stripe", "disputes.update", dispute_id, {"submit": True, "evidence": payload}),
                                     lambda: self.stripe.update_dispute(dispute_id, payload, submit=True))
                        outcome = final.get("status", "under_review")
                        if outcome == "won":
                            recovered = amount + DISPUTE_FEE_CENTS
                        # customer notice: Photon text is the channel; email only when no phone or no existing thread
                        email = (b.charge.get("billing_details") or {}).get("email")
                        phone = (b.charge.get("billing_details") or {}).get("phone")
                        note = self._customer_note(b)
                        sent = False
                        if phone and self.photon is not None:
                            try:
                                gate(Effect("photon", "messages.send", dispute_id), lambda: self.photon.send(phone, note))
                                sent = True
                            except Blocked:
                                raise
                            except Exception as e:  # shared line refuses a cold thread: record it, fall back
                                trace.span("effect", "photon.messages.send", target=dispute_id, result="ERROR", error=str(e)[:200])
                        if not sent and email:
                            gate(Effect("gmail", "messages.send", dispute_id), lambda: self.gmail.send(email, "About your recent dispute", note))
                except Blocked as e:
                    outcome = f"blocked:{e}"
                except Exception as e:  # the counterparty rejected the evidence: hold, record why, never retry blindly
                    outcome = "held"
                    trace.span("effect", "stripe.disputes.update", target=dispute_id, result="ERROR", error=str(e)[:300])
                    ce3_status = "rejected_by_validator"
        elif decision.verdict == Verdict.CONCEDE:
            outcome = "conceded"

        gate(Effect("sheets", "values.append", dispute_id), lambda: self.sheets.append_outcome({
            "dispute_id": dispute_id, "reason": reason, "verdict": decision.verdict.value, "outcome": outcome,
            "amount": amount / 100, "recovered": recovered / 100, "run_id": run_id, "ce3": ce3_status or "",
        }))
        fee = "returned" if outcome == "won" else "at risk"
        summary = (f"{decision.verdict.value.upper()} -> {outcome} | ${amount/100:.2f} at stake, ${recovered/100:.2f} recovered, "
                   f"${DISPUTE_FEE_CENTS/100:.2f} fee {fee} | {gate.blocked} forbidden effects blocked | run {run_id}")
        gate(Effect("slack", "chat.postMessage", self.channel), lambda: self.slack.post(self.channel, summary))
        trace.span("report", "slack.summary", text=summary)
        report = detect(trace.spans, {"claims": packet["raw_claims"]}, b.as_dict(), decision.verdict.value, stage="post")
        trace.span("review", "detector.post", findings=[f.mode for f in report.findings])
        if report.findings:
            flags = "Review flags: " + "; ".join(f"{f.mode}: {f.detail}" for f in report.findings)
            gate(Effect("slack", "chat.postMessage", self.channel), lambda: self.slack.post(self.channel, flags))
        trace.dump()
        return RunResult(run_id, dispute_id, decision.verdict, decision, outcome, amount, recovered, gate.blocked, report, trace, ce3_status)

    @staticmethod
    def _ce3_status(d: dict[str, Any]) -> str | None:
        try:
            e = d["evidence_details"]["enhanced_eligibility"]["visa_compelling_evidence_3"]
            actions = e.get("required_actions") or []
            return e["status"] + ("" if not actions else ":" + ",".join(actions))
        except (KeyError, TypeError):
            return None

    def _slack_text(self, b: Bundle, d: Decision, packet: dict[str, Any], dropped: int, report: Report) -> str:
        lines = [f"*Dispute {b.dispute['id']}* · {b.dispute['reason']} · ${b.dispute['amount']/100:.2f}",
                 f"*Verdict:* {d.verdict.value.upper()} — {d.reason}"]
        if d.missing:
            lines.append("*Missing:* " + ", ".join(m.value for m in d.missing))
        lines += [f"• {c['text']}  _[{c['source']}]_" for c in packet["claims"]]
        if dropped:
            lines.append(f"_{dropped} uncited claim(s) dropped before filing_")
        if report.findings:
            lines.append("*Review flags:* " + "; ".join(f"{f.mode}: {f.detail}" for f in report.findings))
        if d.verdict == Verdict.SUBMIT:
            lines.append("Reply *approve* or *hold*.")
        return "\n".join(lines)

    @staticmethod
    def _customer_note(b: Bundle) -> str:
        o = b.order or {}
        tracking = f" (tracking {o['tracking']})" if o.get("tracking") else ""
        return (f"Hi, we received a dispute for order {o.get('order_id', '')}. We have sent your bank the order and delivery records{tracking}. "
                "If this was a mistake, reply to this email and we will sort it out.")


def _strip(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            v = _strip(v)
        if isinstance(v, list):
            v = [_strip(x) if isinstance(x, dict) else x for x in v]
        if v not in (None, "", {}, []):
            out[k] = v
    return out
