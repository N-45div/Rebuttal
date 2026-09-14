"""GPT-6 Astra as the coordinator, on the OpenAI Agents SDK, with the six apps as tools.

Every tool is a thin wrapper over the same clients (or twins) and passes through the same gate,
so the forbidden effects hold no matter what the model decides to call. The policy table still
owns the verdict: the model asks for it through a tool and must follow it.

    python -m rebuttal.demo run
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agents import Agent, RunContextWrapper, Runner, function_tool
from pydantic import BaseModel

from . import call
from .agent import DISPUTE_FEE_CENTS, Bundle, Rebuttal
from .detector import detect
from .gate import Blocked, Effect, Gate, GateState, Trace
from .policy import Decision, Evidence, Verdict, decide


class Claim(BaseModel):
    text: str
    source: str


@dataclass
class Ctx:
    core: Rebuttal                 # holds the clients (real or twins) and the helper methods
    trace: Trace
    gate: Gate
    dispute_id: str
    bundle: Bundle | None = None
    have: set = field(default_factory=set)
    kind: str = "physical"
    decision: Decision | None = None
    packet: dict[str, Any] = field(default_factory=lambda: {"claims": [], "raw_claims": []})
    dropped: int = 0
    approved: bool = False
    outcome: str = "held"
    recovered: int = 0
    ce3_status: str | None = None
    call: Any = None               # call.CallRecord once the confirmation call has ended
    grounding: Any = None          # call.Grounding: what survived cross-examination
    call_file: str | None = None   # Stripe file id of the call document
    fault: str | None = None       # eval-suite fault injection: uncited | invent_tracking | wrong_source


@function_tool
async def gather_evidence(ctx: RunContextWrapper[Ctx]) -> str:
    """Fetch the dispute, the charge, the order row from the ledger, the customer's email thread and prior charges. Returns the facts with their record ids."""
    c = ctx.context
    c.bundle = await c.core.gather(c.dispute_id, c.trace)
    c.have, c.kind = c.core.assess(c.bundle)
    b = c.bundle
    return json.dumps({"reason": b.dispute["reason"], "amount_cents": b.dispute["amount"], "email_thread_messages": len(b.thread),
                       "customer_phone_on_file": bool((b.charge.get("billing_details") or {}).get("phone")),
                       "facts": b.facts, "evidence_present": sorted(e.value for e in c.have)})


_SHOW_EVENT = re.compile(r"ring|answer|connect|complet|fail|busy|voicemail|hang", re.I)


