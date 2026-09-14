"""Real clients for the four apps. Same interface as the twins, so the agent code is identical."""
from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/spreadsheets"]
ROOT = Path(__file__).resolve().parents[1]


# ---------------- Stripe ----------------
def _plain(obj: Any) -> dict[str, Any]:
    return json.loads(str(obj))


class StripeClient:
    app = "stripe"

    def __init__(self):
        import stripe
        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        self.s = stripe

    def dispute(self, dispute_id: str) -> dict[str, Any]:
        return _plain(self.s.Dispute.retrieve(dispute_id))

    def charge(self, charge_id: str) -> dict[str, Any]:
        c = _plain(self.s.Charge.retrieve(charge_id))
        card = (c.get("payment_method_details") or {}).get("card") or {}
        checks = card.get("checks") or {}
        c["fingerprint"] = card.get("fingerprint")
        c["created_iso"] = datetime.fromtimestamp(c["created"], tz=timezone.utc).date().isoformat()
        c["avs"] = checks.get("address_postal_code_check") or "n/a"
        c["cvc"] = checks.get("cvc_check") or "n/a"
        md = c.get("metadata") or {}
        # identifiers the merchant's checkout stamps on the charge
        c["ip"] = md.get("ip")
        c["device"] = md.get("device")
        c["account_id"] = md.get("account_id")
        bd = c.get("billing_details") or {}
        if not bd.get("email") and c.get("customer"):  # email lives on the customer, not the charge
            cust = _plain(self.s.Customer.retrieve(c["customer"]))
            bd["email"] = cust.get("email")
            bd["phone"] = bd.get("phone") or cust.get("phone")
            c["billing_details"] = bd
            if not bd.get("address") and cust.get("address"):
                bd["address"] = cust["address"]
        addr = bd.get("address") or {}
        c["billing_address"] = ", ".join(x for x in [addr.get("line1"), addr.get("city"), addr.get("state"), addr.get("postal_code")] if x) or None
        return c

    def charges_for_fingerprint(self, fingerprint: str, customer: str | None = None) -> list[dict[str, Any]]:
        """Prior charges on the same card; falls back to the same customer (test cards share no fingerprint)."""
        res = [_plain(c) for c in self.s.Charge.search(query=f"payment_method_details.card.fingerprint:'{fingerprint}'", limit=10).auto_paging_iter()]
        if len([c for c in res if not c.get("disputed")]) < 2 and customer:
            res = [_plain(c) for c in self.s.Charge.list(customer=customer, limit=20).auto_paging_iter()]
        now = time.time()
        out = []
        for c in res:
            if c.get("disputed"):
                continue
            md = c.get("metadata") or {}
            out.append({"id": c["id"], "amount": c["amount"], "created_iso": datetime.fromtimestamp(c["created"], tz=timezone.utc).date().isoformat(),
                        "age_days": int(md.get("age_days_override") or (now - c["created"]) // 86400),
                        "ip": md.get("ip"), "device": md.get("device"), "account": md.get("account_id"),
                        "email": (c.get("billing_details") or {}).get("email"), "ship_to": md.get("ship_to"),
                        "ship_to_struct": _addr_struct(md.get("ship_to")), "items": c.get("description") or "prior order"})
        return out

    def upload_evidence(self, data: bytes, filename: str) -> str:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(data)
            path = fh.name
        try:
            with open(path, "rb") as fh:
                return self.s.File.create(purpose="dispute_evidence", file=fh).id
        finally:
            os.remove(path)

    def update_dispute(self, dispute_id: str, evidence: dict[str, Any], submit: bool) -> dict[str, Any]:
        # TEST MODE ONLY: Stripe resolves a test dispute by the literal marker "winning_evidence" / "losing_evidence".
        # The CE3.0 validator is real; the won/lost verdict in test mode is not. README says so.
        marker = os.environ.get("STRIPE_TEST_OUTCOME_MARKER")
        if submit and marker and self.s.api_key.startswith("sk_test_"):
            narrative = evidence.get("uncategorized_text", "")
            evidence = {**evidence, "uncategorized_text": marker,
                        "product_description": ((evidence.get("product_description") or "") + chr(10) + narrative).strip()}
        d = _plain(self.s.Dispute.modify(dispute_id, evidence=evidence, submit=submit))
        if submit:
            for _ in range(10):  # test mode closes within a few seconds
                if d.get("status") in ("won", "lost"):
                    break
                time.sleep(1)
                d = _plain(self.s.Dispute.retrieve(dispute_id))
        return d


def _addr_struct(s: str | None) -> dict[str, str] | None:
    # "12 Ridge Rd, Boulder, CO, 80302" -> struct
    if not s:
        return None
    parts = [p.strip() for p in s.split(",")]
    if len(parts) < 4:
        return None
    return {"line1": parts[0], "city": parts[1], "state": parts[2], "postal_code": parts[3], "country": "US"}


# ---------------- Google (Gmail + Sheets) ----------------
def google_creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token = ROOT / "token.json"
    creds = Credentials.from_authorized_user_file(str(token), GOOGLE_SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / "credentials.json"), GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
        token.write_text(creds.to_json())
    return creds


class GmailClient:
    app = "gmail"

    def __init__(self, creds=None):
        from googleapiclient.discovery import build
        self.svc = build("gmail", "v1", credentials=creds or google_creds(), cache_discovery=False)
        self.me = self.svc.users().getProfile(userId="me").execute()["emailAddress"]

    def search(self, email: str) -> list[dict[str, Any]]:
        res = self.svc.users().messages().list(userId="me", q=f"from:{email} OR to:{email}", maxResults=5).execute()
        out = []
        for m in res.get("messages", []):
            full = self.svc.users().messages().get(userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "To", "Date", "Subject"]).execute()
            h = {x["name"]: x["value"] for x in full["payload"]["headers"]}
            out.append({"id": m["id"], "from": h.get("From", ""), "to": h.get("To", ""), "date": h.get("Date", "")[:16], "snippet": full.get("snippet", "")})
        return out

    def send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        msg = MIMEText(body)
        msg["to"], msg["from"], msg["subject"] = to, self.me, subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return self.svc.users().messages().send(userId="me", body={"raw": raw}).execute()


