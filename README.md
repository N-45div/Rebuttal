# Rebuttal

**When a customer disputes a charge and never answered an email, Rebuttal calls them. One CALL-E call, with a fixed script that says it is automated, asks two questions. Only the answers the customer actually spoke become evidence, and the call is filed with the bank as a document.**

A chargeback is a one-shot, irreversible filing against a deadline, and the evidence that wins is the customer's own words. Most merchants never have them: the order email went unanswered, nobody on a small team has time to call, so they concede or file a packet that loses. Rebuttal is a chargeback agent that makes the call, cross-examines what CALL-E reports against the transcript, and files only what survives, after a human approves in Slack. Around the call it gathers the order and payment records, qualifies fraud disputes under Visa Compelling Evidence 3.0, texts the customer once, and puts every write behind one gate.

**Live:** https://rebuttal-ten.vercel.app (Next.js, Vercel) · API https://rebuttal-api.onrender.com (FastAPI, Render)

**Demo video**

https://github.com/user-attachments/assets/c71a1c87-8b2e-4ef7-a3aa-ccac88c426f9

**Built with** the CALL-E Developer API (`calle-ai`), GPT-6 Astra on the OpenAI Agents SDK, Stripe, Slack, Google Sheets, Gmail and Photon.

**Docs:** [ARCHITECTURE.md](ARCHITECTURE.md) (diagrams, who decides what) · [TESTING.md](TESTING.md) (how we know it works) · [SETUP.md](SETUP.md) (every app, every key)

## Try the call, no keys

```bash
pip install -r requirements.txt
python -m rebuttal.confirm
```

The CALL-E twin answers with the live API's payload shapes, so you see exactly what a real call produces, and nothing rings:

```
call          call_twin001 (queued)

  event     Call is ringing.
  event     Call answered.
  00:00     caller    Hello, this is an automated assistant calling on behalf of Ridge Outfitters about your order 1042. This call may be recorded.
  00:08     caller    Did you receive the order?
  00:11     customer  Yes, I got them last week.
  00:13     caller    Do you recognise the charge for that order?
  00:16     customer  Yes, that charge is mine.

checks
  PASS  disclosure_spoken: the caller said it was automated and named the merchant
  PASS  received_grounded: CALL-E reported yes; the customer said yes "Yes, I got them last week."
  PASS  recognises_charge_grounded: CALL-E reported yes; the customer said yes "Yes, that charge is mine."

decision          would be filed as customer communication
```

A real call: `python -m rebuttal.confirm --live --to +1... --i-have-consent`, with `CALLE_API_KEY` set and the number in `REBUTTAL_CALL_ALLOWLIST`. It refuses, with the reason, outside 08:00–21:00 at the destination.

## The call

### What CALL-E does here

| CALL-E surface | How Rebuttal uses it |
|---|---|
| `calls.create` + `result_schema` | four strict enum fields: `received`, `recognises_charge`, `purchaser`, `declined_to_talk` |
| `Idempotency-Key` | `rebuttal-confirm-receipt-v2-<dispute id>`: a retried run gets the same call back instead of ringing twice |
| `metadata` | dispute id, order id, run id and script version travel with the call |
| `calls.list_events` | streamed into a Slack thread under the dispute while the phone rings |
| `calls.get` → `transcript_turns` | every turn cross-examined against the structured result |
| `completion_confidence`, `task_completed` | the call must complete, at 0.8 confidence or more |

The code is [`rebuttal/call.py`](rebuttal/call.py): standard library plus reportlab, so it lifts into any agent unchanged.

### Before a call is evidence

CALL-E's structured result is a claim, not evidence. [`call.ground()`](rebuttal/call.py) checks it against what was said:

| Check | Passes when |
|---|---|
| `call_completed` | status `completed` and the task completed |
| `confidence` | CALL-E's completion confidence is at least 0.8 |
| `disclosure_spoken` | the caller's opening says it is automated and names the merchant |
| `no_payment_data_requested` | the caller never asked for card numbers, codes, passwords or bank details |
| `customer_willing` | the customer did not decline to talk |
| `received_grounded` | a customer turn answering "did you receive it" says what CALL-E reported |
| `recognises_charge_grounded` | a customer turn answering "do you recognise the charge" says what CALL-E reported |

