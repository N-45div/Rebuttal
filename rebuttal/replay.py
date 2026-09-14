"""Export a confirmation call as a replay file for the site and the film. Viewing it needs no credentials.

    python -m rebuttal.replay --trace runs/<run_id>.json --out web/public/calls/<name>.json
    python -m rebuttal.replay --fixture tests/fixtures/calle_call_confirmed.json --out web/public/calls/<name>.json
    python -m rebuttal.replay --call call_... --out web/public/calls/<name>.json      # fetch from CALL-E

A trace carries the whole run: the call's events and transcript, the checks, what was filed and the
outcome. A fixture or a live fetch carries the call alone and is grounded here. Numbers are masked.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import call

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
PHONE = re.compile(r"\+[1-9]\d{7,14}")


def _scrub(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_scrub(x) for x in o]
    if isinstance(o, str):
        return PHONE.sub(lambda m: call.mask(m.group(0)), o)
    return o


def _speaker(t: dict[str, Any]) -> str:
    return "caller" if call._is_caller(t) else "customer"


def _offsets(events: list[dict[str, Any]], started: str | None) -> list[dict[str, Any]]:
    def ts(s: str | None) -> datetime | None:
        try:
            return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    t0 = ts(started)
    out = []
    for e in events:
        at = ts(e.get("created_at"))
        out.append({"message": e.get("message") or e.get("type"), "type": e.get("type"),
                    "offset": round((at - t0).total_seconds(), 1) if at and t0 else None})
    return out


def _decision(usable: bool, accepted: dict[str, Any], denied: bool) -> str:
    if usable and "yes" in (accepted.get("received"), accepted.get("recognises_charge")):
        return "used as evidence"
    return "stops the filing" if denied else "not used"


def from_record(rec: call.CallRecord, g: call.Grounding, *, title: str, source: str, dispute: dict[str, Any],
                phone: str = "", outcome: dict[str, Any] | None = None) -> dict[str, Any]:
    return _scrub({
        "title": title, "source": source, "dispute": dispute,
        "call": {"id": rec.call_id, "status": rec.status, "confidence": rec.confidence, "duration_seconds": rec.duration_seconds,
                 "started_at": rec.started_at, "completed_at": rec.completed_at, "to": call.mask(phone),
                 "script": call.TEMPLATE_VERSION, "idempotency_key": call.idempotency_key(dispute.get("id", ""))},
        "events": _offsets(rec.events, rec.started_at),
        "turns": [{"offset_seconds": t.get("offset_seconds"), "speaker": _speaker(t), "text": t.get("text", "")} for t in rec.turns],
        "reported": g.reported, "accepted": g.accepted, "usable": g.usable, "denied": g.denied,
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail, "quote": c.quote, "offset": c.offset} for c in g.checks],
        "decision": _decision(g.usable, g.accepted, g.denied), "outcome": outcome,
    })


def from_trace(path: Path, title: str) -> dict[str, Any]:
    t = json.loads(path.read_text(encoding="utf-8"))
    spans = t.get("spans", [])
    gs = next((s for s in spans if s.get("name") == "calle.grounding"), None)
    if gs is None:
        raise SystemExit(f"{path} has no call in it")
    dec = next((s for s in spans if s.get("name") == "policy.decide"), {})
    rep = next((s for s in spans if s.get("kind") == "report"), {})
    doc = next((s for s in spans if s.get("name") == "evidence.call_document"), {})
    appr = next((s for s in spans if s.get("name") == "slack.approval"), {})
    text = rep.get("text", "")
    m = re.search(r"->\s*(\w+)", text)
    rec_amt = re.search(r"\$([\d.]+) recovered", text)
    checks = [call.Check(**c) for c in gs.get("checks", [])]
    g = call.Grounding(reported=gs.get("reported", {}), accepted=gs.get("accepted", {}), checks=checks,
                       usable=gs.get("usable", False), denied=gs.get("denied", False))
    events = [{"message": s.get("message"), "type": s.get("type"), "offset": s.get("t")} for s in spans if s.get("name") == "calle.event"]
    rec = call.CallRecord(call_id=gs.get("call_id", ""), status=gs.get("result", ""), task_completed=None,
                          confidence=gs.get("confidence"), result=gs.get("reported", {}), summary="", evidence=[],
                          turns=gs.get("transcript", []))
    out = from_record(rec, g, title=title, source="live run trace",
                      dispute={"id": t.get("dispute_id"), "reason": dec.get("reason_code")},
                      outcome={"verdict": (dec.get("verdict") or "").upper(), "status": m.group(1) if m else None,
                               "recovered": f"${rec_amt.group(1)}" if rec_amt else None, "file": doc.get("file"),
                               "approved": appr.get("approved"), "report": text, "run_id": t.get("run_id")})
    out["call"]["duration_seconds"] = gs.get("duration")
    out["events"] = _scrub(events)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--trace")
    src.add_argument("--fixture")
    src.add_argument("--call")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="The confirmation call")
    ap.add_argument("--merchant", default=os.environ.get("MERCHANT_NAME", "Ridge Outfitters"))
    ap.add_argument("--dispute", default="")
    ap.add_argument("--reason", default="")
    args = ap.parse_args(argv)

    if args.trace:
        data = from_trace(Path(args.trace), args.title)
    else:
        if args.fixture:
            raw = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
            payload, events = raw["call"], (raw.get("events") or {}).get("data", [])
            source = "saved CALL-E payload"
        else:
            from calle import CalleClient
            kw = {"api_key": os.environ["CALLE_API_KEY"]}
            if os.environ.get("CALLE_BASE_URL"):
                kw["base_url"] = os.environ["CALLE_BASE_URL"]
            client = CalleClient(**kw)
            payload, events = client.calls.get(args.call), client.calls.list_events(args.call, limit=100).get("data", [])
            source = "live CALL-E call"
        rec = call.record_from(payload, events)
        phone = next((p for r in payload.get("recipients") or [] for p in r.get("phones") or []), "")
        data = from_record(rec, call.ground(rec, args.merchant), title=args.title, source=source,
                           dispute={"id": args.dispute, "reason": args.reason}, phone=phone)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    leaked = PHONE.findall(out.read_text(encoding="utf-8"))
    print(f"wrote {out} ({len(data['turns'])} turns, {len(data['checks'])} checks, decision: {data['decision']})"
          + (f"  WARNING unmasked: {leaked}" if leaked else ""))
    return 1 if leaked else 0


if __name__ == "__main__":
    sys.exit(main())
