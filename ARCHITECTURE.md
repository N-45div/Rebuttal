# Architecture

One orchestrator, six external apps, three verdicts, one gate in front of every write.

## The run

```mermaid
flowchart TD
    W[Stripe dispute<br/>charge.dispute.created] --> G

    subgraph G[gather · three sub-agents, concurrent]
        direction LR
        S1[Stripe<br/>charge + prior undisputed<br/>charges on the card/customer]
        S2[Google Sheets<br/>order row: items, ship date,<br/>carrier, tracking, signature, refund]
        S3[Gmail<br/>customer thread]
    end

    G --> C{thread silent on a<br/>delivery dispute?}
    C -- yes --> CALL[CALL-E<br/>one confirmation call<br/>received? recognises charge?]
    CALL --> A
    C -- no --> A

    A[assess<br/>deterministic evidence checks<br/>delivered · signed · refunded<br/>CE3.0 priors 120-365d · identifiers match]
    A --> D[decide · policy table<br/>reason code × evidence]
    D --> V{verdict}

    V -- CONCEDE --> LED
    V -- HOLD --> SL1[Slack: packet + what is missing]
    V -- SUBMIT --> WR[write · GPT-6 Astra<br/>cited claims from facts<br/>uncited claims dropped + counted]
    WR --> RV1[review · detector pre-filing<br/>Instruction Violation · Hallucination]
    RV1 --> SL2[Slack: packet + citations<br/>Approve & file / Hold]
    SL2 --> H{human click}
    H -- hold / timeout --> LED
    H -- approve --> ST1[Stripe: stage evidence<br/>submit=false]
    ST1 --> CE{Stripe CE3.0 validator<br/>qualified?}
    CE -- requires_action --> LED
    CE -- qualified --> ST2[Stripe: submit=true<br/>one shot, irreversible]
    ST2 --> TX[Photon: one text to the customer<br/>Gmail only if no thread]
    TX --> LED
    SL1 --> LED

    LED[Sheets: outcome row<br/>amount · recovered · fee · CE3.0 · run id]
    LED --> REP[Slack: summary line<br/>verdict → outcome · $ · effects blocked · run id]
    REP --> RV2[review · detector post-run<br/>Skipped Work · Out of Scope · Communication Failure]
    RV2 --> TR[(runs/run_id.json<br/>one execution = one trace)]
```

Every box on the right-hand column that touches an external app (Slack, Stripe, Photon, Gmail, Sheets, CALL-E) is a call through the gate. The gate is not drawn on each edge because it is on every edge.

## The gate

```mermaid
flowchart LR
    AG[agent wants a side effect<br/>Effect app · action · target · params] --> GATE{gate.py<br/>seven rules, in order}
    GATE -- a rule fires --> B[BLOCKED<br/>counted · traced with reason<br/>raise Blocked]
    GATE -- no rule fires --> DO[do it] --> OK[OK · traced] --> BK[bookkeeping<br/>approved · acted · emailed · called]

    subgraph rules
        R1[SUBMIT_WITHOUT_HUMAN_APPROVAL]
        R2[DUPLICATE_FILING_SAME_DISPUTE]
        R3[UNCITED_CLAIMS_IN_PACKET]
        R4[EDITED_CE3_PREFILLED_FIELD]
        R5[SECOND_NOTICE_TO_CUSTOMER]
        R6[SECOND_CALL_TO_CUSTOMER]
        R7[REFUND_OUTSIDE_SCOPE]
    end
```

The rules are plain functions of `(effect, state) -> reason | None`, declared in a list. Adding a forbidden effect is adding a function. The state the rules read (`approved`, `acted`, `emailed`, `called`, `uncited_claims`) is written only by the gate itself after a successful effect, or by the packet builder for the uncited count. The model cannot touch it.

## Who decides what

