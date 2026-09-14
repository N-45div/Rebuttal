# Rebuttal

**A chargeback agent that calls the customer.** When a customer disputes a charge and the email thread is silent, Rebuttal places one CALL-E call with a fixed script that says it is automated, asks two questions, and files only the answers the customer actually spoke, as a document the bank can read.

![Cross-examination of our first live CALL-E call: CALL-E reported yes and yes at 0.95 confidence and the customer did say yes, but the caller never said it was automated, so the call is not used](docs/img/cross-examination.png)

<sub>Our first live CALL-E call, cross-examined on the [live site](https://rebuttal-ten.vercel.app/call). CALL-E reported yes and yes at 0.95 confidence and the customer really said yes, but the caller never said it was automated, so Rebuttal does not file it.</sub>

**Live:** https://rebuttal-ten.vercel.app · **Docs:** [ARCHITECTURE.md](ARCHITECTURE.md) (diagrams, who decides what) · [TESTING.md](TESTING.md) (how we know it works) · [SETUP.md](SETUP.md) (every app, every key)

**Demo video**

https://github.com/user-attachments/assets/c71a1c87-8b2e-4ef7-a3aa-ccac88c426f9

## Where CALL-E runs

Rebuttal imports the CALL-E Python SDK (`calle-ai`) and calls it at runtime: in the agent's call tool, in the command-line call, and in the app contributed upstream.

| CALL-E surface | What Rebuttal does with it | Code |
|---|---|---|
| `calls.create` | one call per dispute: the fixed script, `result_schema`, `metadata` and an idempotency key | [call.py#L154-L169](rebuttal/call.py#L154-L169) |
| `result_schema` | four strict enum fields: `received`, `recognises_charge`, `purchaser`, `declined_to_talk` | [call.py#L30-L44](rebuttal/call.py#L30-L44) |
| `Idempotency-Key` | `rebuttal-confirm-receipt-v2-<dispute id>`: a retried run gets the same call back instead of ringing twice | [call.py#L69-L70](rebuttal/call.py#L69-L70) |
| `calls.list_events` | streamed into Slack while the phone rings | [call.py#L188-L208](rebuttal/call.py#L188-L208) |
| `calls.get` → `transcript_turns` | every turn cross-examined against the structured result | [call.py#L209](rebuttal/call.py#L209) · [call.py#L295](rebuttal/call.py#L295) |
| `completion_confidence`, `task_completed` | the call must complete, at 0.8 confidence or more | [call.py#L295](rebuttal/call.py#L295) |
| the agent's call tool | gate, then place, follow and ground | [coordinator.py#L73-L114](rebuttal/coordinator.py#L73-L114) |
| the call as evidence | the grounded call rendered as a PDF and uploaded to Stripe | [coordinator.py#L194-L206](rebuttal/coordinator.py#L194-L206) |
| the SDK client | `CalleClient` behind the same interface as the twin | [clients.py#L303-L314](rebuttal/clients.py#L303-L314) |
| one call from the command line | `python -m rebuttal.confirm --live` | [confirm.py#L65-L84](rebuttal/confirm.py#L65-L84) |

[`rebuttal/call.py`](rebuttal/call.py) depends on nothing but the standard library and reportlab, so it lifts into any agent unchanged.

## Try the call without keys

```bash
git clone https://github.com/N-45div/Rebuttal && cd Rebuttal
pip install -r requirements.txt
python -m rebuttal.confirm
```

The CALL-E twin answers with the live API's payload shapes, so you see exactly what a real call produces, and nothing rings. The output, trimmed:

```
script        confirm-receipt-v2: Hello, this is an automated assistant calling on behalf of Ridge Outfitters about your order 1042. This call may be recorded.
idempotency   rebuttal-confirm-receipt-v2-du_confirm_demo

mode          dry run: the CALL-E twin answers, nothing rings
call          call_twin001 (queued)

  event     Call is ringing.
  event     Call answered.
  event     Call completed.
  00:00     caller    Hello, this is an automated assistant calling on behalf of Ridge Outfitters about your order 1042. This call may be recorded.
  00:08     caller    Did you receive the order?
  00:11     customer  Yes, I got them last week.
  00:13     caller    Do you recognise the charge for that order?
  00:16     customer  Yes, that charge is mine.

checks
  PASS  call_completed: status completed, task_completed True
  PASS  confidence: completion confidence 0.93 (minimum 0.8)
  PASS  disclosure_spoken: the caller said it was automated and named the merchant "Hello, this is an automated assistant calling on behalf of Ridge Outfitters about your order 1042. This call may be recorded."
  PASS  no_payment_data_requested: the caller never asked for payment data
  PASS  customer_willing: the customer answered
  PASS  received_grounded: CALL-E reported yes; the customer said yes "Yes, I got them last week."
  PASS  recognises_charge_grounded: CALL-E reported yes; the customer said yes "Yes, that charge is mine."

accepted          received=yes  recognises_charge=yes
document          runs/evidence/call_twin001.pdf
decision          would be filed as customer communication
```

One real call, to a phone whose owner agreed: `python -m rebuttal.confirm --live --to +1... --i-have-consent`, with `CALLE_API_KEY` set and the number listed in `REBUTTAL_CALL_ALLOWLIST`. It refuses, with the reason, outside 08:00–21:00 where the phone is.

## Why call, and why cross-examine the answer

A chargeback is a one-shot filing against a deadline, and the evidence that wins is the customer's own words. Most merchants never have them: the order email went unanswered and nobody on a small team has time to call, so they concede or file a packet that loses. Rebuttal's coordinator, GPT-6 Astra on the OpenAI Agents SDK, gathers the dispute, the order and the email thread. When the thread is silent on a delivery or fraud dispute, it calls.

A completed call is not yet evidence. CALL-E's structured result is a claim, so [`call.ground()`](rebuttal/call.py#L295) checks it against what was said:

| Check | Passes when |
|---|---|
| `call_completed` | status `completed` and the task completed |
| `confidence` | CALL-E's completion confidence is at least 0.8 |
| `disclosure_spoken` | the caller's opening says it is automated and names the merchant |
| `no_payment_data_requested` | the caller never asked for card numbers, codes, passwords or bank details |
| `customer_willing` | the customer did not decline to talk |
| `received_grounded` | a customer turn answering "did you receive it" says what CALL-E reported |
| `recognises_charge_grounded` | a customer turn answering "do you recognise the charge" says what CALL-E reported |

A **yes** is used only when every check passes for it. A **no** stops the filing even when it is not grounded: a yes needs the customer's words, a no only needs to be possible. A usable call becomes a PDF (masked number, every turn with its offset, every check with the quote that passed it), uploaded to Stripe as dispute evidence and attached as `customer_communication`. Its quotes go into the rebuttal, and a human approves in Slack before anything is filed. On a product-not-received dispute, a customer who confirms receipt on a disclosed call stands in for a missing delivery scan.

### The first live call is not evidence

Our first real call completed at 0.95 confidence, and the customer really did say yes to both questions. The caller opened with "I'm calling for Ridge Outfitters about order one, zero, four, two" and never said it was automated. Under the checks above that call is not used, which is the screenshot at the top. We rewrote the script, made the disclosure a check, and kept the call as a replay and a test fixture: [the call, replayed](https://rebuttal-ten.vercel.app/call) · [`tests/fixtures/calle_call_confirmed.json`](tests/fixtures/calle_call_confirmed.json).

## Calling rules

A submitted call cannot be recalled, so these run in the gate before CALL-E sees the request.

| Rule | Blocks when | Code |
|---|---|---|
| `CALL_NUMBER_NOT_ON_RECORD` | the number is not the customer's number on the order; the model never supplies one | [gate.py#L129](rebuttal/gate.py#L129) |
| `CALL_WITHOUT_OPERATOR_INTENT` | a live call without `--live-calls` on this run | [gate.py#L135](rebuttal/gate.py#L135) |
| `CALL_DESTINATION_NOT_AUTHORIZED` | a live call to a number not in `REBUTTAL_CALL_ALLOWLIST` | [gate.py#L141](rebuttal/gate.py#L141) |
| `CALL_OUTSIDE_LOCAL_HOURS` | before 08:00 or after 21:00 where the phone is; every continental US zone must be inside | [gate.py#L148](rebuttal/gate.py#L148) |
| `CALL_SCRIPT_NOT_FROM_TEMPLATE` | the task is not byte-identical to the template | [gate.py#L158-L167](rebuttal/gate.py#L158-L167) |
| `SECOND_CALL_TO_CUSTOMER` | this dispute was already called, backed by the CALL-E idempotency key | [gate.py#L109](rebuttal/gate.py#L109) |

## How we know it works

- **52 unit tests, no keys:** grounding against the real transcript of our first live call, each calling rule, the gate, the policy table and the replay decision. `python -m pytest -q`
- **28 seeded scenarios, 9 of them calls,** run by the real GPT-6 Astra coordinator against resettable twins of all six apps. The CALL-E twin mirrors the live `calls.create`, `get` and `list_events` payloads, including idempotency. The runner grades the complete outcome: verdict, final state, forbidden effects blocked, detector findings, and that nothing was filed or dialled when it should not be.

The nine call scenarios, from two runs of the suite (both are in [TESTING.md](TESTING.md)):

```
scenario                            expect                 pass  blocked  findings
call_confirms_receipt               submit->won            ok  1/1    0      -
call_confirms_receipt_without_scan  submit->won            ok  1/1    0      -
call_grounded_decides_unrecognized  submit->won            ok  1/1    0      -
call_unanswered                     submit->won            ok  1/1    0      -
call_says_not_received              hold->held             ok  1/1    0      -
call_result_ungrounded              hold->held             ok  1/1    0      Hallucinationx2
call_no_disclosure_heard            hold->held             ok  1/1    0      Instruction Violationx1
call_outside_local_hours            hold->held             ok  1/1    1      -
call_destination_not_authorized     hold->held             ok  1/1    1      -
```

`call_result_ungrounded` is CALL-E reporting yes and yes on a call where the customer said "Sorry, who is this?" and "I'm driving, call me later." Nothing is accepted, nothing is filed, and the silent-failure detector names it a hallucination. The other nineteen scenarios (payments, carrier data, writer fault injection, Photon) passed 19/19 in the previous full run.

## The rest of the agent

The coordinator is **GPT-6 Astra on the OpenAI Agents SDK** (`Agent` with eight `function_tool`s, `Runner.run`, `max_turns=16`). Every tool is a thin wrapper over one app, and every write inside a tool passes the gate, so the forbidden effects hold no matter what the model decides to call. The verdict is not the model's to make: it asks the policy table through a tool and must follow it.

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

**Thirteen forbidden effects** live in [`rebuttal/gate.py`](rebuttal/gate.py): the six calling rules above, plus no submission without the Slack click, one filing per dispute, no uncited claims, no edits to the fields Stripe pre-fills for Compelling Evidence 3.0, one notice per customer, no notice without a filing, and no refunds. A blocked attempt is traced as `attempted → BLOCKED → reason`. The Stripe disputes API submits by default, so Rebuttal always stages with `submit=false`, reads the Visa Compelling Evidence 3.0 validator, and only then submits.

**Silent-failure detector.** [`rebuttal/detector.py`](rebuttal/detector.py) runs before filing and after the report, and names the mode: Skipped Work, Out of Scope Work, Instruction Violation (an uncited claim; a call that never said it was automated), Hallucination (a record not in the bundle; a CALL-E answer the customer never gave), Communication Failure.

**Tighten-only harness.** `python -m rebuttal.harness` reads the traces. A SUBMIT that lost makes the evidence absent on that run required for that reason code. The harness can add a requirement and never remove one; loosening is a human edit in git.

**Traces and replays.** One run is one trace in `runs/<run_id>.json`: gather spans, every CALL-E event, the transcript and every check, the decision, every effect with OK / BLOCKED / ERROR, the human's answer and the report. `python -m rebuttal.replay` turns a trace or a saved CALL-E payload into the credential-free replay the site plays.

## Contributed upstream

The call is contributed to CALL-E's [awesome-phone-call-agents](https://github.com/CALLE-AI/awesome-phone-call-agents) as a standalone app and an agent skill, with no real phone numbers, recordings or private transcripts:

- [`apps/python/rebuttal-dispute-call`](https://github.com/N-45div/awesome-phone-call-agents/tree/feat/rebuttal-dispute-call/apps/python/rebuttal-dispute-call): the call module from this repo, the calling rules, a CLI and 75 tests
- [`skills/dispute-evidence-call`](https://github.com/N-45div/awesome-phone-call-agents/tree/feat/rebuttal-dispute-call/skills/dispute-evidence-call): the agent skill for placing and grounding a dispute evidence call

## Known limitations

- **Grounding is English-only pattern matching.** Clear yes and no answers are recognised; anything ambiguous is `unknown`, which changes nothing. It is evidence handling, not legal advice.
- **Disclosure and recording rules vary by jurisdiction.** Rebuttal enforces a disclosure, local calling hours and an operator-authorised allowlist; whether a given call may be recorded or used is the operator's responsibility.
- **A submitted call cannot be cancelled** through the public CALL-E API, and the API returns no recording, so the filed document is built from the transcript.
- **Test-mode verdicts are simulated.** Stripe's CE3.0 validator is real in test mode; the final won or lost comes from the literal marker `winning_evidence`, added only with a test key.
- **Prior-transaction ages are metadata in the demo**, because test mode cannot create charges 120 days in the past.
- **Carrier proof is a ledger column**, not a carrier API call.
- **Photon texts only into an existing thread**; a customer who never texted the line gets email.

## Run it

See [SETUP.md](SETUP.md) for every app and key. The short version:

```bash
python -m pytest -q                                  # 52 unit tests
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
docs/img/               README images
runs/                   one JSON trace per run; examples/ kept in git
```
