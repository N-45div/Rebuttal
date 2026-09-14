"""A stateful twin of the CALL-E Developer API: calls.create, calls.get and calls.list_events, with idempotency.

The scenario scripts the person who answers. By default the caller follows the Rebuttal script: it
discloses, asks the two questions and hangs up, and the customer's turns come from the scripted
answers. A scenario can override the turns so CALL-E's structured result disagrees with what was
said, drop the disclosure, fail the call, or lower the confidence. Payload shapes mirror the live API.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from . import Twin

_SAY = {
    ("received", "yes"): "Yes, I got them last week.",
    ("received", "no"): "No, nothing arrived.",
    ("recognises_charge", "yes"): "Yes, that charge is mine.",
    ("recognises_charge", "no"): "No, it is not mine.",
}


class _Calls:
    def __init__(self, twin: "CalleTwin"):
        self._t = twin

    def create(self, **kw: Any) -> dict[str, Any]:
        return self._t._create(**kw)

    def get(self, call_id: str) -> dict[str, Any]:
        return self._t._get(call_id)

    def list_events(self, call_id: str, *, cursor: str | None = None, limit: int | None = None) -> dict[str, Any]:
        return self._t._events(call_id)

    def wait_for_result(self, call_id: str, **_: Any) -> dict[str, Any]:
        return self._t._get(call_id)


class CalleTwin(Twin):
    app = "calle"

    def reset(self) -> None:
        super().reset()
        self.by_key: dict[str, str] = {}
        self.store: dict[str, dict[str, Any]] = {}

    @property
    def live(self) -> bool:
        return bool(self.state.get("live"))

    @property
    def calls(self) -> _Calls:
        return _Calls(self)

    def _create(self, *, task: str, recipients: list[dict[str, Any]] | None = None, recipient: dict[str, Any] | None = None,
                result_schema: dict[str, Any] | None = None, recipient_result_schema: dict[str, Any] | None = None,
                metadata: dict[str, Any] | None = None, webhook_url: str | None = None,
                idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key and idempotency_key in self.by_key:
            cid = self.by_key[idempotency_key]
            return self._rec("calls.create", copy.deepcopy(self.store[cid]["created"]), idempotency_key=idempotency_key, replay=True)
        people = recipients or ([recipient] if recipient else [])
        phone = ((people[0] if people else {}).get("phones") or [None])[0]
        cid = f"call_twin{len(self.store) + 1:03d}"
        created = {"id": cid, "object": "call_task", "status": "queued", "task": task, "metadata": dict(metadata or {})}
        self.store[cid] = {"created": created, "phone": phone, "task": task, "metadata": dict(metadata or {})}
        if idempotency_key:
            self.by_key[idempotency_key] = cid
        self._effect("call.placed", to=phone, call_id=cid)
        return self._rec("calls.create", copy.deepcopy(created), phone=phone, idempotency_key=idempotency_key)

    def _script(self, cid: str) -> dict[str, Any]:
        s = self.store[cid]
        ans = (self.state.get("answers") or {}).get(s["phone"])
        if ans is None:
            return {"status": "failed", "task_completed": False, "turns": [], "result": None, "confidence": None, "failure": "no_answer"}
        received = ans.get("received", "unknown")
        charge = ans.get("recognises_charge", "unknown")
        turns = ans.get("turns")
        if turns is None:
            m = re.search(r'Start the call by saying: "([^"]+)"', s["task"])
            opening = m.group(1) if m else "Hello."
            if ans.get("disclose") is False:
                opening = opening.replace("this is an automated assistant calling", "I'm calling")
            turns = [
                {"offset_seconds": 0, "speaker": "bot", "text": opening},
                {"offset_seconds": 7, "speaker": "user", "text": "Okay."},
                {"offset_seconds": 8, "speaker": "bot", "text": "Did you receive the order?"},
                {"offset_seconds": 11, "speaker": "user", "text": _SAY.get(("received", received), "Sorry, who is this?")},
                {"offset_seconds": 13, "speaker": "bot", "text": "Do you recognise the charge for that order?"},
                {"offset_seconds": 16, "speaker": "user", "text": _SAY.get(("recognises_charge", charge), "I have to go.")},
                {"offset_seconds": 18, "speaker": "bot", "text": "Thank you. Goodbye."},
            ]
        return {"status": ans.get("status", "completed"), "task_completed": ans.get("task_completed", True), "turns": turns,
                "result": {"received": received, "recognises_charge": charge, "purchaser": ans.get("purchaser", "cardholder"),
                           "declined_to_talk": ans.get("declined_to_talk", "no")},
                "confidence": ans.get("confidence", 0.93), "failure": None}

    def _get(self, call_id: str) -> dict[str, Any]:
        s, sc = self.store[call_id], self._script(call_id)
        attempt = {"id": f"att_{call_id}", "phone": s["phone"], "status": sc["status"], "started_at": "2026-09-14T16:00:05Z",
                   "completed_at": "2026-09-14T16:00:25Z", "summary": "", "transcript_turns": sc["turns"],
                   "provider_call_id": "twin", "failure_code": sc["failure"], "failure_message": None}
        payload = {"id": call_id, "object": "call_task", "status": sc["status"], "task": s["task"],
                   "recipients": [{"id": f"rcp_{call_id}", "phones": [s["phone"]], "status": sc["status"], "attempts": [attempt]}],
                   "structured_result": sc["result"], "summary": "", "task_completed": sc["task_completed"],
                   "completion_confidence": {"score": sc["confidence"], "label": "high"} if sc["confidence"] is not None else None,
                   "evidence": [], "metadata": s["metadata"], "failure_code": sc["failure"], "failure_message": None,
                   "created_at": "2026-09-14T16:00:00Z", "completed_at": "2026-09-14T16:00:30Z"}
        return self._rec("calls.get", copy.deepcopy(payload), call_id=call_id)

    def _events(self, call_id: str) -> dict[str, Any]:
        sc = self._script(call_id)
        msgs = ["run_call started.", "calling task created.", "Call is ringing."]
        msgs += ["Call answered.", "Call completed."] if sc["status"] == "completed" else ["No answer.", "Call failed."]
        data = [{"id": f"evt_{call_id}_{i}", "type": "call.completed" if i == len(msgs) - 1 else "call.in_progress",
                 "call_id": call_id, "level": "info", "status": sc["status"], "message": m, "details": {}}
                for i, m in enumerate(msgs)]
        return self._rec("calls.list_events", {"object": "list", "data": data, "next_cursor": None}, call_id=call_id)