@function_tool
def call_customer(ctx: RunContextWrapper[Ctx]) -> str:
    """Place ONE CALL-E confirmation call to the customer's number on record: a fixed script that says it is an automated call, then asks whether they received the order and whether they recognise the charge. CALL-E's structured answer is cross-examined against the transcript and only answers the customer actually gave become evidence. Takes no arguments: the model never chooses the number or the words."""
    c = ctx.context
    b, core = c.bundle, c.core
    bd = b.charge.get("billing_details") or {}
    phone = bd.get("phone")
    if not phone or core.calle is None:
        return json.dumps({"error": "no phone on file or calling disabled"})
    o = b.order or {}
    args = {"merchant": core.merchant, "order_id": str(o.get("order_id", "")), "items": o.get("items") or "your order",
            "amount": f"${b.dispute['amount'] / 100:.2f}"}
    params = {"phone": phone, "customer_phone": bd.get("phone"), "task": call.build_task(**args), "template_args": args,
              "live": bool(getattr(core.calle, "live", False)), "now": core.now.isoformat()}

    def say(text: str, thread: str | None = None) -> dict[str, Any]:
        return c.gate(Effect("slack", "chat.postMessage", core.channel), lambda: core.slack.post(core.channel, text, thread_ts=thread))

    head = say(f"*Dispute {c.dispute_id}* \u00b7 {b.dispute['reason']} \u00b7 no email thread from the customer. "
               f"Calling {call.mask(phone)} with CALL-E to confirm order {args['order_id']}\u2026")
    thread = (head or {}).get("ts")
    try:
        created = c.gate(Effect("calle", "calls.create", c.dispute_id, params),
                         lambda: call.place(core.calle, dispute_id=c.dispute_id, phone=phone, run_id=c.trace.run_id, **args))
    except Blocked as e:
        say(f"Call not placed: {e}", thread)
        return json.dumps({"blocked": str(e)})
    except Exception as e:
        c.trace.span("effect", "calle.calls.create", target=c.dispute_id, result="ERROR", error=str(e)[:300])
        say(f"CALL-E did not accept the call: {str(e)[:200]}", thread)
        return json.dumps({"error": str(e)[:300]})

    call_id = created.get("id") or created.get("call_id", "")
    c.trace.span("gather", "calle.call_created", result="ok", call_id=call_id, idempotency_key=call.idempotency_key(c.dispute_id))

    def on_event(e: dict[str, Any]) -> None:
        msg = e.get("message") or e.get("type") or ""
        c.trace.span("event", "calle.event", type=e.get("type"), message=msg)
        if _SHOW_EVENT.search(msg):
            say(f"_CALL-E: {msg}_", thread)

    rec = call.follow(core.calle, call_id, on_event=on_event, interval=core.call_poll_seconds)
    g = call.ground(rec, core.merchant)
    c.call, c.grounding = rec, g
    if rec.turns:
        say("*Transcript*\n" + "\n".join(
            f"`{call._clock(t.get('offset_seconds'))}` {'Caller' if call._is_caller(t) else 'Customer'}: {t.get('text', '')}"
            for t in rec.turns), thread)
    say("*Checks*\n" + "\n".join(("\u2705 " if x.passed else "\u274c ") + f"{x.name}: {x.detail}"
                                    + (f" \u201c{x.quote}\u201d" if x.quote else "") for x in g.checks), thread)
    c.trace.span("gather", "calle.grounding", result=rec.status, call_id=rec.call_id, reported=g.reported, accepted=g.accepted,
                 usable=g.usable, denied=g.denied, confidence=rec.confidence, duration=rec.duration_seconds, turns=len(rec.turns),
                 transcript=rec.turns, checks=[asdict(x) for x in g.checks])
    used = g.usable and not g.denied and "yes" in (g.accepted.get("received"), g.accepted.get("recognises_charge"))
    verdict = "stops the filing" if g.denied else ("used as evidence" if used else "not used")
    say(f"Call {rec.status}: received={g.accepted.get('received')}, recognises charge={g.accepted.get('recognises_charge')} "
        f"(CALL-E reported {g.reported.get('received', 'unknown')}/{g.reported.get('recognises_charge', 'unknown')}, "
        f"confidence {rec.confidence}) \u2192 {verdict}.")
    if used:
        q = {x.name: x.quote for x in g.checks if x.quote}
        b.facts.append({"id": f"calle:{rec.call_id}", "text": (
            f"Recorded phone call with the customer ({rec.started_at or 'date on file'}), placed by an automated assistant that disclosed itself. "
            f"Asked whether they received order {args['order_id']}, the customer said \"{q.get('received_grounded', '')}\". "
            f"Asked whether they recognise the {args['amount']} charge, the customer said \"{q.get('recognises_charge_grounded', '')}\".")})
        if g.accepted.get("received") == "yes":
            c.have.add(Evidence.CUSTOMER_COMMUNICATION)
            c.have.add(Evidence.CUSTOMER_CONFIRMED_RECEIPT)
    return json.dumps({"call_id": rec.call_id, "status": rec.status, "used_as_evidence": used, "accepted": g.accepted,
                       "denied": g.denied, "checks": {x.name: x.passed for x in g.checks}})


