# Rebuttal

**Stripe auto-submits whatever evidence it already holds. Rebuttal, a GPT-6 Astra agent, goes and finds the evidence Stripe cannot see, across the order ledger, the customer's email thread and, when the thread is silent, a phone call to the customer, qualifies the dispute under Visa Compelling Evidence 3.0, files it with a human click in Slack, texts the customer, and refuses to file when the packet would lose.**

Every chargeback is a one-shot, irreversible filing against a deadline. A finance-ops person spends 30 to 40 minutes assembling a packet from five systems, and most merchants give up because the order was $60. Rebuttal does that job in about 35 seconds, with a human click in Slack before anything is filed, and it shows its work: every claim carries a citation to a source record, every write passes a gate, and every run leaves a trace.

**Demo video (2 min):** _link goes here_

Built from scratch on 13 September 2026 for the Multi-App AI Agent Hackathon.

## What it does

```
Stripe dispute webhook
   │
   ├── gather: three sub-agents, dispatched concurrently
   │     ├── Stripe   → the disputed charge + prior undisputed charges on the same card/customer
   │     ├── Sheets   → the order row: items, ship date, carrier, tracking, signature, refund
   │     └── Gmail    → the customer's email thread
   │
   ├── CALL-E  → if the thread is silent on a delivery dispute: ONE call to the customer,
   │             "did you receive order 1042?" → structured yes/no becomes cited evidence
   ├── assess  → deterministic evidence checks (delivered? signed? refunded? CE3.0 priors? identifiers match?)
   ├── decide  → policy table: reason code × evidence → SUBMIT / HOLD / CONCEDE
   ├── write   → GPT-6 Astra turns cited facts into claims; any claim without a citation is dropped and counted
   ├── review  → silent-failure detector on the trace (see Reliability)
   │
   ├── Slack   → packet + verdict + citations; Approve & file / Hold buttons (Socket Mode)
   ├── Stripe  → stage evidence (submit=false) → read Stripe's CE3.0 validator → submit only if qualified
   ├── Photon  → one text to the customer (iMessage/RCS); email only if no phone or no existing thread
   ├── Sheets  → outcome row: amount, recovered, fee, CE3.0 status, run id
   └── Slack   → "SUBMIT → won | $89.00 at stake, $104.00 recovered, $15.00 fee returned | 0 forbidden effects blocked"
```

**Three verdicts.** SUBMIT when the reason-code checklist is complete. HOLD when something is missing, with the missing items named in Slack. CONCEDE when filing would lose anyway (already refunded, or a fraud claim with no CE3.0 path), because losing also costs the $15 fee and hurts the dispute ratio.

**Why CE 3.0 is the point.** For a "fraudulent" dispute on Visa, the only way to win *and remove the fraud record* is Compelling Evidence 3.0: two prior undisputed transactions on the same card, 120 to 365 days old, with at least two of four identifiers (IP, device fingerprint, account id, shipping address) matching across all three, one of them IP or device. That evidence is scattered across the payment processor, the store's checkout and the shipping record by construction. Stripe's built-in Smart Disputes cannot assemble it. Rebuttal can, and Stripe grades the result: in test mode the dispute's `enhanced_eligibility.visa_compelling_evidence_3.status` moves from `requires_action` to `qualified` only when the submitted identifiers actually match. That is a real rule engine acting as ground truth, not our own scorer marking its own homework.

## External apps

| App | Role | How |
|---|---|---|
| **Stripe** | dispute in, evidence out, CE3.0 validator | Disputes + Charges API, test mode |
| **Google Sheets** | order and shipment ledger; outcome ledger | Sheets API v4 |
| **Gmail** | customer thread in (evidence); email fallback out | Gmail API |
| **CALL-E** | one outbound confirmation call when the thread is silent; structured answer is evidence | `calle-ai` SDK, `calls.create_and_wait` with a result schema |
| **Photon** | one text to the customer after filing | spectrum-ts sidecar into an existing iMessage/RCS thread |
| **Slack** | human approval gate; run report | Bot + Socket Mode interactive buttons |

The call is the interesting one. A "product not received" dispute with a delivered scan but no word from the customer is the classic coin-flip filing. Rebuttal rings the customer once, asks two questions, and the answer decides: yes, and the transcript is cited and the packet is filed; no, and the agent HOLDs even though the carrier says delivered, because a customer who says no on the phone will say no to their bank. Live on the night: a real call to a real phone, `received=yes, recognises_charge=yes, confidence 0.95`.