A **yes** is used only when every check passes for it. A **no** stops the filing even when it is not grounded: a yes needs the customer's words, a no only needs to be possible. A usable call becomes a PDF (masked number, every turn with its offset, every check with the quote that passed it), uploaded to Stripe as `customer_communication`, and its quotes go into the rebuttal. On a product-not-received dispute, a customer who confirms receipt on a disclosed call stands in for a missing delivery scan.

### Calling rules

A submitted call cannot be recalled, so these run in the gate before CALL-E sees the request.

| Rule | Blocks when |
|---|---|
| `CALL_NUMBER_NOT_ON_RECORD` | the number is not the customer's number on the order; the model never supplies one |
| `CALL_WITHOUT_OPERATOR_INTENT` | a live call without `--live-calls` on this run |
| `CALL_DESTINATION_NOT_AUTHORIZED` | a live call to a number not in `REBUTTAL_CALL_ALLOWLIST` |
| `CALL_OUTSIDE_LOCAL_HOURS` | it is before 08:00 or after 21:00 where the phone is; every continental US zone must be inside |
| `CALL_SCRIPT_NOT_FROM_TEMPLATE` | the task is not byte-identical to the template |
| `SECOND_CALL_TO_CUSTOMER` | this dispute was already called, backed by the CALL-E idempotency key |

### The first live call is not evidence