@function_tool
def get_verdict(ctx: RunContextWrapper[Ctx]) -> str:
    """Ask the policy table for the verdict: SUBMIT, HOLD or CONCEDE, with what is missing. You must follow it."""
    c = ctx.context
    d = decide(c.bundle.dispute["reason"], c.kind, c.have)
    if c.grounding is not None and c.grounding.denied and d.verdict == Verdict.SUBMIT:
        d = Decision(Verdict.HOLD, [], "customer said no on the phone; human decides")
    c.decision = d
    c.trace.span("decision", "policy.decide", verdict=d.verdict.value, missing=[m.value for m in d.missing], reason=d.reason,
                 reason_code=c.bundle.dispute["reason"], fulfilment=c.kind, have=sorted(e.value for e in c.have))
    return json.dumps({"verdict": d.verdict.value, "missing": [m.value for m in d.missing], "reason": d.reason})


@function_tool
def propose_packet(ctx: RunContextWrapper[Ctx], claims: list[Claim]) -> str:
    """Submit your rebuttal claims. Each claim MUST cite exactly one fact id from gather_evidence in `source`. Uncited or unknown sources are dropped and counted, and the gate will refuse to file if any were dropped."""
    c = ctx.context
    raw = [{"text": k.text, "source": k.source} for k in claims]
    if c.fault == "uncited" and raw: raw[0]["source"] = ""
    if c.fault == "wrong_source" and raw: raw[0]["source"] = "rec_does_not_exist"
    if c.fault == "invent_tracking": raw.append({"text": "Delivered under tracking 1Z999FAKE0000000001", "source": raw[0]["source"] if raw else ""})
    ids = set(c.bundle.record_ids)
    kept = [k for k in raw if k["source"] in ids]
    c.dropped = len(raw) - len(kept)
    c.packet = {"claims": kept, "raw_claims": raw}
    c.gate.state.uncited_claims = c.dropped
    c.trace.span("generation", "coordinator.propose_packet", claims=len(raw), dropped_uncited=c.dropped)
    rep = detect(c.trace.spans, {"claims": raw}, c.bundle.as_dict(), (c.decision.verdict.value if c.decision else ""), stage="pre")
    c.trace.span("review", "detector.pre", findings=[f.mode for f in rep.findings], details=[f"{f.mode}: {f.detail}" for f in rep.findings])
    return json.dumps({"kept": len(kept), "dropped": c.dropped, "findings": [f.mode for f in rep.findings]})


@function_tool
def request_approval(ctx: RunContextWrapper[Ctx]) -> str:
    """Post the packet to Slack with Approve & file / Hold buttons and wait for the human. Returns approved true/false."""
    c = ctx.context
    text = c.core._slack_text(c.bundle, c.decision, c.packet, c.dropped, detect(c.trace.spans, {"claims": c.packet["raw_claims"]}, c.bundle.as_dict(), c.decision.verdict.value, stage="pre"))
    slack = c.core.slack
    if hasattr(slack, "post_approval"):
        post = c.gate(Effect("slack", "chat.postMessage", c.core.channel), lambda: slack.post_approval(text, c.dispute_id))
    else:
        post = c.gate(Effect("slack", "chat.postMessage", c.core.channel), lambda: slack.post(c.core.channel, text))
    ok = bool(slack.await_approval(post["ts"]))
    c.trace.span("interaction", "slack.approval", approved=ok)
    c.approved = ok
    if ok:
        c.gate.state.approved.add(c.dispute_id)
    return json.dumps({"approved": ok})


