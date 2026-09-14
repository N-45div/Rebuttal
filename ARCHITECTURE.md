# Architecture

One coordinator (GPT-6 Astra on the OpenAI Agents SDK), eight tools over six external apps, one disclosed CALL-E call per dispute, three verdicts, one gate in front of every write.

## The run

```mermaid
flowchart TD
    W[Stripe dispute] --> G

    subgraph G[gather · three lookups, concurrent]
        direction LR
        S1[Stripe<br/>charge + prior undisputed<br/>charges on the card/customer]
        S2[Google Sheets<br/>order row: items, ship date,<br/>carrier, tracking, signature, refund]
        S3[Gmail<br/>customer thread]
    end

    G --> C{thread silent on a<br/>delivery or fraud dispute,<br/>phone on file?}
    C -- yes --> CALL[CALL-E · one disclosed call<br/>events streamed to Slack<br/>answers grounded in the transcript]
    CALL --> D
    C -- no --> D

    D[decide · policy table<br/>reason code × evidence]
    D --> V{verdict}

    V -- CONCEDE --> LED
    V -- HOLD --> SL1[Slack: what is missing]
    V -- SUBMIT --> WR[write · GPT-6 Astra<br/>cited claims from facts<br/>uncited claims dropped + counted]
    WR --> RV1[review · detector pre-filing]
    RV1 --> SL2[Slack: packet + citations<br/>Approve & file / Hold]
    SL2 --> H{human click}
    H -- hold / timeout --> LED
    H -- approve --> DOC[Stripe Files: call document<br/>customer_communication]
    DOC --> ST1[Stripe: stage evidence<br/>submit=false]
    ST1 --> CE{Stripe CE3.0 validator<br/>qualified?}
    CE -- requires_action --> LED
    CE -- qualified or not a fraud dispute --> ST2[Stripe: submit=true<br/>one shot, irreversible]
    ST2 --> TX[Photon: one text to the customer<br/>Gmail only if no thread]
    TX --> LED
    SL1 --> LED

    LED[Sheets: outcome row] --> REP[Slack: summary line]
    REP --> RV2[review · detector post-run]
    RV2 --> TR[(runs/run_id.json<br/>one execution = one trace)]
```

Every box that touches an external app goes through the gate. The gate is not drawn on each edge because it is on every edge.

## The call

```mermaid
sequenceDiagram
    participant A as Astra coordinator
    participant T as call_customer tool
    participant G as gate
    participant C as CALL-E
    participant S as Slack thread
    participant X as Stripe

    A->>T: call_customer() — no arguments
    T->>S: Calling +91******5425 with CALL-E to confirm order 1042…
    T->>G: calls.create · number on record · operator intent · allowlist · local hours · script from template · once per dispute
    G-->>T: allowed, or BLOCKED with the reason (nothing rings)
    T->>C: calls.create(task, result_schema, metadata, Idempotency-Key)
    loop until completed, failed or timeout
        T->>C: list_events · get
        T->>S: CALL-E: Call is ringing. …
    end
    T->>T: ground(): completed? confidence ≥ 0.8? disclosure spoken?<br/>no payment data asked? customer's words say what CALL-E reported?
    T->>S: transcript, checks, decision
    T-->>A: used as evidence · not used · stops the filing
    A->>X: file_evidence: upload call PDF (Files API) → customer_communication → stage → validator → submit
```

The model cannot choose the number or the words: `call_customer` takes no arguments, reads the number from the order record, and builds the task from one template, and the gate re-derives that template before the create. CALL-E's structured result is a claim; [`call.ground()`](rebuttal/call.py) decides what survives. A yes needs the customer's words; a no only needs to be possible.

## The gate

```mermaid
flowchart LR
    AG[agent wants a side effect<br/>Effect app · action · target · params] --> GATE{gate.py<br/>thirteen rules, in order}
    GATE -- a rule fires --> B[BLOCKED<br/>counted · traced with reason<br/>raise Blocked]
    GATE -- no rule fires --> DO[do it] --> OK[OK · traced] --> BK[bookkeeping<br/>approved · acted · notified · called]

    subgraph filing
        R1[SUBMIT_WITHOUT_HUMAN_APPROVAL]
        R2[DUPLICATE_FILING_SAME_DISPUTE]
        R3[UNCITED_CLAIMS_IN_PACKET]
        R4[EDITED_CE3_PREFILLED_FIELD]
        R5[REFUND_OUTSIDE_SCOPE]
    end
    subgraph customer
        R6[SECOND_NOTICE_TO_CUSTOMER]
        R7[NOTICE_WITHOUT_FILING]
    end
    subgraph calling
        R8[SECOND_CALL_TO_CUSTOMER]
        R9[CALL_NUMBER_NOT_ON_RECORD]
        R10[CALL_WITHOUT_OPERATOR_INTENT]
        R11[CALL_DESTINATION_NOT_AUTHORIZED]
        R12[CALL_OUTSIDE_LOCAL_HOURS]
        R13[CALL_SCRIPT_NOT_FROM_TEMPLATE]
    end
```

