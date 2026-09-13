"""The writer model. GPT-6 Astra in production, a deterministic fake for the eval suite.

Astra is used for exactly one thing: turning cited facts into the rebuttal
narrative. It never chooses the verdict (policy.py does) and it never touches
an external app (gate.py does). Output is JSON claims, each with a source id.
"""
from __future__ import annotations

import json
import os
from typing import Any, Protocol


class Model(Protocol):
    def write(self, facts: list[dict[str, Any]], reason: str, verdict: str) -> list[dict[str, str]]: ...


SYSTEM = (
    "You write chargeback rebuttals for a merchant. You are given FACTS, each with an id. "
    "Write 3 to 6 short claims that rebut the dispute reason. Every claim MUST cite exactly one fact id "
    "in the field 'source'. Do not invent tracking numbers, dates, names or amounts. "
    "Return only JSON: {\"claims\": [{\"text\": str, \"source\": str}]}"
)


class AstraModel:
    def __init__(self, model: str | None = None):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model or os.environ.get("REBUTTAL_MODEL", "gpt-6-astra")
        self.calls = 0
        self.tokens = 0

    def write(self, facts: list[dict[str, Any]], reason: str, verdict: str) -> list[dict[str, str]]:
        user = f"Dispute reason: {reason}. Verdict already decided: {verdict}.\nFACTS:\n" + "\n".join(
            f"- [{f['id']}] {f['text']}" for f in facts
        )
        try:
            resp = self.client.responses.create(
                model=self.model, instructions=SYSTEM, input=user, max_output_tokens=500,
            )
            text = resp.output_text
            usage = getattr(resp, "usage", None)
        except Exception:
            resp = self.client.chat.completions.create(
                model=self.model, max_tokens=500,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            )
            text = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)
        self.calls += 1
        if usage is not None:
            self.tokens += int(getattr(usage, "total_tokens", 0) or 0)
        text = text.strip().strip("`")
        if text.startswith("json"):
            text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start:end + 1]) if start >= 0 else {"claims": []}
        return [{"text": str(c.get("text", "")), "source": str(c.get("source", ""))} for c in data.get("claims", [])]


class FakeModel:
    """Deterministic: one claim per fact, always cited. Used by the scenario suite."""
    def __init__(self, misbehave: str | None = None):
        self.misbehave = misbehave  # "uncited" | "invent_tracking" | "wrong_source"

    def write(self, facts: list[dict[str, Any]], reason: str, verdict: str) -> list[dict[str, str]]:
        claims = [{"text": f["text"], "source": f["id"]} for f in facts]
        if self.misbehave == "uncited" and claims:
            claims[0]["source"] = ""
        if self.misbehave == "invent_tracking":
            claims.append({"text": "Delivered under tracking 1Z999FAKE0000000001", "source": facts[0]["id"] if facts else ""})
        if self.misbehave == "wrong_source" and claims:
            claims[0]["source"] = "rec_does_not_exist"
        return claims