@function_tool
def file_evidence(ctx: RunContextWrapper[Ctx]) -> str:
    """Stage the evidence with Stripe, read Stripe's CE3.0 validator, and submit only if qualified. One shot. Requires human approval."""
    c = ctx.context; b = c.bundle
    payload = c.core._evidence_payload(b, c.packet, c.have)
    call_used = c.call is not None and c.grounding is not None and c.grounding.usable and not c.grounding.denied and "yes" in (
        c.grounding.accepted.get("received"), c.grounding.accepted.get("recognises_charge"))
    if call_used:
        o = b.order or {}
        pdf = call.evidence_pdf(c.call, c.grounding, merchant=c.core.merchant, order_id=str(o.get("order_id", "")),
                                dispute_id=c.dispute_id, phone=(b.charge.get("billing_details") or {}).get("phone", ""))
        try:
            c.call_file = c.gate(Effect("stripe", "files.create", c.dispute_id, {"purpose": "dispute_evidence"}),
                                 lambda: c.core.stripe.upload_evidence(pdf, f"rebuttal-call-{c.call.call_id}.pdf"))
        except Blocked as e:
            return json.dumps({"blocked": str(e)})
        payload["customer_communication"] = c.call_file
        out = Path(__file__).resolve().parents[1] / "runs" / "evidence"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{c.trace.run_id}.pdf").write_bytes(pdf)
        c.trace.span("artifact", "evidence.call_document", target=c.dispute_id, file=c.call_file, bytes=len(pdf))
    try:
        staged = c.gate(Effect("stripe", "disputes.update", c.dispute_id, {"submit": False, "evidence": payload}),
                        lambda: c.core.stripe.update_dispute(c.dispute_id, payload, submit=False))
        c.ce3_status = staged.get("ce3_status") or c.core._ce3_status(staged)
        if b.dispute["reason"] == "fraudulent" and c.ce3_status and not c.ce3_status.startswith("qualified"):
            c.outcome = "held"
            c.trace.span("decision", "ce3.validator", status=c.ce3_status, action="held: Stripe says not qualified")
            return json.dumps({"outcome": "held", "ce3": c.ce3_status})
        final = c.gate(Effect("stripe", "disputes.update", c.dispute_id, {"submit": True, "evidence": payload}),
                       lambda: c.core.stripe.update_dispute(c.dispute_id, payload, submit=True))
        c.outcome = final.get("status", "under_review")
        if c.outcome == "won":
            c.recovered = b.dispute["amount"] + DISPUTE_FEE_CENTS
        return json.dumps({"outcome": c.outcome, "ce3": c.ce3_status})
    except Blocked as e:
        c.outcome = f"blocked:{e}"
        return json.dumps({"blocked": str(e)})
    except Exception as e:
        c.outcome = "held"; c.ce3_status = "rejected_by_validator"
        c.trace.span("effect", "stripe.disputes.update", target=c.dispute_id, result="ERROR", error=str(e)[:300])
        return json.dumps({"outcome": "held", "error": str(e)[:200]})


@function_tool
def notify_customer(ctx: RunContextWrapper[Ctx]) -> str:
    """Send the customer ONE notice: a Photon text if a phone is on file, otherwise an email."""
    c = ctx.context; b = c.bundle
    bd = b.charge.get("billing_details") or {}
    note = c.core._customer_note(b)
    try:
        if bd.get("phone") and c.core.photon is not None:
            try:
                c.gate(Effect("photon", "messages.send", c.dispute_id), lambda: c.core.photon.send(bd["phone"], note))
                return json.dumps({"sent": "photon"})
            except Blocked:
                raise
            except Exception as e:
                c.trace.span("effect", "photon.messages.send", target=c.dispute_id, result="ERROR", error=str(e)[:200])
        if bd.get("email"):
            c.gate(Effect("gmail", "messages.send", c.dispute_id), lambda: c.core.gmail.send(bd["email"], "About your recent dispute", note))
            return json.dumps({"sent": "gmail"})
        return json.dumps({"sent": "none"})
    except Blocked as e:
        return json.dumps({"blocked": str(e)})


