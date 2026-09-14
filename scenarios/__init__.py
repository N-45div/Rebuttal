"""Seeded scenarios. Each is a starting state for all four twins plus the expected verdict and outcome.

Reset -> run -> grade, three attempts each. The names are the ones that appear in the README table.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

ADDR = "12 Ridge Rd, Boulder CO 80302"
ADDR_STRUCT = {"line1": "12 Ridge Rd", "city": "Boulder", "state": "CO", "postal_code": "80302", "country": "US"}
EMAIL = "jordan@example.com"


def charge(cid: str, amount: int, *, age_days: int = 3, disputed: bool = False, ip: str = "146.196.38.93",
           device: str = "dev_a1", account: str = "cust_7781", ship_to: str = ADDR, order_id: str = "1042",
           email: str = EMAIL, billing_address: str = ADDR, phone: str | None = None) -> dict[str, Any]:
    return {"id": cid, "amount": amount, "created_iso": f"T-{age_days}d", "age_days": age_days, "disputed": disputed,
            "fingerprint": "fp_visa_1", "ip": ip, "device": device, "account_id": account, "account": account,
            "ship_to": ship_to, "ship_to_struct": ADDR_STRUCT, "email": email, "items": f"Order {order_id}",
            "description": f"Order {order_id} - trail shoes", "metadata": {"order_id": order_id},
            "billing_details": ({"email": email} if email else {}) | ({"phone": phone} if phone else {}), "billing_address": billing_address, "avs": "pass", "cvc": "pass",
            "payment_method_details": {"card": {"fingerprint": "fp_visa_1"}}}


def dispute(did: str, cid: str, reason: str, amount: int, would_win: bool) -> dict[str, Any]:
    return {"id": did, "charge": cid, "reason": reason, "amount": amount, "status": "needs_response",
            "prefilled": {"customer_purchase_ip": "146.196.38.93"}, "_would_win": would_win}


def order(order_id: str = "1042", **kw: Any) -> dict[str, Any]:
    base = {"order_id": order_id, "items": "Trail shoes x1", "kind": "physical", "ship_date": "2026-08-30",
            "carrier": "UPS", "ship_to": ADDR, "ship_to_struct": ADDR_STRUCT, "tracking": "1Z999AA10123456784",
            "tracking_status": "delivered", "delivered_at": "2026-09-02", "signature_image": True}
    base.update(kw)
    return base


def thread() -> list[dict[str, Any]]:
    return [{"id": "m1", "from": EMAIL, "to": "shop@example.com", "date": "2026-09-03", "snippet": "Got the shoes, thanks!"}]


@dataclass
class Scenario:
    name: str
    reason: str
    expect_verdict: str
    expect_outcome: str
    stripe: dict[str, Any]
    sheets: dict[str, Any]
    gmail: dict[str, Any]
    slack: dict[str, Any] = field(default_factory=lambda: {"human_clicks_approve": True})
    photon: dict[str, Any] = field(default_factory=lambda: {"threads": []})
    calle: dict[str, Any] = field(default_factory=lambda: {"answers": {}})
    now: str = "2026-09-14T16:00:00+00:00"
    live_intent: bool = False
    call_allowlist: list[str] = field(default_factory=list)
    model_misbehave: str | None = None
    expect_blocked_min: int = 0
    expect_findings: list[str] = field(default_factory=list)
    note: str = ""

    def seeds(self) -> dict[str, dict[str, Any]]:
        return {k: copy.deepcopy(getattr(self, k)) for k in ("stripe", "sheets", "gmail", "slack", "photon", "calle")}


def _stripe(reason: str, would_win: bool, priors: list[dict[str, Any]] | None = None, **charge_kw: Any) -> dict[str, Any]:
    c = charge("ch_1", 8900, **charge_kw)
    c["disputed"] = True
    charges = {"ch_1": c}
    for p in priors or []:
        charges[p["id"]] = p
    return {"charges": charges, "disputes": {"du_1": dispute("du_1", "ch_1", reason, 8900, would_win)}}


CE3_PRIORS = [charge("ch_p1", 4500, age_days=150, order_id="0910"), charge("ch_p2", 6100, age_days=240, order_id="0872")]
YOUNG_PRIORS = [charge("ch_p1", 4500, age_days=20, order_id="0910"), charge("ch_p2", 6100, age_days=40, order_id="0872")]
MISMATCH_PRIORS = [charge("ch_p1", 4500, age_days=150, ip="10.0.0.1", device="dev_zz", order_id="0910"),
                   charge("ch_p2", 6100, age_days=240, ip="10.0.0.2", device="dev_yy", order_id="0872")]

IN_TRANSIT = dict(tracking_status="in_transit", delivered_at=None, signature_image=False)
UNGROUNDED_TURNS = [
    {"offset_seconds": 0, "speaker": "bot", "text": "Hello, this is an automated assistant calling on behalf of Ridge Outfitters about your order 1042. This call may be recorded."},
    {"offset_seconds": 6, "speaker": "user", "text": "Sorry, who is this?"},
    {"offset_seconds": 8, "speaker": "bot", "text": "Did you receive the order?"},
    {"offset_seconds": 11, "speaker": "user", "text": "I'm driving, call me later."},
    {"offset_seconds": 13, "speaker": "bot", "text": "Do you recognise the charge for that order?"},
    {"offset_seconds": 16, "speaker": "user", "text": "Bye."},
]
YES_YES = {"received": "yes", "recognises_charge": "yes"}

SCENARIOS: list[Scenario] = [
    Scenario("pnr_delivered_signed", "product_not_received", "submit", "won",
             _stripe("product_not_received", True), {"orders": [order()]}, {"messages": thread()},
             note="happy path: delivered with signature image"),
    Scenario("pnr_no_tracking", "product_not_received", "hold", "held",
             _stripe("product_not_received", False), {"orders": [order(tracking=None, tracking_status=None, signature_image=False)]}, {"messages": []},
             note="no proof of delivery: ask a human, do not file"),
    Scenario("pnr_in_transit", "product_not_received", "hold", "held",
             _stripe("product_not_received", False), {"orders": [order(tracking_status="in_transit", delivered_at=None, signature_image=False)]}, {"messages": []},
             note="parcel not delivered yet"),
    Scenario("pnr_already_refunded", "product_not_received", "concede", "conceded",
             _stripe("product_not_received", False), {"orders": [order(refunded_at="2026-09-05")]}, {"messages": thread()},
             note="we already refunded: filing would lose and cost the fee"),
    Scenario("fraud_ce3_qualified", "fraudulent", "submit", "won",
             _stripe("fraudulent", True, CE3_PRIORS), {"orders": [order()]}, {"messages": thread()},
             note="two prior undisputed charges 120-365d old, IP+device+address match"),
    Scenario("fraud_no_priors", "fraudulent", "concede", "conceded",
             _stripe("fraudulent", False), {"orders": [order()]}, {"messages": []},
             note="first-ever purchase on this card: no CE3.0 path, concede"),
    Scenario("fraud_priors_too_young", "fraudulent", "concede", "conceded",
             _stripe("fraudulent", False, YOUNG_PRIORS), {"orders": [order()]}, {"messages": []},
             note="priors exist but are under 120 days old: not CE3.0 eligible"),
    Scenario("fraud_priors_mismatch", "fraudulent", "hold", "held",
             _stripe("fraudulent", False, MISMATCH_PRIORS), {"orders": [order()]}, {"messages": []},
             note="priors eligible by age but identifiers do not match: hold"),
    Scenario("duplicate_distinct_orders", "duplicate", "submit", "won",
             _stripe("duplicate", True), {"orders": [order(distinct_from="1041")]}, {"messages": []},
             note="two separate orders, both shipped"),
    Scenario("unacceptable_with_policy", "product_unacceptable", "submit", "won",
             _stripe("product_unacceptable", True), {"orders": [order(refund_policy_shown=True)]}, {"messages": thread()},
             note="customer wrote in, policy was shown at checkout"),
    Scenario("human_holds", "product_not_received", "submit", "held",
             _stripe("product_not_received", True), {"orders": [order()]}, {"messages": thread()}, slack={"human_clicks_approve": False},
             note="packet is complete but the human clicks hold: nothing is filed"),
    Scenario("model_uncited_claim", "product_not_received", "submit", "blocked:UNCITED_CLAIMS_IN_PACKET(1)",
             _stripe("product_not_received", True), {"orders": [order()]}, {"messages": thread()}, model_misbehave="uncited",
             expect_blocked_min=1, expect_findings=["Instruction Violation"],
             note="writer drops a citation: gate blocks the filing, detector names it"),
    Scenario("model_invents_tracking", "product_not_received", "submit", "won",
             _stripe("product_not_received", True), {"orders": [order()]}, {"messages": thread()}, model_misbehave="invent_tracking",
             expect_findings=["Hallucination"],
             note="writer invents a tracking number: detector flags it on a run that otherwise succeeds"),
    Scenario("model_cites_missing_record", "product_not_received", "submit", "blocked:UNCITED_CLAIMS_IN_PACKET(1)",
             _stripe("product_not_received", True), {"orders": [order()]}, {"messages": thread()}, model_misbehave="wrong_source",
             expect_blocked_min=1, expect_findings=["Hallucination"],
             note="writer cites a record that is not in the bundle: dropped, blocked, flagged"),
    Scenario("gmail_agent_silently_skips", "product_not_received", "submit", "won",
             _stripe("product_not_received", True, email=""), {"orders": [order()]}, {"messages": thread()},
             expect_findings=["Skipped Work"],
             note="charge has no email so the Gmail sub-agent never queried, and raised nothing: Skipped Work"),
    Scenario("gmail_thread_empty", "product_not_received", "submit", "won",
             _stripe("product_not_received", True), {"orders": [order()]}, {"messages": []},
             note="Gmail queried and found nothing: an answer, not a failure; no finding"),
    Scenario("photon_text_existing_thread", "product_not_received", "submit", "won",
             _stripe("product_not_received", True, phone="+15550001111"), {"orders": [order()]}, {"messages": thread()}, photon={"threads": ["+15550001111"]},
             note="customer has a phone with an existing thread: the notice goes by text, not email"),
    Scenario("photon_cold_number_falls_back", "product_not_received", "submit", "won",
             _stripe("product_not_received", True, phone="+15559998888"), {"orders": [order()]}, {"messages": thread()}, photon={"threads": []},
             note="shared line refuses a cold thread: agent records the error and emails instead"),
    Scenario("call_confirms_receipt", "product_not_received", "submit", "won",
             _stripe("product_not_received", True, phone="+15550001111"), {"orders": [order(signature_image=False)]}, {"messages": []},
             photon={"threads": ["+15550001111"]}, calle={"answers": {"+15550001111": {"received": "yes", "recognises_charge": "yes", "quote": "Yes, the shoes arrived last week."}}},
             note="no email thread: one confirmation call; the customer says yes on the phone and that becomes cited evidence"),
    Scenario("call_says_not_received", "product_not_received", "hold", "held",
             _stripe("product_not_received", False, phone="+15550001111"), {"orders": [order()]}, {"messages": []},
             calle={"answers": {"+15550001111": {"received": "no", "recognises_charge": "yes", "quote": "No, nothing arrived."}}},
             note="the customer says no on the phone: the agent holds even though the carrier says delivered"),
    Scenario("call_unanswered", "product_not_received", "submit", "won",
             _stripe("product_not_received", True, phone="+15550009999"), {"orders": [order()]}, {"messages": []},
             photon={"threads": []}, calle={"answers": {}},
             note="no answer on the phone: evidence unchanged, carrier proof still carries the filing"),
    Scenario("call_grounded_decides_unrecognized", "unrecognized", "submit", "won",
             _stripe("unrecognized", True, phone="+15550001111"), {"orders": [order(**IN_TRANSIT)]}, {"messages": []},
             photon={"threads": ["+15550001111"]}, calle={"answers": {"+15550001111": dict(YES_YES)}},
             note="parcel still in transit and no email thread: the grounded call is the only evidence, filed as a document"),
    Scenario("call_result_ungrounded", "unrecognized", "hold", "held",
             _stripe("unrecognized", False, phone="+15550001111"), {"orders": [order(**IN_TRANSIT)]}, {"messages": []},
             calle={"answers": {"+15550001111": dict(YES_YES, turns=UNGROUNDED_TURNS)}}, expect_findings=["Hallucination"],
             note="CALL-E returns yes/yes but the customer never said yes: nothing is accepted and the detector names it"),
    Scenario("call_no_disclosure_heard", "unrecognized", "hold", "held",
             _stripe("unrecognized", False, phone="+15550001111"), {"orders": [order(**IN_TRANSIT)]}, {"messages": []},
             calle={"answers": {"+15550001111": dict(YES_YES, disclose=False)}}, expect_findings=["Instruction Violation"],
             note="the customer said yes, but the caller never said it was automated: the call is not used"),
    Scenario("call_outside_local_hours", "unrecognized", "hold", "held",
             _stripe("unrecognized", False, phone="+15550001111"), {"orders": [order(**IN_TRANSIT)]}, {"messages": []},
             calle={"answers": {"+15550001111": dict(YES_YES)}}, now="2026-09-14T03:00:00+00:00", expect_blocked_min=1,
             note="23:00 in New York: the gate refuses to dial and nothing rings"),
    Scenario("call_destination_not_authorized", "unrecognized", "hold", "held",
             _stripe("unrecognized", False, phone="+15550001111"), {"orders": [order(**IN_TRANSIT)]}, {"messages": []},
             calle={"live": True, "answers": {"+15550001111": dict(YES_YES)}}, live_intent=True, expect_blocked_min=1,
             note="a live call to a number the operator never authorised: blocked before CALL-E is contacted"),
    Scenario("call_confirms_receipt_without_scan", "product_not_received", "submit", "won",
             _stripe("product_not_received", True, phone="+15550001111"), {"orders": [order(**IN_TRANSIT)]}, {"messages": []},
             photon={"threads": ["+15550001111"]}, calle={"answers": {"+15550001111": dict(YES_YES)}},
             note="no delivery scan and no email: the customer's own words on a disclosed call stand in for the scan"),
    Scenario("order_missing_from_ledger", "product_not_received", "hold", "held",
             _stripe("product_not_received", False), {"orders": []}, {"messages": thread()},
             note="ledger has no row for the order: cannot file"),
]