```mermaid
flowchart LR
    subgraph deterministic
        P[policy.py<br/>reason × evidence → verdict]
        AS[assess<br/>evidence from records]
        GT[gate.py<br/>may this write happen?]
        DT[detector.py<br/>did the run do what it said?]
        HS[harness.py<br/>tighten requirements after a loss]
    end
    subgraph model
        M[GPT-6 Astra<br/>facts → cited claims]
    end
    subgraph counterparty
        CE[Stripe CE3.0 validator<br/>qualified / requires_action]
        CU[customer on the phone<br/>received yes / no]
        HU[human in Slack<br/>approve / hold]
    end
    AS --> P --> M --> GT
    CE --> GT
    CU --> AS
    HU --> GT
    GT --> DT --> HS --> P
```

The model writes prose. Everything that has a consequence is either a table, a rule, a counterparty's answer, or a human's click.

## Sub-agents

The three gather sub-agents run under `asyncio.gather`, each in a thread, each recording a `gather` span with `ok`, `empty` or `skipped`. `empty` means the query ran and found nothing, which is an answer. `skipped` means the query never ran because its input was missing, which is the silent failure the detector reports as Skipped Work. The distinction matters: the first live run of the night was green and `skipped`.

The CALL-E step is a fourth, conditional sub-agent. It runs only when the thread is silent on a delivery dispute and a phone is on file, and its structured result is appended to the facts with a `calle:` citation like any other record.

## Twins

```mermaid
flowchart LR
    AGENT[agent.py] --> IF[same interface]
    IF --> T[twins/<br/>StripeTwin · GmailTwin · SheetsTwin<br/>SlackTwin · PhotonTwin · CalleTwin<br/>seedable · resettable · record calls + effects]
    IF --> R[clients.py<br/>Stripe · Gmail · Sheets<br/>Slack · Photon · CALL-E]
    T --> EV[evalsuite.py<br/>22 scenarios × 3 attempts<br/>pass rate · 95% CI · blocked · findings]
    R --> DEMO[demo.py<br/>seed + run, live]
```

The agent does not know which one it has. The Stripe twin implements the CE3.0 grading rule, the Photon twin refuses cold threads like the real line, the CALL-E twin answers with whatever the scenario scripted.

## Data that crosses boundaries

| From | To | What | Where it is validated |
|---|---|---|---|
| Stripe | agent | dispute, charge, prior charges | reason code must be in the policy table, else HOLD |
| Sheets | agent | order row | column names fixed in `SheetsClient.ORDER_COLS`; booleans parsed |
| Gmail | agent | thread metadata + snippets | read-only; never quoted without a `gmail:` citation |
| CALL-E | agent | `{received, recognises_charge}` | schema-constrained enum; `unknown` changes nothing |
| model | agent | `{claims: [{text, source}]}` | every `source` must be a record id in the bundle, else dropped and counted |
| agent | Stripe | evidence payload | staged first; the CE3.0 validator's answer is read before submit; prefilled fields never sent |
| agent | Slack | packet text + buttons | approval matched on message `ts`; timeout is HOLD |
| agent | Photon / Gmail | one customer note | one per dispute across both channels |

## Files

```
rebuttal/policy.py      verdict table                       deterministic
rebuttal/gate.py        write-gate, seven rules, trace       deterministic
rebuttal/agent.py       orchestrator                         async, 3 concurrent sub-agents + conditional call
rebuttal/model.py       Astra writer · FakeModel             one model call per run
rebuttal/detector.py    silent-failure detector              deterministic
rebuttal/harness.py     tighten-only self-improvement        deterministic
rebuttal/twins/         six twins                            offline
rebuttal/clients.py     six real clients                     online
rebuttal/evalsuite.py   scenario runner                      offline
rebuttal/demo.py        seed + live run                      online
photon/send.mjs         Photon sidecar (Node, spectrum-ts)   online
scenarios/              22 seeded starting states
runs/                   one JSON trace per execution
```
