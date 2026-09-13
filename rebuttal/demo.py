"""Live demo against the real apps.

    python -m rebuttal.demo seed      # creates the customer, two prior charges, the disputed charge, ledger rows, email thread
    python -m rebuttal.demo run       # runs the agent on the newest open dispute; approve in Slack
    python -m rebuttal.demo run --dispute du_xxx

All money is Stripe test mode. The dispute is created by Stripe's CE3.0 test card.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from .agent import Rebuttal
from .clients import GmailClient, SheetsClient, SlackClient, StripeClient, google_creds
from .model import AstraModel

CUSTOMER_EMAIL = os.environ.get("DEMO_CUSTOMER_EMAIL", "ndivij2004@gmail.com")
SHIP_TO = "12 Ridge Rd, Boulder, CO, 80302"
IDENT = {"ip": "146.196.38.93", "device": "dev_a1f9c3e7b2d4f6a8c0e2b4d6", "account_id": "cust_7781", "ship_to": SHIP_TO}


def seed(args) -> None:
    import stripe
    st = StripeClient()
    s = st.s
    cust = s.Customer.create(email=CUSTOMER_EMAIL, name="Jordan Lee", address={"line1": "12 Ridge Rd", "city": "Boulder", "state": "CO", "postal_code": "80302", "country": "US"})
    print("customer", cust.id)
    priors = []
    for oid, amt, age in (("0910", 4500, 150), ("0872", 6100, 240)):
        pi = s.PaymentIntent.create(amount=amt, currency="usd", customer=cust.id, payment_method="pm_card_visa", confirm=True,
                                    payment_method_types=["card"], description=f"Order {oid} - prior order",
                                    metadata={"order_id": oid, "age_days_override": str(age), **IDENT})
        priors.append(pi.latest_charge)
        print("prior charge", pi.latest_charge, f"({age} days old by metadata)")
    pi = s.PaymentIntent.create(amount=8900, currency="usd", customer=cust.id, payment_method="pm_card_createCe3EligibleDispute", confirm=True,
                                payment_method_types=["card"], description="Order 1042 - trail shoes",
                                metadata={"order_id": "1042", **IDENT})
    charge = pi.latest_charge
    time.sleep(2)
    du = s.Charge.retrieve(charge).dispute
    print("disputed charge", charge, "->", du)

    creds = google_creds()
    sheets = SheetsClient(creds=creds)
    sheets.seed_orders([
        {"order_id": "1042", "items": "Trail shoes x1", "kind": "physical", "ship_date": "2026-08-30", "carrier": "UPS", "ship_to": SHIP_TO,
         "tracking": "1Z999AA10123456784", "tracking_status": "delivered", "delivered_at": "2026-09-02", "signature_image": True},
        {"order_id": "0910", "items": "Running socks x3", "kind": "physical", "ship_date": "2026-04-14", "carrier": "UPS", "ship_to": SHIP_TO,
         "tracking": "1Z999AA10123456701", "tracking_status": "delivered", "delivered_at": "2026-04-17", "signature_image": False},
        {"order_id": "0872", "items": "Rain shell x1", "kind": "physical", "ship_date": "2026-01-16", "carrier": "UPS", "ship_to": SHIP_TO,
         "tracking": "1Z999AA10123456655", "tracking_status": "delivered", "delivered_at": "2026-01-19", "signature_image": True},
    ])
    print("ledger", sheets.url)
    gm = GmailClient(creds=creds)
    gm.send(CUSTOMER_EMAIL, "Re: Order 1042", "Got the shoes, thanks! Fit is perfect. - Jordan")
    print("email thread seeded to", CUSTOMER_EMAIL)
    env = open(".env", "a")
    env.write(f"SHEET_ID={sheets.id}\nDEMO_DISPUTE={du}\n")
    env.close()
    print("\nseeded. run:  python -m rebuttal.demo run")


def run(args) -> None:
    st = StripeClient()
    dispute_id = args.dispute or os.environ.get("DEMO_DISPUTE")
    if not dispute_id:
        d = st.s.Dispute.list(limit=1).data[0]
        dispute_id = d.id
    creds = google_creds()
    agent = Rebuttal(st, GmailClient(creds=creds), SheetsClient(creds=creds), SlackClient(), AstraModel())
    print("running on", dispute_id, "-> approve in Slack", agent.slack.channel)
    r = asyncio.run(agent.run(dispute_id, approve=args.auto_approve or None))
    print(f"\nverdict {r.verdict.value} -> {r.outcome} | ce3 {r.ce3_status} | ${r.amount_cents/100:.2f} at stake, ${r.recovered_cents/100:.2f} recovered | {r.blocked} forbidden effects blocked")
    for f in r.report.findings:
        print("  flag:", f.mode, "-", f.detail)
    print("trace: runs/" + r.run_id + ".json")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    r = sub.add_parser("run")
    r.add_argument("--dispute")
    r.add_argument("--auto-approve", action="store_true", help="skip the Slack click (for CI, not for the demo)")
    args = ap.parse_args()
    {"seed": seed, "run": run}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