@function_tool
def record_outcome(ctx: RunContextWrapper[Ctx]) -> str:
    """Append the outcome row to the ledger and post the summary line to Slack. Always the last step."""
    c = ctx.context; b = c.bundle
    if c.decision and c.decision.verdict == Verdict.CONCEDE:
        c.outcome = "conceded"
    amount = b.dispute["amount"]
    c.gate(Effect("sheets", "values.append", c.dispute_id), lambda: c.core.sheets.append_outcome({
        "dispute_id": c.dispute_id, "reason": b.dispute["reason"], "verdict": c.decision.verdict.value if c.decision else "", "outcome": c.outcome,
        "amount": amount / 100, "recovered": c.recovered / 100, "run_id": c.trace.run_id, "ce3": c.ce3_status or ""}))
    fee = "returned" if c.outcome == "won" else "at risk"
    summary = (f"{(c.decision.verdict.value if c.decision else 'hold').upper()} -> {c.outcome} | ${amount/100:.2f} at stake, ${c.recovered/100:.2f} recovered, "
               f"${DISPUTE_FEE_CENTS/100:.2f} fee {fee} | {c.gate.blocked} forbidden effects blocked | run {c.trace.run_id} | coordinator: gpt-6-astra")
    c.gate(Effect("slack", "chat.postMessage", c.core.channel), lambda: c.core.slack.post(c.core.channel, summary))
    c.trace.span("report", "slack.summary", text=summary)
    return summary


INSTRUCTIONS = """You are Rebuttal's coordinator for one chargeback dispute. Use the tools in this order and stop when done:
1. gather_evidence.
2. If the email thread is empty, the dispute reason is product_not_received, unrecognized or fraudulent, and a phone is on file: call_customer (once). Whatever it returns (used, not used, blocked or refused), continue with get_verdict.
3. get_verdict. Follow it exactly.
   - CONCEDE or HOLD: record_outcome, then stop. Do not request approval, do not file.
   - SUBMIT: continue.
4. propose_packet with 3 to 6 short claims that rebut the dispute reason. Every claim cites exactly one fact id. Never invent tracking numbers, dates, names or amounts.
5. request_approval. If not approved: record_outcome, stop.
6. file_evidence. 7. notify_customer. 8. record_outcome. Then stop.
Never call a tool twice. Never skip record_outcome."""


def build(core: Rebuttal, model: str | None = None) -> Agent[Ctx]:
    return Agent[Ctx](name="Rebuttal coordinator", instructions=INSTRUCTIONS, model=model or os.environ.get("REBUTTAL_MODEL", "gpt-6-astra"),
                      tools=[gather_evidence, call_customer, get_verdict, propose_packet, request_approval, file_evidence, notify_customer, record_outcome])


async def run(core: Rebuttal, dispute_id: str, model: str | None = None, fault: str | None = None,
              live_call_intent: bool = False, call_allowlist: list[str] | set[str] | None = None) -> Ctx:
    trace = Trace(uuid.uuid4().hex[:10], dispute_id)
    state = GateState(live_call_intent=live_call_intent, call_allowlist=set(call_allowlist or []))
    ctx = Ctx(core=core, trace=trace, gate=Gate(trace, state), dispute_id=dispute_id, fault=fault)
    agent = build(core, model)
    result = await Runner.run(agent, f"Handle dispute {dispute_id}.", context=ctx, max_turns=16)
    tokens = sum(int(getattr(getattr(r, "usage", None), "total_tokens", 0) or 0) for r in (result.raw_responses or []))
    trace.span("generation", "coordinator.run", turns=len(result.raw_responses or []), tokens=tokens)
    rep = detect(trace.spans, {"claims": ctx.packet.get("raw_claims", [])}, ctx.bundle.as_dict() if ctx.bundle else {"record_ids": [], "facts": {}},
                 ctx.decision.verdict.value if ctx.decision else "", stage="post")
    trace.span("review", "detector.post", findings=[f.mode for f in rep.findings], details=[f"{f.mode}: {f.detail}" for f in rep.findings])
    trace.dump()
    return ctx