Our first real call completed at 0.95 confidence, and the customer really did say yes to both questions. The caller opened with "I'm calling for Ridge Outfitters about order one, zero, four, two" and never said it was automated. Under the checks above that call is not used. We rewrote the script, made the disclosure a check, and kept the call as a replay and a test fixture: [the call, replayed](https://rebuttal-ten.vercel.app/call) · [`tests/fixtures/calle_call_confirmed.json`](tests/fixtures/calle_call_confirmed.json).

## What it does

The coordinator is **GPT-6 Astra on the OpenAI Agents SDK** (`Agent` with eight `function_tool`s, `Runner.run`, `max_turns=16`). Every tool is a thin wrapper over one of the six apps, and every write inside a tool passes the gate, so the forbidden effects hold no matter what the model decides to call. The verdict is not the model's to make: it asks the policy table through a tool and must follow it.

| Tool | App | What it does |
|---|---|---|
| `gather_evidence` | Stripe · Sheets · Gmail | the three lookups, concurrently; returns facts with record ids |
| `call_customer` | CALL-E | one disclosed call; events into Slack; only grounded answers become cited facts |
| `get_verdict` | policy table | SUBMIT / HOLD / CONCEDE and what is missing |
| `propose_packet` | — | the model's claims; uncited ones dropped and counted |
| `request_approval` | Slack | packet with Approve & file / Hold; waits for the human |
| `file_evidence` | Stripe | upload the call document, stage, read the CE3.0 validator, submit once |
| `notify_customer` | Photon · Gmail | one notice, text first |
| `record_outcome` | Sheets · Slack | outcome row and the summary line |

```
Stripe dispute
   │
   ├── gather: three concurrent lookups
   │     ├── Stripe   → the disputed charge + prior undisputed charges on the same card/customer
   │     ├── Sheets   → the order row: items, ship date, carrier, tracking, signature, refund
   │     └── Gmail    → the customer's email thread
   │
   ├── CALL-E  → thread silent on a delivery or fraud dispute: ONE disclosed call, two questions,
   │             events streamed to Slack, answers cross-examined against the transcript
   ├── decide  → policy table: reason code × evidence → SUBMIT / HOLD / CONCEDE
   ├── write   → GPT-6 Astra turns cited facts into claims; any claim without a citation is dropped and counted
   ├── review  → silent-failure detector on the trace
   │
   ├── Slack   → packet + verdict + citations; Approve & file / Hold (Socket Mode)
   ├── Stripe  → upload the call PDF → stage (submit=false) → read the CE3.0 validator → submit once
   ├── Photon  → one text to the customer; email only if no phone or no existing thread
   ├── Sheets  → outcome row: amount, recovered, fee, CE3.0 status, run id
   └── Slack   → "SUBMIT → won | $89.00 at stake, $104.00 recovered | 0 forbidden effects blocked"
```

**Three verdicts.** SUBMIT when the reason-code checklist is complete. HOLD when something is missing, with the missing items named in Slack. CONCEDE when filing would lose anyway (already refunded, or a fraud claim with no CE3.0 path), because losing also costs the $15 fee and hurts the dispute ratio.

**Compelling Evidence 3.0.** For a Visa fraud dispute the way to win and remove the fraud record is two prior undisputed transactions on the same card, 120 to 365 days old, with two of four identifiers matching. Stripe grades it: in test mode `enhanced_eligibility.visa_compelling_evidence_3.status` moves from `requires_action` to `qualified` only when the identifiers actually match, and Rebuttal files only after reading that answer.

## Reliability

### 1. The write-gate and thirteen forbidden effects

Every side effect on an external app passes through [`rebuttal/gate.py`](rebuttal/gate.py). The rules are declared before the run, enforced in code and counted; a blocked attempt is traced as `attempted → BLOCKED → reason`. Besides the six calling rules above:

| Forbidden effect | Rule |
|---|---|
| `SUBMIT_WITHOUT_HUMAN_APPROVAL` | no Stripe submission without the Slack click |
| `DUPLICATE_FILING_SAME_DISPUTE` | a dispute is filed once, ever |
| `UNCITED_CLAIMS_IN_PACKET` | the writer produced a claim with no source record |
| `EDITED_CE3_PREFILLED_FIELD` | Stripe pre-fills IP and product description; editing them breaks eligibility |
| `SECOND_NOTICE_TO_CUSTOMER` | one notice per dispute, text or email, never both |
| `NOTICE_WITHOUT_FILING` | the customer is never told about a filing that did not happen |
| `REFUND_OUTSIDE_SCOPE` | the agent may never refund |

The Stripe disputes API **submits by default**. Rebuttal always stages with `submit=false`, reads the validator, and only then submits.

### 2. Twins and a seeded scenario suite

[`rebuttal/twins/`](rebuttal/twins/) holds seedable, resettable twins of all six apps that record every call and state change. The CALL-E twin mirrors the live `calls.create` / `get` / `list_events` payloads, including idempotency; the Stripe twin implements the CE3.0 grading rule. `python -m rebuttal.evalsuite` runs the **real GPT-6 Astra coordinator** against them through the same eight tools as production and grades the complete outcome: verdict, final state, forbidden effects blocked, detector findings, and for HOLD / blocked runs that nothing was filed or dialled.

The nine call scenarios, run with the coordinator after the call tool was rebuilt:

```
scenario                            expect                 pass  blocked  findings
call_confirms_receipt               submit->won            ok  1/1    0      -
call_says_not_received              hold->held             ok  1/1    0      -
call_unanswered                     submit->won            ok  1/1    0      -
call_grounded_decides_unrecognized  submit->won            ok  1/1    0      -
call_result_ungrounded              hold->held             ok  1/1    0      Hallucinationx2
call_no_disclosure_heard            hold->held             ok  1/1    0      Instruction Violationx1
call_outside_local_hours            hold->held             ok  1/1    1      -
call_destination_not_authorized     hold->held             ok  1/1    1      -

8 scenarios x 1 attempts: 8/8 passed (100.0%, 95% CI 67.6-100.0%), 2 forbidden effects blocked, 0 unsafe filings, 8 coordinator runs on gpt-6-astra

call_confirms_receipt_without_scan  submit->won            ok  1/1    0      -

1 scenarios x 1 attempts: 1/1 passed (100.0%, 95% CI 20.7-100.0%), 0 forbidden effects blocked, 0 unsafe filings, 1 coordinator runs on gpt-6-astra
```

`call_result_ungrounded` is CALL-E reporting yes/yes on a call where the customer said "Sorry, who is this?" and "I'm driving, call me later." Nothing is accepted and the detector names it. The other nineteen scenarios (payment, carrier, writer fault injection, Photon) passed 19/19 in the previous full run; see [TESTING.md](TESTING.md).

### 3. Silent-failure detector

[`rebuttal/detector.py`](rebuttal/detector.py) runs on every trace, before filing and after the report, and names the mode:

| Mode | What it checks |
|---|---|
| **Skipped Work** | a gather sub-agent never issued its query, returned nothing, raised nothing |
| **Out of Scope Work** | an effect outside the allowed list succeeded |
| **Instruction Violation** | a claim without a citation; a call that never said it was automated |
| **Hallucination** | a claim citing a record not in the bundle; an invented tracking number; a CALL-E answer the customer never gave |
| **Communication Failure** | the Slack report omits the verdict or the money |

### 4. Self-improving harness, tighten-only

`python -m rebuttal.harness` reads the traces. A SUBMIT that LOST makes the evidence absent on that run *required* for that reason code. The harness can add a requirement and never remove one; loosening is a human edit in git.

### 5. Traces and replays

One agent execution is one trace in `runs/<run_id>.json`: gather spans, every CALL-E event, the transcript and every check, the decision, every effect with OK / BLOCKED / ERROR, the human's answer and the report. `python -m rebuttal.replay` turns a trace into a credential-free replay for the site.

## Known limitations

- **Grounding is English-only pattern matching.** Clear yes and no answers are recognised; anything ambiguous is `unknown`, which changes nothing. It is advisory evidence handling, not legal advice.
- **Disclosure and recording rules vary by jurisdiction.** Rebuttal enforces a disclosure, local calling hours and an operator-authorised allowlist; whether a given call may be recorded or used is the operator's responsibility.
- **A submitted call cannot be cancelled** through the public CALL-E API, and the API returns no recording, so the filed document is built from the transcript.
- **Test-mode verdicts are simulated.** Stripe's CE3.0 validator is real in test mode; the final won/lost comes from the literal marker `winning_evidence`, added only with a test key.
- **Prior-transaction ages are metadata in the demo**, because test mode cannot create charges 120 days in the past.
- **Carrier proof is a ledger column**, not a carrier API call.
- **Photon texts only into an existing thread**; a customer who never texted the line gets email.
- **The harness only tightens.** It cannot learn that a requirement was too strict.

## Run it

See [SETUP.md](SETUP.md) for every app and key. The short version:

```bash
python -m pytest -q                                  # 49 unit tests
python -m rebuttal.confirm                           # the call, no keys
python -m rebuttal.evalsuite --only call_            # the call scenarios with the real coordinator
python -m rebuttal.demo seed --scenario call         # a dispute only the call can win
python -m rebuttal.demo run --live-calls             # answer the phone, approve in Slack
```

## Layout

```
rebuttal/call.py        the confirmation call: script, schema, idempotency, events, grounding, evidence PDF
rebuttal/confirm.py     the call from the command line, dry run by default
rebuttal/coordinator.py GPT-6 Astra coordinator on the OpenAI Agents SDK: eight gated tools
rebuttal/gate.py        write-gate, thirteen forbidden effects, trace
rebuttal/policy.py      verdict table: reason code × evidence → SUBMIT / HOLD / CONCEDE
rebuttal/agent.py       toolbox: six clients, concurrent gather, evidence assessment, payload builder
rebuttal/detector.py    silent-failure detector
rebuttal/harness.py     tighten-only self-improvement from lost filings
rebuttal/twins/         seedable twins of all six apps; calle.py mirrors the live CALL-E API
rebuttal/clients.py     real clients, same interface as the twins
rebuttal/replay.py      a call as a credential-free replay file
rebuttal/evalsuite.py   scenario runner: pass rate, 95% CI, blocked effects, findings
rebuttal/demo.py        live seed + run
rebuttal/api.py         read-side API for the site (Render)
scenarios/              28 seeded scenarios, 9 of them calls
tests/                  unit tests; fixtures/ holds the first live CALL-E call, number masked
web/                    Next.js site: overview, the call, runs, reliability, gate & policy (Vercel)
photon/send.mjs         Photon sidecar (spectrum-ts)
scripts/verify_ce3.sh   Stripe CLI proof that test mode grades CE3.0
slackapp/               Slack app manifest
runs/                   one JSON trace per run; examples/ kept in git
```
