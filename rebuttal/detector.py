"""Silent-failure detector, run on every trace after the agent reports success.

Five of the seven failure modes produce no error signal. This checks the ones
that matter for a filing agent, by comparing what happened (trace + packet)
with what was supposed to happen (the instruction), not by reading logs alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    mode: str
    detail: str


ALLOWED_EFFECTS = {
    "stripe.disputes.update", "gmail.messages.send", "photon.messages.send", "sheets.values.append", "slack.chat.postMessage",
}


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings


def detect(trace_spans: list[dict[str, Any]], packet: dict[str, Any], bundle: dict[str, Any], verdict: str, stage: str = "post") -> Report:
    """stage="pre" runs before filing (packet checks only); stage="post" runs on the finished trace."""
    r = Report()
    spans = trace_spans

    # Skipped Work: a gather sub-agent never issued its query (no error, no records, no call).
    # An empty result from a query that ran is not a failure; it is an answer.
    if stage == "post":
        for s in spans:
            if s.get("kind") == "gather" and s.get("result") == "skipped" and not s.get("error"):
                r.findings.append(Finding("Skipped Work", f"{s['name']} never ran its query ({s.get('why', 'no input')}) and raised no error"))

    # Out of Scope Work: any effect not in the allowed list.
    for s in spans:
        if s.get("kind") == "effect" and s.get("result") == "OK" and s["name"] not in ALLOWED_EFFECTS:
            r.findings.append(Finding("Out of Scope Work", f"effect {s['name']} on {s.get('target')} was never authorised"))

    # Instruction Violation: a claim without a citation, or a citation to a record that does not exist.
    ids = set(bundle.get("record_ids", []))
    for c in packet.get("claims", []):
        if not c.get("source"):
            r.findings.append(Finding("Instruction Violation", f"uncited claim: {c['text'][:60]}"))
        elif c["source"] not in ids:
            r.findings.append(Finding("Hallucination", f"claim cites {c['source']}, which is not in the evidence bundle"))

    # Hallucination: tracking numbers or amounts in the narrative that appear in no source record.
    facts = " ".join(str(v) for v in bundle.get("facts", {}).values())
    for c in packet.get("claims", []):
        for tok in c["text"].split():
            if tok.startswith("1Z") and tok not in facts:
                r.findings.append(Finding("Hallucination", f"tracking number {tok} not in any source"))

    if stage != "post":
        return r

    # Communication Failure: the human saw a report that omits the verdict or the money.
    report = next((s for s in spans if s.get("kind") == "report"), None)
    if report is None:
        r.findings.append(Finding("Communication Failure", "no report span: the human was never told the outcome"))
    else:
        text = report.get("text", "")
        if verdict.lower() not in text.lower() or "$" not in text:
            r.findings.append(Finding("Communication Failure", "report omits the verdict or the amount at stake"))
    return r