GPT-6 Astra is the writer. It never chooses the verdict (a policy table does) and never touches an external app (the gate does). One model call per run, about 375 tokens.

## Reliability

Reliability is where the build spent a third of its time, because a filing agent's failures are silent: it can look like it worked and not have.

### 1. The write-gate and seven forbidden effects

Every side effect on an external app passes through `rebuttal/gate.py`. The seven forbidden effects are declared before the run, enforced in code, and counted. A blocked attempt is recorded in the trace as `attempted → BLOCKED → reason`, never silently dropped.

| Forbidden effect | Rule |
|---|---|
| `SUBMIT_WITHOUT_HUMAN_APPROVAL` | no Stripe submission without the Slack click |
| `DUPLICATE_FILING_SAME_DISPUTE` | a dispute is filed once, ever |
| `UNCITED_CLAIMS_IN_PACKET` | the writer produced a claim with no source record |
| `EDITED_CE3_PREFILLED_FIELD` | Stripe pre-fills IP and product description; editing them breaks eligibility |
| `SECOND_NOTICE_TO_CUSTOMER` | one notice per dispute, text or email, never both |
| `SECOND_CALL_TO_CUSTOMER` | one call per dispute, ever |
| `REFUND_OUTSIDE_SCOPE` | the agent may never refund |

Note that the Stripe disputes API **submits by default**. Rebuttal always stages with `submit=false`, reads the validator, and only then submits. The default is the single most dangerous thing in this integration.

### 2. Local stateful twins and a seeded scenario suite

`rebuttal/twins/` holds seedable, resettable twins of all six apps that record every call and every state change. The Stripe twin implements the same CE3.0 grading rule Stripe applies. The agent code is identical against twins and against the real apps.

`scenarios/` seeds 22 starting states. `python -m rebuttal.evalsuite` resets the twins, runs each scenario three times, and grades the *complete outcome*: verdict, final state, forbidden effects blocked, detector findings, and, for HOLD/CONCEDE/blocked runs, that the twin shows no filing. No model calls, no network, runs in seconds.

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

Nine scenarios are fault injections or edge cases: a writer that drops a citation, invents a tracking number, or cites a record that does not exist; a sub-agent that silently never runs. Findings appear only where a fault was injected.

### 3. Silent-failure detector

`rebuttal/detector.py` runs on every trace, before filing and again after the report. It compares what happened with what was supposed to happen, and names the mode:

| Mode | What it checks |
|---|---|
| **Skipped Work** | a gather sub-agent never issued its query, returned nothing, raised nothing |
| **Out of Scope Work** | an effect outside the allowed list succeeded |
| **Instruction Violation** | a claim without a citation |
| **Hallucination** | a claim citing a record not in the bundle; a tracking number that appears in no source |
| **Communication Failure** | the Slack report omits the verdict or the money |

On the first live run of the evening the agent reported a green SUBMIT → under_review, and the post-run detector flagged `Skipped Work: gmail.thread never ran its query (charge carries no customer email)`. The charge had been created without an email, so the Gmail sub-agent returned an empty list and no error. That trace is kept in `runs/examples/skipped-work-on-a-green-run.json` as the example of a success that was not one.

### 4. Self-improving harness, tighten-only

`python -m rebuttal.harness` reads the run traces. A SUBMIT that LOST makes the evidence that was absent on that run *required* for that reason code, written to `policy_overrides.json` and loaded at startup. The harness can add a requirement and can never remove one, so the agent gets stricter with every loss and never looser on its own. Loosening is a human edit to the file, in git, with a reason. Tests in `tests/test_harness.py` pin that set-union property.

### 5. Traces

One agent execution is one trace, in `runs/<run_id>.json`: gather spans with their result, the decision with the missing evidence named, the generation span with claims produced and dropped, every effect with OK / BLOCKED / ERROR, the interaction with the human's answer, and the report text. The Slack summary line quotes the run id.

## Known limitations

