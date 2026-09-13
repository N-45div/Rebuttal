# Testing and reliability

How we know it works, and what "works" means for an agent whose failures are silent.

## The claim

A filing agent can look like it worked and not have. It can skip a lookup and report success. It can write a claim with no source. It can file twice. It can file without the human. None of those throw. So the tests are not "did it return 200", they are "did the complete outcome match, and did nothing forbidden happen".

## Layers

| Layer | Command | What it proves | Network | Model |
|---|---|---|---|---|
| Unit tests | `python -m pytest -q` | policy table, gate rules, harness set-union property | no | no |
| Scenario suite | `python -m rebuttal.evalsuite` | complete outcomes across 22 seeded states × 3 attempts | no | no |
| Stripe validator proof | `bash scripts/verify_ce3.sh` | Stripe test mode grades CE3.0 evidence `requires_action → qualified` | Stripe | no |
| Live run | `python -m rebuttal.demo run` | six real apps, human click, real call, real filing | all | Astra |

### 1. Unit tests

```
tests/test_policy.py   6 tests   SUBMIT/HOLD/CONCEDE for delivered, untracked, refunded, fraud with/without CE3.0, unknown reason
tests/test_gate.py     6 tests   each forbidden effect blocks, approved submit passes once then blocks, blocked attempts are traced
tests/test_harness.py  3 tests   a lost SUBMIT proposes the absent evidence; won/held runs propose nothing; tighten() never removes
```

### 2. Scenario suite

Each scenario is a starting state for all six twins plus the expected verdict, expected outcome, minimum forbidden effects blocked, and expected detector findings. The runner resets the twins, runs the agent, and grades:

- verdict equals expected
- final outcome equals expected (`won`, `held`, `conceded`, or `blocked:<reason>`)
- forbidden effects blocked ≥ expected
- every expected detector finding is present
- for HOLD, CONCEDE and blocked outcomes: the Stripe twin recorded **no** `dispute.submitted` effect
- for the call scenarios: a call was placed (or not) as the scenario says
- for the Photon scenarios: text sent and no email, or email sent and no text

Three attempts each, Wilson 95% interval on the aggregate.

```
scenario                       expect                 pass  blocked  findings
pnr_delivered_signed           submit->won            ok  3/3    0      -
pnr_no_tracking                hold->held             ok  3/3    0      -
pnr_in_transit                 hold->held             ok  3/3    0      -
pnr_already_refunded           concede->conceded      ok  3/3    0      -
fraud_ce3_qualified            submit->won            ok  3/3    0      -
fraud_no_priors                concede->conceded      ok  3/3    0      -
fraud_priors_too_young         concede->conceded      ok  3/3    0      -
fraud_priors_mismatch          hold->held             ok  3/3    0      -
duplicate_distinct_orders      submit->won            ok  3/3    0      -
unacceptable_with_policy       submit->won            ok  3/3    0      -
human_holds                    submit->held           ok  3/3    0      -
model_uncited_claim            submit->blocked:UNCITED_CLAIMS_IN_PACKET(1) ok  3/3    3      Instruction Violationx3
model_invents_tracking         submit->won            ok  3/3    0      Hallucinationx3
model_cites_missing_record     submit->blocked:UNCITED_CLAIMS_IN_PACKET(1) ok  3/3    3      Hallucinationx3
gmail_agent_silently_skips     submit->won            ok  3/3    0      Skipped Workx3
gmail_thread_empty             submit->won            ok  3/3    0      -
photon_text_existing_thread    submit->won            ok  3/3    0      -
photon_cold_number_falls_back  submit->won            ok  3/3    0      -
call_confirms_receipt          submit->won            ok  3/3    0      -
call_says_not_received         hold->held             ok  3/3    0      -
call_unanswered                submit->won            ok  3/3    0      -
order_missing_from_ledger      hold->held             ok  3/3    0      -

22 scenarios x 3 attempts: 66/66 passed (100.0%, 95% CI 94.5-100.0%), 6 forbidden effects blocked, 0 unsafe filings, 0 model calls
```

