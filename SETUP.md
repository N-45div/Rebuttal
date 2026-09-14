# Setup

Offline first, then one app at a time. The first two commands need no accounts at all.

## 0. No keys (two minutes)

```bash
git clone https://github.com/N-45div/Rebuttal && cd Rebuttal
pip install -r requirements.txt
python -m pytest -q                    # 52 unit tests, including grounding against a real CALL-E transcript
python -m rebuttal.confirm             # one confirmation call against the CALL-E twin: events, transcript, checks, PDF; nothing rings
```

With an OpenAI key you can also run the scenario suite, where the real GPT-6 Astra coordinator drives local twins of all six apps:

```bash
python -m rebuttal.evalsuite --only call_   # the 9 call scenarios
python -m rebuttal.evalsuite                # all 28 scenarios
python -m rebuttal.harness --dry-run        # what the harness would tighten from runs/
```

Python 3.11+ (the `calle-ai` SDK requires it). Node 18+ only for the Photon sidecar.

## 1. CALL-E (five minutes)

Sign up at https://dashboard.heycall-e.com, complete identity verification in the dashboard (outbound calls stay disabled until it is done), and create an API key.

```
CALLE_API_KEY=iams_live_...
CALLE_BASE_URL=https://api.heycall-e.com
REBUTTAL_CALL_ALLOWLIST=+1...          # every E.164 number you are authorised to call, comma-separated
MERCHANT_NAME=Ridge Outfitters         # the name the caller says in its disclosure
```

Place one real confirmation call with nothing else configured:

```bash
python -m rebuttal.confirm --live --to +1... --i-have-consent
```

It refuses, with the reason, unless the key is set, the number is E.164 and on the allowlist, `--i-have-consent` is passed, and it is between 08:00 and 21:00 where the phone is. A submitted call cannot be cancelled through the public API. Running the same command again with the same `--dispute` reuses the idempotency key, so CALL-E returns the same call instead of ringing twice.

Twenty free calls on signup, then $0.05 per call. Without a key the agent runs without the call step (scenario `call_unanswered` shows the behaviour: evidence unchanged).

## 2. Stripe (test mode, five minutes)

Any Stripe account works in test mode; nothing needs activation. If you have no account, the CLI can provision a claimable sandbox without a browser:

```bash
winget install Stripe.StripeCli        # or brew install stripe/stripe-cli/stripe
stripe sandbox create --email you@example.com
```

Then claim it from the printed URL and copy the `sk_test_` key from Developers → API keys. Put it in `.env`:

```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_TEST_OUTCOME_MARKER=winning_evidence   # test mode only; resolves a submitted test dispute
```

