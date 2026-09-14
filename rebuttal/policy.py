"""Verdict policy: dispute reason code + available evidence -> SUBMIT / HOLD / CONCEDE.

Deterministic. The model gathers and writes; this table decides.
Sources: Stripe dispute reason codes and per-reason evidence checklists,
Visa Compelling Evidence 3.0 (CE3.0) qualification rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    SUBMIT = "submit"
    HOLD = "hold"       # missing evidence, ask a human
    CONCEDE = "concede"  # filing would lose; save the analyst's time


class Evidence(str, Enum):
    ORDER_RECORD = "order_record"
    TRACKING_DELIVERED = "tracking_delivered"        # carrier scan says delivered
    TRACKING_SIGNATURE = "tracking_signature"        # signature image, outranks a name string
    SHIPPING_ADDRESS_MATCH = "shipping_address_match"  # ship-to equals billing/AVS
    CUSTOMER_COMMUNICATION = "customer_communication"  # email thread with the customer
    REFUND_POLICY_SHOWN = "refund_policy_shown"
    ALREADY_REFUNDED = "already_refunded"
    DUPLICATE_CHARGE_DISTINCT = "duplicate_charge_distinct"  # proof the two charges were separate orders
    DIGITAL_ACCESS_LOG = "digital_access_log"
    CE3_PRIOR_TRANSACTIONS = "ce3_prior_transactions"  # two undisputed charges, same card, 120-365 days old
    CE3_ELEMENTS_MATCH = "ce3_elements_match"
    CUSTOMER_CONFIRMED_RECEIPT = "customer_confirmed_receipt"  # the customer said so on a disclosed, grounded call          # two of four elements match, one being IP or device


# Physical goods need proof of delivery; digital goods need proof of access.
PHYSICAL = "physical"
DIGITAL = "digital"


@dataclass
class Requirement:
    must: set[Evidence] = field(default_factory=set)   # all required to SUBMIT
    any_of: set[Evidence] = field(default_factory=set)  # at least one required to SUBMIT
    concede_if: set[Evidence] = field(default_factory=set)  # presence of any of these means CONCEDE


# Keyed by (stripe dispute reason, fulfilment kind).
POLICY: dict[tuple[str, str], Requirement] = {
    ("product_not_received", PHYSICAL): Requirement(
        must={Evidence.ORDER_RECORD, Evidence.TRACKING_DELIVERED},
        any_of={Evidence.TRACKING_SIGNATURE, Evidence.SHIPPING_ADDRESS_MATCH},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
    ("product_not_received", DIGITAL): Requirement(
        must={Evidence.ORDER_RECORD, Evidence.DIGITAL_ACCESS_LOG},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
    # Fraud on Visa: CE3.0 is the only path that removes the fraud record.
    ("fraudulent", PHYSICAL): Requirement(
        must={Evidence.ORDER_RECORD, Evidence.CE3_PRIOR_TRANSACTIONS, Evidence.CE3_ELEMENTS_MATCH},
        any_of={Evidence.TRACKING_DELIVERED, Evidence.SHIPPING_ADDRESS_MATCH},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
    ("fraudulent", DIGITAL): Requirement(
        must={Evidence.ORDER_RECORD, Evidence.CE3_PRIOR_TRANSACTIONS, Evidence.CE3_ELEMENTS_MATCH},
        any_of={Evidence.DIGITAL_ACCESS_LOG},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
    ("duplicate", PHYSICAL): Requirement(
        must={Evidence.ORDER_RECORD, Evidence.DUPLICATE_CHARGE_DISTINCT},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
    ("duplicate", DIGITAL): Requirement(
        must={Evidence.ORDER_RECORD, Evidence.DUPLICATE_CHARGE_DISTINCT},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
    ("product_unacceptable", PHYSICAL): Requirement(
        must={Evidence.ORDER_RECORD, Evidence.CUSTOMER_COMMUNICATION},
        any_of={Evidence.REFUND_POLICY_SHOWN, Evidence.TRACKING_DELIVERED},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
    ("credit_not_processed", PHYSICAL): Requirement(
        must={Evidence.ORDER_RECORD, Evidence.REFUND_POLICY_SHOWN, Evidence.CUSTOMER_COMMUNICATION},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
    ("subscription_canceled", DIGITAL): Requirement(
        must={Evidence.ORDER_RECORD, Evidence.DIGITAL_ACCESS_LOG, Evidence.REFUND_POLICY_SHOWN},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
    ("unrecognized", PHYSICAL): Requirement(
        must={Evidence.ORDER_RECORD},
        any_of={Evidence.TRACKING_DELIVERED, Evidence.CUSTOMER_COMMUNICATION},
        concede_if={Evidence.ALREADY_REFUNDED},
    ),
}


@dataclass
class Decision:
    verdict: Verdict
    missing: list[Evidence]
    reason: str


def decide(reason_code: str, kind: str, have: set[Evidence]) -> Decision:
    """Pure function. No I/O, no model. Unit-tested against the scenario suite."""
    req = POLICY.get((reason_code, kind))
    if req is None:
        return Decision(Verdict.HOLD, [], f"no policy for {reason_code}/{kind}; human decides")

    # A disclosed call in which the customer's own words confirm receipt stands in for a delivery scan.
    if Evidence.CUSTOMER_CONFIRMED_RECEIPT in have and reason_code in ("product_not_received", "unrecognized"):
        have = set(have) | {Evidence.TRACKING_DELIVERED}

    hit = req.concede_if & have
    if hit:
        return Decision(Verdict.CONCEDE, [], f"conceding: {sorted(e.value for e in hit)} present")

    missing = sorted(req.must - have, key=lambda e: e.value)
    any_ok = not req.any_of or bool(req.any_of & have)

    if not missing and any_ok:
        return Decision(Verdict.SUBMIT, [], "all required evidence present and cited")

    if not any_ok:
        missing = missing + sorted(req.any_of, key=lambda e: e.value)

    # Fraud with no CE3 path is a known loser: don't burn the one-shot filing.
    if reason_code == "fraudulent" and Evidence.CE3_PRIOR_TRANSACTIONS in missing:
        return Decision(Verdict.CONCEDE, missing, "fraud dispute without CE3.0 prior transactions; filing would lose")

    return Decision(Verdict.HOLD, missing, "evidence incomplete; escalating to Slack")
