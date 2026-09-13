import pytest
from rebuttal.gate import Blocked, Effect, Gate, GateState, Trace


def mk(state=None):
    return Gate(Trace("t", "du_1"), state or GateState())


def submit(target="du_1", **evidence):
    return Effect("stripe", "disputes.update", target, {"submit": True, "evidence": evidence})


def test_submit_without_approval_is_blocked():
    g = mk()
    with pytest.raises(Blocked, match="SUBMIT_WITHOUT_HUMAN_APPROVAL"):
        g(submit(), lambda: "sent")
    assert g.blocked == 1 and g.trace.spans[-1]["result"] == "BLOCKED"


def test_approved_submit_passes_once_then_blocks_duplicate():
    g = mk(GateState(approved={"du_1"}))
    assert g(submit(), lambda: "sent") == "sent"
    with pytest.raises(Blocked, match="DUPLICATE_FILING_SAME_DISPUTE"):
        g(submit(), lambda: "sent")


def test_uncited_claims_block():
    g = mk(GateState(approved={"du_1"}, uncited_claims=2))
    with pytest.raises(Blocked, match="UNCITED_CLAIMS"):
        g(submit(), lambda: None)


def test_editing_ce3_prefilled_ip_is_blocked():
    g = mk(GateState(approved={"du_1"}))
    ev = {"enhanced_evidence": {"visa_compelling_evidence_3": {"disputed_transaction": {"customer_purchase_ip": "1.2.3.4"}}}}
    with pytest.raises(Blocked, match="EDITED_CE3_PREFILLED_FIELD"):
        g(submit(**ev), lambda: None)


def test_second_email_blocked():
    g = mk()
    e = Effect("gmail", "messages.send", "du_1")
    g(e, lambda: None)
    with pytest.raises(Blocked, match="SECOND_EMAIL_TO_CUSTOMER"):
        g(e, lambda: None)


def test_refund_blocked():
    with pytest.raises(Blocked, match="REFUND_OUTSIDE_SCOPE"):
        mk()(Effect("stripe", "refunds.create", "ch_1"), lambda: None)
