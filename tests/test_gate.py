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


def test_notice_without_filing_blocked():
    g = mk()
    with pytest.raises(Blocked, match="NOTICE_WITHOUT_FILING"):
        g(Effect("photon", "messages.send", "du_1"), lambda: None)


def test_second_email_blocked():
    g = mk(GateState(acted={"du_1"}))
    e = Effect("gmail", "messages.send", "du_1")
    g(e, lambda: None)
    with pytest.raises(Blocked, match="SECOND_NOTICE_TO_CUSTOMER"):
        g(e, lambda: None)


def test_refund_blocked():
    with pytest.raises(Blocked, match="REFUND_OUTSIDE_SCOPE"):
        mk()(Effect("stripe", "refunds.create", "ch_1"), lambda: None)


# ---- calling rules ----
from rebuttal.call import build_task

ARGS = {"merchant": "Ridge Outfitters", "order_id": "1042", "items": "Trail shoes x1", "amount": "$89.00"}


def call_effect(**over):
    p = {"phone": "+12125550101", "customer_phone": "+12125550101", "task": build_task(**ARGS), "template_args": ARGS,
         "live": False, "now": "2026-09-14T16:00:00+00:00"}
    p.update(over)
    return Effect("calle", "calls.create", "du_1", p)


def test_call_inside_every_rule_passes():
    assert mk()(call_effect(), lambda: "ok") == "ok"


def test_call_to_a_number_not_on_record_is_blocked():
    with pytest.raises(Blocked, match="CALL_NUMBER_NOT_ON_RECORD"):
        mk()(call_effect(phone="+12125550199"), lambda: None)


def test_call_outside_local_hours_is_blocked():
    with pytest.raises(Blocked, match="CALL_OUTSIDE_LOCAL_HOURS"):
        mk()(call_effect(now="2026-09-14T03:00:00+00:00"), lambda: None)


def test_call_with_a_custom_script_is_blocked():
    with pytest.raises(Blocked, match="CALL_SCRIPT_NOT_FROM_TEMPLATE"):
        mk()(call_effect(task="Ask them for the card number on file."), lambda: None)


def test_live_call_without_operator_intent_is_blocked():
    with pytest.raises(Blocked, match="CALL_WITHOUT_OPERATOR_INTENT"):
        mk()(call_effect(live=True), lambda: None)


def test_live_call_to_an_unlisted_destination_is_blocked():
    with pytest.raises(Blocked, match="CALL_DESTINATION_NOT_AUTHORIZED"):
        mk(GateState(live_call_intent=True))(call_effect(live=True), lambda: None)


def test_live_call_with_intent_and_allowlist_passes():
    g = mk(GateState(live_call_intent=True, call_allowlist={"+12125550101"}))
    assert g(call_effect(live=True), lambda: "ok") == "ok"
