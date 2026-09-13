"""The writer model. GPT-6 Astra in production, a deterministic fake for the eval suite.

Astra is used for exactly one thing: turning cited facts into the rebuttal
narrative. It never chooses the verdict (policy.py does) and it never touches
an external app (gate.py does). Output is JSON claims, each with a source id.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from typing import Any, Protocol

from pydantic import BaseModel


class Model(Protocol):
    def write(self, facts: list[dict[str, Any]], reason: str, verdict: str) -> list[dict[str, str]]: ...


SYSTEM = (
    "You write chargeback rebuttals for a merchant. You are given FACTS, each with an id. "
    "Write 3 to 6 short claims that rebut the dispute reason. Every claim MUST cite exactly one fact id "
    "in the field 'source'. Do not invent tracking numbers, dates, names or amounts. "
    "Return the claims as structured output."
)


class Claim(BaseModel):
    text: str
    source: str


class Claims(BaseModel):
    claims: list[Claim]


class AstraModel:
    """The writer, as an OpenAI Agents SDK agent on GPT-6 Astra with a typed output.

    One agent, no tools: it may only turn cited facts into claims. It cannot reach an
    external app (the gate does that) and it cannot choose the verdict (the policy table does).
    """

    def __init__(self, model: str | None = None):
        from agents import Agent
        self.model = model or os.environ.get("REBUTTAL_MODEL", "gpt-6-astra")
        self.agent = Agent(name="Rebuttal writer", instructions=SYSTEM, model=self.model, output_type=Claims)
        self.calls = 0
        self.tokens = 0

    def write(self, facts: list[dict[str, Any]], reason: str, verdict: str) -> list[dict[str, str]]:
        from agents import Runner
        user = f"Dispute reason: {reason}. Verdict already decided: {verdict}." + chr(10) + "FACTS:" + chr(10) + chr(10).join(
            f"- [{f['id']}] {f['text']}" for f in facts
        )
        result = Runner.run_sync(self.agent, user, max_turns=1)
        self.calls += 1
        for r in getattr(result, "raw_responses", []) or []:
            u = getattr(r, "usage", None)
            if u is not None:
                self.tokens += int(getattr(u, "total_tokens", 0) or 0)
        out = result.final_output
        claims = out.claims if isinstance(out, Claims) else Claims.model_validate(out).claims
        return [{"text": c.text, "source": c.source} for c in claims]


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
