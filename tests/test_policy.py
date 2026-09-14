from rebuttal.policy import Evidence as E, Verdict, decide, PHYSICAL, DIGITAL


def test_pnr_with_delivery_and_signature_submits():
    d = decide("product_not_received", PHYSICAL, {E.ORDER_RECORD, E.TRACKING_DELIVERED, E.TRACKING_SIGNATURE})
    assert d.verdict == Verdict.SUBMIT


def test_pnr_without_tracking_holds():
    d = decide("product_not_received", PHYSICAL, {E.ORDER_RECORD})
    assert d.verdict == Verdict.HOLD
    assert E.TRACKING_DELIVERED in d.missing


def test_already_refunded_concedes():
    d = decide("product_not_received", PHYSICAL, {E.ORDER_RECORD, E.TRACKING_DELIVERED, E.ALREADY_REFUNDED})
    assert d.verdict == Verdict.CONCEDE


def test_fraud_without_ce3_concedes():
    d = decide("fraudulent", PHYSICAL, {E.ORDER_RECORD, E.TRACKING_DELIVERED})
    assert d.verdict == Verdict.CONCEDE


def test_fraud_with_ce3_submits():
    d = decide("fraudulent", PHYSICAL, {E.ORDER_RECORD, E.CE3_PRIOR_TRANSACTIONS, E.CE3_ELEMENTS_MATCH, E.SHIPPING_ADDRESS_MATCH})
    assert d.verdict == Verdict.SUBMIT


def test_unknown_reason_holds():
    assert decide("bank_cannot_process", DIGITAL, set()).verdict == Verdict.HOLD


def test_confirmed_receipt_on_a_call_stands_in_for_a_delivery_scan():
    d = decide("product_not_received", PHYSICAL, {E.ORDER_RECORD, E.SHIPPING_ADDRESS_MATCH, E.CUSTOMER_CONFIRMED_RECEIPT})
    assert d.verdict == Verdict.SUBMIT


def test_without_the_call_a_missing_scan_holds():
    d = decide("product_not_received", PHYSICAL, {E.ORDER_RECORD, E.SHIPPING_ADDRESS_MATCH})
    assert d.verdict == Verdict.HOLD and E.TRACKING_DELIVERED in d.missing


def test_confirmed_receipt_does_not_rescue_a_fraud_dispute_without_ce3():
    d = decide("fraudulent", PHYSICAL, {E.ORDER_RECORD, E.CUSTOMER_CONFIRMED_RECEIPT, E.TRACKING_DELIVERED})
    assert d.verdict == Verdict.CONCEDE
