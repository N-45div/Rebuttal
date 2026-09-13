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