class SheetsClient:
    """Ledger spreadsheet: sheet 'orders' (one row per order), sheet 'outcomes' (appended per run)."""
    app = "sheets"
    ORDER_COLS = ["order_id", "items", "kind", "ship_date", "carrier", "ship_to", "tracking", "tracking_status",
                  "delivered_at", "signature_image", "refunded_at", "refund_policy_shown", "distinct_from"]
    OUTCOME_COLS = ["run_id", "dispute_id", "reason", "verdict", "outcome", "amount", "recovered", "ce3"]

    def __init__(self, spreadsheet_id: str | None = None, creds=None):
        from googleapiclient.discovery import build
        self.svc = build("sheets", "v4", credentials=creds or google_creds(), cache_discovery=False)
        self.id = spreadsheet_id or os.environ.get("SHEET_ID") or self._create()

    def _create(self) -> str:
        body = {"properties": {"title": "Rebuttal ledger"}, "sheets": [{"properties": {"title": "orders"}}, {"properties": {"title": "outcomes"}}]}
        sid = self.svc.spreadsheets().create(body=body).execute()["spreadsheetId"]
        self.svc.spreadsheets().values().update(spreadsheetId=sid, range="orders!A1", valueInputOption="RAW", body={"values": [self.ORDER_COLS]}).execute()
        self.svc.spreadsheets().values().update(spreadsheetId=sid, range="outcomes!A1", valueInputOption="RAW", body={"values": [self.OUTCOME_COLS]}).execute()
        return sid

    def seed_orders(self, rows: list[dict[str, Any]]) -> None:
        values = [[_cell(r.get(c)) for c in self.ORDER_COLS] for r in rows]
        self.svc.spreadsheets().values().append(spreadsheetId=self.id, range="orders!A1", valueInputOption="RAW", body={"values": values}).execute()

    def order(self, order_id: str) -> dict[str, Any] | None:
        res = self.svc.spreadsheets().values().get(spreadsheetId=self.id, range="orders!A2:M").execute()
        for row in res.get("values", []):
            if row and row[0] == str(order_id):
                d = {c: (row[i] if i < len(row) else "") for i, c in enumerate(self.ORDER_COLS)}
                d["signature_image"] = d["signature_image"] in ("TRUE", "true", "1", "yes")
                d["refund_policy_shown"] = d["refund_policy_shown"] in ("TRUE", "true", "1", "yes")
                d["ship_to_struct"] = _addr_struct(d.get("ship_to"))
                return {k: (v if v != "" else None) for k, v in d.items()}
        return None

    def append_outcome(self, row: dict[str, Any]) -> None:
        values = [[_cell(row.get(c)) for c in self.OUTCOME_COLS]]
        self.svc.spreadsheets().values().append(spreadsheetId=self.id, range="outcomes!A1", valueInputOption="RAW", body={"values": values}).execute()

    @property
    def url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self.id}"


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return v


