from rebuttal.replay import _decision


def test_a_no_stops_the_filing_even_next_to_a_grounded_yes():
    assert _decision(True, {"received": "yes", "recognises_charge": "no"}, True) == "stops the filing"


def test_a_usable_call_with_a_grounded_yes_is_used():
    assert _decision(True, {"received": "yes", "recognises_charge": "yes"}, False) == "used as evidence"


def test_an_unusable_call_is_not_used():
    assert _decision(False, {"received": "yes", "recognises_charge": "yes"}, False) == "not used"