Prove the CE3.0 validator is live: `bash scripts/verify_ce3.sh` (uses the CLI's login, `stripe login`). The call document is uploaded through the Files API with purpose `dispute_evidence`.

## 3. GPT-6 Astra

```
OPENAI_API_KEY=sk-...
REBUTTAL_MODEL=gpt-6-astra
```

The coordinator runs on the OpenAI Agents SDK with eight tools. One dispute is one agent run of roughly ten turns and about 9,000 tokens; each scenario in the suite is one such run.

## 4. Slack (ten minutes)

The app manifest is in `slackapp/manifest.json`. Two ways in:

**Slack CLI:** `slack login`, then in `slackapp/` run `slack install --team <TEAM_ID> --environment deployed`. The CLI creates and installs the app from the manifest.

**Or api.slack.com:** Create New App → From a manifest → paste `slackapp/manifest.json` → Install to Workspace.

Then from the app's pages:

- OAuth & Permissions → Bot User OAuth Token → `SLACK_BOT_TOKEN=xoxb-...`
- Basic Information → App-Level Tokens → Generate, scope `connections:write` → `SLACK_APP_TOKEN=xapp-...`
- `SLACK_CHANNEL=#rebuttal` (the bot falls back to `#general` if the channel does not exist; invite the bot with `/invite @Rebuttal`)

Socket Mode and Interactivity are already on in the manifest, so no public URL is needed. The call streams into a thread under the dispute message: CALL-E events, the transcript, and each check.

## 5. Google: Gmail + Sheets (ten minutes)

Google's built-in gcloud client is refused for Gmail scopes, so the project needs its own OAuth client:

1. `gcloud services enable gmail.googleapis.com sheets.googleapis.com --project <PROJECT>`
2. Google Auth Platform → **Audience**: External, publishing status Testing, add your address under **Test users**. (Skipping this produces "Access blocked: app has not completed the Google verification process".)
3. Google Auth Platform → **Clients** → Create → Desktop app → download JSON → save as `credentials.json` in the repo root.

First run opens the consent screen once and writes `token.json`. Both files are gitignored.

## 6. Photon (optional, ten minutes)

Photon texts only into an **existing** thread, so the demo phone must have texted the line once before.

```bash
cd photon && npm init -y && npm install spectrum-ts   # or point PHOTON_SDK_DIR at an existing install
```

Credentials from app.photon.codes → project Settings, in a file the sidecar reads:

```
SPECTRUM_PROJECT_ID=...
SPECTRUM_PROJECT_SECRET=...
```

Set `PHOTON_ENV_FILE` to that file and `PHOTON_SDK_DIR` to `<install>/node_modules/spectrum-ts/dist`. Test: `node photon/send.mjs "+1..." "hello"`. Set `PHOTON_ENABLED=0` to skip Photon; notices then go by Gmail.

## 7. Demo data and a live run

```
DEMO_CUSTOMER_EMAIL=you@example.com     # the customer's address on the Stripe customer
DEMO_CUSTOMER_PHONE=+1...               # the phone that answers the call; must also be in REBUTTAL_CALL_ALLOWLIST
```

```bash
python -m rebuttal.demo seed --scenario call   # product-not-received dispute, parcel still in transit, no email: only the call can win it
python -m rebuttal.demo seed                   # fraud dispute with two CE3.0 prior charges and an email thread
python -m rebuttal.demo run --live-calls       # --live-calls is the per-run operator intent; answer the phone, then Approve & file in Slack
```

`seed` appends `SHEET_ID` and `DEMO_DISPUTE` to `.env`. Each run writes `runs/<run_id>.json`, and a filed call document to `runs/evidence/<run_id>.pdf`. Turn a run into a replay for the site with `python -m rebuttal.replay --trace runs/<run_id>.json --out web/public/calls/<name>.json`.

## Full `.env`

```
CALLE_API_KEY=
CALLE_BASE_URL=https://api.heycall-e.com
REBUTTAL_CALL_ALLOWLIST=
MERCHANT_NAME=Ridge Outfitters
STRIPE_SECRET_KEY=
STRIPE_TEST_OUTCOME_MARKER=winning_evidence
OPENAI_API_KEY=
REBUTTAL_MODEL=gpt-6-astra
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_CHANNEL=#rebuttal
DEMO_CUSTOMER_EMAIL=
DEMO_CUSTOMER_PHONE=
PHOTON_ENABLED=1
```

## Things that bit us

- A CALL-E call can complete with high confidence and a correct answer and still be unusable: our first live script never told the customer it was an automated call. The disclosure is now in the script and checked in the transcript.
- `calls.create_and_wait` blocks for the whole call with no progress. Rebuttal creates the call and polls `list_events` and `get` instead, so the Slack thread shows the phone ringing.
- CALL-E transcripts carry speech-recognition noise ("HI received order."). Grounding matches meaning with simple patterns and treats anything unclear as unknown.
- A new CALL-E account accepts calls but every attempt fails until identity verification is done in the dashboard.
- Stripe disputes **submit by default**. The client always stages with `submit=false` first.
- Stripe's CE3.0 validator rejects a `device_fingerprint` under 20 characters. Real checkout fingerprints are longer; seed data must be too.
- The Slack bot cannot create channels with `chat:write` scopes; create `#rebuttal` by hand or let it fall back to `#general`.
- Google test users: the address that signs in must be on the Audience list, or every consent attempt is blocked.
- A Slack approval that never comes is a HOLD after ten minutes. Nothing is filed. The dispute stays open and can be rerun.