# ---------------- Slack ----------------
class SlackClient:
    """Posts packets and waits for the human's approve/hold click over Socket Mode."""
    app = "slack"

    def __init__(self, channel: str | None = None):
        from slack_sdk import WebClient
        self.web = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
        self.channel = channel or os.environ.get("SLACK_CHANNEL", "#rebuttal")
        self._ensure_channel()

    def _ensure_channel(self) -> None:
        name = self.channel.lstrip("#")
        chans = self.web.conversations_list(types="public_channel", limit=200)["channels"]
        found = next((c for c in chans if c["name"] == name), None)
        if not found:  # bot cannot create channels; fall back to #general
            found = next((c for c in chans if c["name"] == "general"), chans[0])
            self.channel = "#" + found["name"]
        try:
            self.web.conversations_join(channel=found["id"])
        except Exception:
            pass
        self.channel_id = found["id"]

    def post(self, channel: str, text: str, blocks: list[dict[str, Any]] | None = None, thread_ts: str | None = None) -> dict[str, Any]:
        res = self.web.chat_postMessage(channel=self.channel_id, text=text, blocks=blocks, thread_ts=thread_ts)
        return {"ts": res["ts"], "channel": self.channel_id, "text": text}

    def post_approval(self, text: str, dispute_id: str) -> dict[str, Any]:
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Approve & file"}, "style": "primary", "action_id": "approve", "value": dispute_id},
                {"type": "button", "text": {"type": "plain_text", "text": "Hold"}, "style": "danger", "action_id": "hold", "value": dispute_id},
            ]},
        ]
        return self.post(self.channel, text, blocks)

    def await_approval(self, ts: str, timeout: float = 600) -> bool:
        """Block until a human clicks Approve or Hold on the message with this ts (Socket Mode)."""
        from slack_sdk.socket_mode import SocketModeClient
        from slack_sdk.socket_mode.request import SocketModeRequest
        from slack_sdk.socket_mode.response import SocketModeResponse

        decision: dict[str, bool] = {}

        def handle(client: SocketModeClient, req: SocketModeRequest) -> None:
            if req.type == "interactive" and req.payload.get("type") == "block_actions":
                client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
                if req.payload["message"]["ts"] == ts:
                    action = req.payload["actions"][0]["action_id"]
                    user = req.payload["user"].get("username") or req.payload["user"]["id"]
                    decision["ok"] = action == "approve"
                    self.web.chat_update(channel=self.channel_id, ts=ts, text=req.payload["message"].get("text", "") + f"\n\n*{'Approved' if decision['ok'] else 'Held'} by @{user}*", blocks=[])

        sm = SocketModeClient(app_token=os.environ["SLACK_APP_TOKEN"], web_client=self.web)
        sm.socket_mode_request_listeners.append(handle)
        sm.connect()
        t0 = time.time()
        try:
            while "ok" not in decision and time.time() - t0 < timeout:
                time.sleep(0.5)
        finally:
            sm.close()
        return decision.get("ok", False)


# ---------------- Photon (iMessage / RCS) ----------------
class PhotonClient:
    """Texts the customer through a Photon line, via a Node sidecar that reuses the spectrum-ts SDK.
    Only sends into an existing thread: a shared line will not open a cold one."""
    app = "photon"

    def __init__(self, script: Path | None = None):
        import shutil
        self.node = shutil.which("node")
        self.script = str(script or ROOT / "photon" / "send.mjs")

    def send(self, to: str, text: str) -> dict[str, Any]:
        import subprocess
        if not self.node:
            raise RuntimeError("node not found")
        p = subprocess.run([self.node, self.script, to, text], capture_output=True, text=True, timeout=90)
        out = (p.stdout or "").strip().splitlines()
        data = json.loads(out[-1]) if out and out[-1].startswith("{") else {"ok": False, "error": (p.stderr or "")[-200:]}
        if not data.get("ok"):
            raise RuntimeError(f"photon send failed: {data.get('error')}")
        return data


# ---------------- CALL-E (outbound phone call) ----------------
class CalleClient:
    """The CALL-E SDK client as the agent sees it: calls.create / get / list_events. `live` marks real calls for the gate."""
    app = "calle"
    live = True

    def __init__(self):
        from calle import CalleClient as _Calle
        kw = {"api_key": os.environ["CALLE_API_KEY"]}
        if os.environ.get("CALLE_BASE_URL"):
            kw["base_url"] = os.environ["CALLE_BASE_URL"]
        self._client = _Calle(**kw)
        self.calls = self._client.calls
