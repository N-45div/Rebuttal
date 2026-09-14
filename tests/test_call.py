import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rebuttal import call
from rebuttal.twins.calle import CalleTwin

REAL = json.loads((Path(__file__).parent / "fixtures" / "calle_call_confirmed.json").read_text(encoding="utf-8"))
MERCHANT = "Ridge Outfitters"
PHONE = "+12125550101"
YES = {"received": "yes", "recognises_charge": "yes", "purchaser": "cardholder", "declined_to_talk": "no"}


def turns(*pairs):
    return [{"offset_seconds": i * 3, "speaker": sp, "text": tx} for i, (sp, tx) in enumerate(pairs)]


def record(ts, result, status="completed", confidence=0.93):
    return call.CallRecord(call_id="call_t", status=status, task_completed=status == "completed", confidence=confidence,
                           result=result, summary="", evidence=[], turns=ts)


OPEN = ("bot", call.disclosure(MERCHANT, "1042"))
ASK_RECEIVED = ("bot", "Did you receive the order?")
ASK_CHARGE = ("bot", "Do you recognise the charge for that order?")


# ---- the real call CALL-E placed on the first live run

def test_real_call_answers_are_grounded():
    g = call.ground(call.record_from(REAL["call"], REAL["events"]["data"]), MERCHANT)
    assert g.check("received_grounded").passed and g.check("received_grounded").quote == "HI received order."
    assert g.check("recognises_charge_grounded").passed


def test_real_call_is_not_usable_because_it_never_said_it_was_automated():
    g = call.ground(call.record_from(REAL["call"]), MERCHANT)
    assert not g.check("disclosure_spoken").passed
    assert not g.usable and g.accepted["received"] == "unknown"


def test_real_fixture_has_no_unmasked_phone_number():
    assert "+919599125425" not in json.dumps(REAL)


# ---- grounding

def test_disclosed_and_grounded_call_is_usable():
    g = call.ground(record(turns(OPEN, ("user", "Okay."), ASK_RECEIVED, ("user", "Yes, I got them."),
                                 ASK_CHARGE, ("user", "Yes, that's mine.")), YES), MERCHANT)
    assert g.usable and g.accepted["received"] == "yes" and g.accepted["recognises_charge"] == "yes"


def test_structured_yes_without_the_customer_saying_yes_is_not_accepted():
    g = call.ground(record(turns(OPEN, ASK_RECEIVED, ("user", "Who is this?"), ASK_CHARGE, ("user", "Call me later.")), YES), MERCHANT)
    assert g.accepted == {"received": "unknown", "recognises_charge": "unknown", "purchaser": "cardholder"}
    assert not g.check("received_grounded").passed


def test_a_no_stops_the_filing_even_when_it_is_not_grounded():
    g = call.ground(record(turns(OPEN, ASK_RECEIVED, ("user", "Hmm."), ASK_CHARGE, ("user", "Hmm.")),
                           dict(YES, received="no")), MERCHANT)
    assert g.denied and g.accepted["received"] == "unknown"


def test_low_confidence_call_is_not_usable():
    g = call.ground(record(turns(OPEN, ASK_RECEIVED, ("user", "Yes."), ASK_CHARGE, ("user", "Yes.")), YES, confidence=0.55), MERCHANT)
    assert not g.usable and not g.check("confidence").passed


def test_failed_call_is_not_usable():
    assert not call.ground(record([], {}, status="failed", confidence=None), MERCHANT).usable


def test_caller_asking_for_card_data_makes_the_call_unusable():
    g = call.ground(record(turns(OPEN, ("bot", "Can you read me the card number?"), ASK_RECEIVED, ("user", "Yes.")), YES), MERCHANT)
    assert not g.check("no_payment_data_requested").passed and not g.usable


def test_polite_no_problem_is_not_a_no():
    assert call.polarity("Yes, no problem.") == "yes"
    assert call.polarity("No, it is not mine.") == "no"
    assert call.polarity("Sorry, who is this?") is None


# ---- script, destination rules

def test_script_discloses_and_never_asks_for_payment_data():
    task = call.build_task(merchant=MERCHANT, order_id="1042", items="Trail shoes x1", amount="$89.00")
    assert call.disclosure(MERCHANT, "1042") in task and "automated assistant" in task
    assert "Never ask for card numbers" in task and "+1" not in task


@pytest.mark.parametrize("phone,now,ok", [
    ("+12125550101", "2026-09-14T16:00:00+00:00", True),    # noon in New York, 09:00 in Los Angeles
    ("+12125550101", "2026-09-14T03:00:00+00:00", False),   # 23:00 in New York
    ("+12125550101", "2026-09-14T13:30:00+00:00", False),   # 06:30 in Los Angeles
    ("+919876500000", "2026-09-14T06:00:00+00:00", True),   # 11:30 in India
    ("+919876500000", "2026-09-14T16:00:00+00:00", False),  # 21:30 in India
    ("+8613800000000", "2026-09-14T06:00:00+00:00", False),  # no rule for this country
])
def test_local_calling_hours(phone, now, ok):
    assert call.local_hours_ok(phone, datetime.fromisoformat(now))[0] is ok


def test_mask_keeps_country_code_and_last_four():
    assert call.mask("+919599125425") == "+91******5425"


def test_allowlist():
    assert call.authorized(PHONE, "+12125550101, +12125550102")
    assert not call.authorized(PHONE, "") and not call.authorized(PHONE, None)


# ---- the CALL-E API contract, against the twin

def test_place_rejects_a_non_e164_destination():
    with pytest.raises(ValueError):
        call.place(CalleTwin({}), dispute_id="du_1", phone="2125550101", merchant=MERCHANT, order_id="1042", items="x", amount="$1")


def test_place_is_idempotent_per_dispute():
    twin = CalleTwin({"answers": {PHONE: YES}})
    a = call.place(twin, dispute_id="du_1", phone=PHONE, merchant=MERCHANT, order_id="1042", items="x", amount="$1")
    b = call.place(twin, dispute_id="du_1", phone=PHONE, merchant=MERCHANT, order_id="1042", items="x", amount="$1")
    assert a["id"] == b["id"] and sum(e["change"] == "call.placed" for e in twin.effects) == 1


def test_follow_streams_events_and_turns_then_grounds():
    twin = CalleTwin({"answers": {PHONE: YES}})
    created = call.place(twin, dispute_id="du_1", phone=PHONE, merchant=MERCHANT, order_id="1042", items="x", amount="$1")
    events, said = [], []
    rec = call.follow(twin, created["id"], on_event=events.append, on_turn=said.append, sleep=lambda s: None)
    assert rec.status == "completed" and len(events) == 5 and len(said) == len(rec.turns) == 7
    g = call.ground(rec, MERCHANT)
    assert g.usable and g.accepted["received"] == "yes"


def test_evidence_document_is_a_pdf_with_masked_number():
    twin = CalleTwin({"answers": {PHONE: YES}})
    created = call.place(twin, dispute_id="du_1", phone=PHONE, merchant=MERCHANT, order_id="1042", items="x", amount="$1")
    rec = call.follow(twin, created["id"], sleep=lambda s: None)
    pdf = call.evidence_pdf(rec, call.ground(rec, MERCHANT), merchant=MERCHANT, order_id="1042", dispute_id="du_1", phone=PHONE)
    assert pdf[:4] == b"%PDF" and len(pdf) > 1000
