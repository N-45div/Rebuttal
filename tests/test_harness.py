from rebuttal.harness import Proposal, propose, tighten
from rebuttal.policy import Evidence as E


def test_lost_submit_proposes_missing_evidence():
    rows = [{"run_id": "r1", "reason": "product_not_received", "kind": "physical", "verdict": "submit", "outcome": "lost",
             "have": [E.ORDER_RECORD.value, E.TRACKING_DELIVERED.value]}]
    p = propose(rows)
    assert p and E.TRACKING_SIGNATURE.value in p[0].add


def test_won_or_held_runs_propose_nothing():
    rows = [{"reason": "fraudulent", "verdict": "submit", "outcome": "won", "have": []},
            {"reason": "fraudulent", "verdict": "hold", "outcome": "held", "have": []}]
    assert propose(rows) == []


def test_tighten_never_removes():
    before = {"product_not_received/physical": ["tracking_signature"]}
    after = tighten([Proposal("product_not_received", "physical", ["customer_communication"], "r2")], before)
    assert set(after["product_not_received/physical"]) >= set(before["product_not_received/physical"])
    assert tighten([], before) == before