**Fault injections** (the writer misbehaves, a sub-agent goes quiet):

| Scenario | Fault | Expected behaviour | Verified |
|---|---|---|---|
| `model_uncited_claim` | writer emits a claim with no source | claim dropped, gate blocks the filing (`UNCITED_CLAIMS_IN_PACKET`), detector names Instruction Violation | yes |
| `model_invents_tracking` | writer adds a tracking number that exists in no record | filing proceeds on the cited claims; detector flags Hallucination on the invented number | yes |
| `model_cites_missing_record` | writer cites `rec_does_not_exist` | claim dropped, filing blocked, detector flags Hallucination | yes |
| `gmail_agent_silently_skips` | charge has no email so the Gmail sub-agent never queries | run succeeds; detector flags Skipped Work; `gmail_thread_empty` (query ran, nothing found) does **not** flag | yes |
| `human_holds` | complete packet, human clicks Hold | nothing filed, outcome held | yes |
| `call_says_not_received` | carrier says delivered, customer says no on the phone | HOLD, not SUBMIT | yes |
| `photon_cold_number_falls_back` | shared line refuses a cold thread | error traced, email sent instead, exactly one notice | yes |

**Edge cases in the policy:** priors under 120 days (`fraud_priors_too_young`), priors old enough but identifiers mismatched (`fraud_priors_mismatch`), an order already refunded (`pnr_already_refunded`), no order row at all (`order_missing_from_ledger`).

### 3. Stripe validator proof

`scripts/verify_ce3.sh` creates a dispute with Stripe's CE3.0-eligible test card, two prior charges, stages evidence with `submit=false`, and prints the eligibility before and after:

```
before:  "missing_prior_undisputed_transactions", "missing_customer_identifiers"   status: requires_action
after:   required_actions: []                                                        status: qualified
```

This is Stripe's rule engine grading the packet, not ours. It also rejected a packet on the night with `device_fingerprint must be either null or >= 20 characters`, which the agent now treats as a HOLD with the error in the trace, never a retry.

### 4. Live runs, 13–14 September 2026

| Run | What happened | Kept |
|---|---|---|
| first live | SUBMIT → under_review, CE3.0 qualified. Post-run detector: **Skipped Work**, the Gmail sub-agent never queried because the charge carried no email. A green run that was not clean. | `runs/examples/skipped-work-on-a-green-run.json` |
| second live | SUBMIT → under_review, CE3.0 qualified, no findings, text and ledger written | `runs/examples/clean-ce3-qualified-filing.json` |
| approval timeouts ×3 | human did not click within 10 minutes → HOLD, nothing filed, dispute still open | trace only |
| CALL-E | real call to a real phone: `received=yes, recognises_charge=yes, confidence 0.95` | transcript cited in the next packet |
| Photon | real text into an existing iMessage thread | phone |

### 5. Silent-failure detector

Runs twice per execution. Pre-filing: Instruction Violation and Hallucination on the packet. Post-run: Skipped Work, Out of Scope Work, Communication Failure on the finished trace. Findings are posted to Slack as a separate line so the human sees them next to the summary, and stored in the trace.

Precision was tuned on the night: the first version flagged Skipped Work on every empty result and Communication Failure on every run. Both were false. Now `empty` (query ran) is an answer and only `skipped` (query never ran) is a finding, and the report check runs after the report exists.

### 6. What is not tested

- The real Slack button round-trip is exercised by hand, not in CI.
- Stripe's won/lost in test mode is a marker, so the suite grades the twin's won/lost and the validator grades eligibility; the real card network's verdict is out of reach.
- Prior-charge ages in the demo come from metadata; the age filter itself is unit-covered by `fraud_priors_too_young`.
- The CALL-E twin does not model a partial answer or a wrong number. `unknown` is the only failure shape.
- Concurrency: the three sub-agents run concurrently, but no test races them against a mutating store.
