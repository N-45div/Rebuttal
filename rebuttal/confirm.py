"""Place one confirmation call and see exactly what Rebuttal would file. No Stripe, Slack or Google needed.

    python -m rebuttal.confirm                                   # no call: the CALL-E twin answers
    python -m rebuttal.confirm --live --to +1... --i-have-consent  # one real CALL-E call

A live call needs CALLE_API_KEY, the destination listed in REBUTTAL_CALL_ALLOWLIST, the person's
agreement to be called, and local calling hours at the destination. A submitted call cannot be
cancelled through the public CALL-E API, so every check runs before the create.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import call

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="place a real CALL-E call (default: the twin answers, nothing rings)")
    ap.add_argument("--to", default="+12125550101", help="E.164 destination (default is a reserved fictional number)")
    ap.add_argument("--i-have-consent", action="store_true", help="confirm the person at this number agreed to be called")
    ap.add_argument("--merchant", default=os.environ.get("MERCHANT_NAME", "Ridge Outfitters"))
    ap.add_argument("--order", default="1042")
    ap.add_argument("--items", default="Trail shoes x1")
    ap.add_argument("--amount", default="$89.00")
    ap.add_argument("--dispute", default="du_confirm_demo", help="dispute id; also the idempotency key for the call")
    args = ap.parse_args(argv)

    task_args = {"merchant": args.merchant, "order_id": args.order, "items": args.items, "amount": args.amount}
    print(f"destination   {call.mask(args.to)}")
    print(f"script        {call.TEMPLATE_VERSION}: {call.disclosure(args.merchant, args.order)}")
    print(f"result fields {', '.join(call.RESULT_SCHEMA['required'])}")
    print(f"idempotency   {call.idempotency_key(args.dispute)}")

    if args.live:
        problems = []
        if not os.environ.get("CALLE_API_KEY"):
            problems.append("CALLE_API_KEY is not set")
        if not call.E164.match(args.to):
            problems.append("--to must be an E.164 number")
        if not args.i_have_consent:
            problems.append("pass --i-have-consent to confirm the person at this number agreed to be called")
        if not call.authorized(args.to, os.environ.get("REBUTTAL_CALL_ALLOWLIST")):
            problems.append(f"{call.mask(args.to)} is not listed in REBUTTAL_CALL_ALLOWLIST")
        ok, why = call.local_hours_ok(args.to)
        if not ok:
            problems.append(why)
        if problems:
            print("\nNot calling:")
            for p in problems:
                print(f"  - {p}")
            return 2
        from calle import CalleClient
        kw = {"api_key": os.environ["CALLE_API_KEY"]}
        if os.environ.get("CALLE_BASE_URL"):
            kw["base_url"] = os.environ["CALLE_BASE_URL"]
        client = CalleClient(**kw)
        print("\nmode          LIVE: a real phone will ring. A submitted call cannot be cancelled through the public API.")
    else:
        from .twins.calle import CalleTwin
        client = CalleTwin({"answers": {args.to: {"received": "yes", "recognises_charge": "yes", "purchaser": "cardholder",
                                                 "declined_to_talk": "no"}}})
        print("\nmode          dry run: the CALL-E twin answers, nothing rings")

    created = call.place(client, dispute_id=args.dispute, phone=args.to, **task_args)
    call_id = created.get("id") or created.get("call_id", "")
    print(f"call          {call_id} ({created.get('status', 'created')})\n")
    rec = call.follow(client, call_id,
                      on_event=lambda e: print(f"  event     {e.get('message') or e.get('type')}"),
                      on_turn=lambda t: print(f"  {call._clock(t.get('offset_seconds'))}     "
                                              f"{'caller  ' if call._is_caller(t) else 'customer'}  {t.get('text', '')}"))
    g = call.ground(rec, args.merchant)
    print("\nchecks")
    for line in g.lines():
        print(f"  {line}")
    print(f"\nCALL-E reported   received={g.reported.get('received')}  recognises_charge={g.reported.get('recognises_charge')}")
    print(f"accepted          received={g.accepted['received']}  recognises_charge={g.accepted['recognises_charge']}")
    out = ROOT / "runs" / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / f"{call_id}.pdf"
    pdf.write_bytes(call.evidence_pdf(rec, g, merchant=args.merchant, order_id=args.order, dispute_id=args.dispute, phone=args.to))
    used = g.usable and "yes" in (g.accepted["received"], g.accepted["recognises_charge"])
    print(f"document          {pdf}")
    print(f"decision          {'would be filed as customer communication' if used else ('stops the filing' if g.denied else 'would not be filed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