The rules are plain functions of `(effect, state) -> reason | None`, declared in a list. The state they read (`approved`, `acted`, `emailed`, `called`, `uncited_claims`, `live_call_intent`, `call_allowlist`) is written by the gate after a successful effect, by the packet builder for the uncited count, or by the operator at the start of a run. The model cannot touch it.

## Who decides what

```mermaid
flowchart LR
    subgraph deterministic
        P[policy.py<br/>reason × evidence → verdict]
        GR[call.ground<br/>what the customer actually said]
        GT[gate.py<br/>may this write happen?]
        DT[detector.py<br/>did the run do what it said?]
        HS[harness.py<br/>tighten requirements after a loss]
    end
    subgraph model
        M[GPT-6 Astra coordinator · OpenAI Agents SDK<br/>calls the eight tools · writes the claims]
    end
    subgraph counterparty
        CU[customer on a CALL-E call<br/>received · recognises the charge]
        CE[Stripe CE3.0 validator<br/>qualified / requires_action]
        HU[human in Slack<br/>approve / hold]
    end
    CU --> GR --> P --> M --> GT
    CE --> GT
    HU --> GT
    GT --> DT --> HS --> P
```

The model writes prose and chooses the order of tools. Everything with a consequence is a table, a rule, a counterparty's answer, or a human's click.

## Twins

```mermaid
flowchart LR
    AGENT[coordinator + agent.py] --> IF[same interface]
    IF --> T[twins/<br/>StripeTwin · GmailTwin · SheetsTwin<br/>SlackTwin · PhotonTwin · CalleTwin<br/>seedable · resettable · record calls + effects]
    IF --> R[clients.py<br/>Stripe · Gmail · Sheets<br/>Slack · Photon · CALL-E SDK]
    T --> EV[evalsuite.py<br/>28 scenarios<br/>pass rate · 95% CI · blocked · findings]
    T --> CF[confirm.py<br/>the call, dry run]
    R --> DEMO[demo.py<br/>seed + run, live]
```

The coordinator does not know which one it has. The CALL-E twin mirrors the live `calls.create`, `calls.get` and `calls.list_events` payloads (verified against real calls), honours idempotency keys, and scripts the person who answers; the Stripe twin implements the CE3.0 grading rule; the Photon twin refuses cold threads like the real line.

## Data that crosses boundaries

| From | To | What | Where it is validated |
|---|---|---|---|
| Stripe | agent | dispute, charge, prior charges | reason code must be in the policy table, else HOLD |
| Sheets | agent | order row | column names fixed in `SheetsClient.ORDER_COLS`; booleans parsed |
| Gmail | agent | thread metadata + snippets | read-only; never quoted without a `gmail:` citation |
| agent | CALL-E | task, result schema, metadata, idempotency key | calling rules in the gate; E.164 check; task from one template |
| CALL-E | agent | events, transcript turns, structured result, confidence | `call.ground()`: completion, confidence, disclosure, no payment-data request, customer's words |
| model | agent | `{claims: [{text, source}]}` | every `source` must be a record id in the bundle, else dropped and counted |
| agent | Stripe | call document, evidence payload | PDF uploaded only for a usable call with a grounded yes; staged first; validator read before submit |
| agent | Slack | call thread, packet text + buttons | approval matched on message `ts`; timeout is HOLD |
| agent | Photon / Gmail | one customer note | one per dispute across both channels, only after a filing |

## Files

```
rebuttal/call.py        the confirmation call                  stdlib + reportlab, portable
rebuttal/confirm.py     the call from the command line          dry run by default
rebuttal/coordinator.py Astra coordinator, 8 gated tools        OpenAI Agents SDK
rebuttal/gate.py        write-gate, thirteen rules, trace       deterministic
rebuttal/policy.py      verdict table                           deterministic
rebuttal/agent.py       toolbox: clients, gather, assess        async, 3 concurrent lookups
rebuttal/detector.py    silent-failure detector                 deterministic
rebuttal/harness.py     tighten-only self-improvement           deterministic
rebuttal/twins/         six twins                               offline
rebuttal/clients.py     six real clients                        online
rebuttal/replay.py      a call as a replay file                 offline
rebuttal/evalsuite.py   scenario runner                         offline apps, real model
rebuttal/demo.py        seed + live run                         online
photon/send.mjs         Photon sidecar (Node, spectrum-ts)      online
scenarios/              28 seeded starting states, 9 calls
runs/                   one JSON trace per execution
```