- **Test-mode verdicts are simulated.** Stripe's CE3.0 validator is real in test mode. The final won/lost is not: test mode resolves a dispute by the literal marker `winning_evidence` in one evidence field. The `STRIPE_TEST_OUTCOME_MARKER` env var adds it, only when the key is a test key, and the code says so. The Stripe outcome proves the filing pipeline; the scenario suite and the validator are the evaluation.
- **Prior-transaction ages are metadata in the demo.** Test mode cannot create charges 120 days in the past, so seeded prior charges carry an `age_days_override`. In live mode the age comes from `created`.
- **Carrier proof is a ledger column, not a carrier API call.** The signature-image vs signer-name distinction is graded, but the record comes from the Sheet. A UPS or EasyPost lookup is the obvious next integration.
- **Reason codes covered:** product_not_received, fraudulent, duplicate, product_unacceptable, credit_not_processed, subscription_canceled, unrecognized. Anything else HOLDs to a human.
- **Physical goods only in the live demo.** Digital-goods policy exists (access logs) but was not exercised live.
- **Slack approval is single-channel and synchronous.** A timeout is a HOLD, never a submit.
- **English-only threads**, no attachments parsed, no PDF evidence uploads yet.
- **Photon texts only into an existing thread.** A shared line will not open a cold conversation, so a customer who has never texted the line gets the email fallback. The trace records the refusal.
- **One call, two questions.** The CALL-E step asks receipt and recognition only, never discusses refunds, and runs once per dispute. Unanswered calls leave the evidence unchanged.
- **The harness only tightens.** It cannot learn that a requirement was too strict; a human decides that.

## Run it

```bash
pip install stripe openai slack-sdk google-api-python-client google-auth-oauthlib pydantic python-dotenv pytest

# offline: unit tests and the scenario suite (no keys needed)
python -m pytest -q
python -m rebuttal.evalsuite --attempts 3

# prove Stripe test mode grades CE3.0 (needs the Stripe CLI logged in)
bash scripts/verify_ce3.sh
```

Live run needs a `.env`:

```
STRIPE_SECRET_KEY=sk_test_...
OPENAI_API_KEY=sk-...
REBUTTAL_MODEL=gpt-6-astra
SLACK_BOT_TOKEN=xoxb-...          # scopes: chat:write, chat:write.public, channels:read, channels:join, channels:history
SLACK_APP_TOKEN=xapp-...          # connections:write, Socket Mode + interactivity on (manifest in slackapp/)
SLACK_CHANNEL=#rebuttal           # falls back to #general
STRIPE_TEST_OUTCOME_MARKER=winning_evidence   # test mode only
CALLE_API_KEY=iams_live_...        # CALL-E; omit to run without the call step
CALLE_BASE_URL=https://api.heycall-e.com
DEMO_CUSTOMER_PHONE=+1...          # the phone the demo customer answers on
```

Photon needs `SPECTRUM_PROJECT_ID` / `SPECTRUM_PROJECT_SECRET` from app.photon.codes, read by `photon/send.mjs` (set `PHOTON_ENV_FILE` to point at them and `PHOTON_SDK_DIR` at a `spectrum-ts` install).

plus `credentials.json`, a Google OAuth desktop client with Gmail and Sheets enabled (consent screen in Testing, your address as a test user). First run opens the consent screen once and writes `token.json`.

```bash
python -m rebuttal.demo seed                  # customer, two prior charges, the CE3.0 dispute, ledger sheet, email thread
python -m rebuttal.demo seed --silent-thread  # same, no email thread: the agent will call the customer
python -m rebuttal.demo run                   # runs the agent; answer the call, click Approve & file in Slack
```

## Layout

```
rebuttal/policy.py     verdict table: reason code × evidence → SUBMIT / HOLD / CONCEDE
rebuttal/gate.py       write-gate, six forbidden effects, trace
rebuttal/agent.py      orchestrator: gather → assess → decide → write → review → act
rebuttal/model.py      GPT-6 Astra writer; deterministic FakeModel for the suite
rebuttal/detector.py   silent-failure detector
rebuttal/twins/        seedable, resettable twins of Stripe, Gmail, Sheets, Slack
rebuttal/clients.py    real clients, same interface as the twins (Stripe, Gmail, Sheets, Slack, Photon, CALL-E)
rebuttal/harness.py    tighten-only self-improvement from lost filings
photon/send.mjs        Photon sidecar (spectrum-ts)
rebuttal/evalsuite.py  scenario runner: pass rate, 95% CI, blocked effects, findings
rebuttal/demo.py       live seed + run
scenarios/             22 seeded scenarios
scripts/verify_ce3.sh  Stripe CLI proof that test mode grades CE3.0
slackapp/              Slack app manifest
tests/                 unit tests for policy and gate
runs/                  one JSON trace per run
```
