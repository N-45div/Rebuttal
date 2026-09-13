# Setup

Offline first, then one app at a time. The offline path needs no accounts.

## 0. Offline (two minutes)

```bash
git clone https://github.com/N-45div/Rebuttal && cd Rebuttal
pip install stripe openai slack-sdk google-api-python-client google-auth-oauthlib pydantic python-dotenv pytest calle-ai
python -m pytest -q                    # 15 unit tests
python -m rebuttal.evalsuite           # 22 scenarios × 3 attempts against the twins
python -m rebuttal.harness --dry-run   # what the harness would tighten from runs/
```

Python 3.11+ (the `calle-ai` SDK requires it). Node 18+ only for the Photon sidecar.

## 1. Stripe (test mode, five minutes)

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

Prove the CE3.0 validator is live: `bash scripts/verify_ce3.sh` (uses the CLI's login, `stripe login`).

## 2. GPT-6 Astra

```
OPENAI_API_KEY=sk-...
REBUTTAL_MODEL=gpt-6-astra
```

One call per run, about 375 tokens. The scenario suite never calls the model.

## 3. Slack (ten minutes)

The app manifest is in `slackapp/manifest.json`. Two ways in:

**Slack CLI:** `slack login`, then in `slackapp/` run `slack install --team <TEAM_ID> --environment deployed`. The CLI creates and installs the app from the manifest.

**Or api.slack.com:** Create New App → From a manifest → paste `slackapp/manifest.json` → Install to Workspace.

Then from the app's pages:

- OAuth & Permissions → Bot User OAuth Token → `SLACK_BOT_TOKEN=xoxb-...`
- Basic Information → App-Level Tokens → Generate, scope `connections:write` → `SLACK_APP_TOKEN=xapp-...`
- `SLACK_CHANNEL=#rebuttal` (the bot falls back to `#general` if the channel does not exist; invite the bot with `/invite @Rebuttal`)

Socket Mode and Interactivity are already on in the manifest, so no public URL is needed.

## 4. Google: Gmail + Sheets (ten minutes)

Google's built-in gcloud client is refused for Gmail scopes, so the project needs its own OAuth client:

1. `gcloud services enable gmail.googleapis.com sheets.googleapis.com --project <PROJECT>`
2. Google Auth Platform → **Audience**: External, publishing status Testing, add your address under **Test users**. (Skipping this produces "Access blocked: app has not completed the Google verification process".)
3. Google Auth Platform → **Clients** → Create → Desktop app → download JSON → save as `credentials.json` in the repo root.

First run opens the consent screen once and writes `token.json`. Both files are gitignored.

## 5. CALL-E (five minutes)

Sign up at https://dashboard.heycall-e.com, verify identity (outbound calls need it), create an API key.

```
CALLE_API_KEY=iams_live_...
CALLE_BASE_URL=https://api.heycall-e.com
```

Twenty free calls on signup, then $0.05 per call. Omit the key and the agent runs without the call step (the scenario `call_unanswered` shows the behaviour: evidence unchanged).

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
DEMO_CUSTOMER_EMAIL=you@example.com     # the inbox the seeded thread lands in (same as the Gmail account)
DEMO_CUSTOMER_PHONE=+1...               # the phone that answers the call and receives the text
```

```bash
python -m rebuttal.demo seed                  # customer, 2 prior charges, CE3.0 dispute, ledger sheet, email thread
python -m rebuttal.demo seed --silent-thread  # no email thread → the agent will call the customer
python -m rebuttal.demo run                   # answer the phone, then click Approve & file in Slack
```

`seed` appends `SHEET_ID` and `DEMO_DISPUTE` to `.env`. Each run writes `runs/<run_id>.json`.

## Full `.env`

```
STRIPE_SECRET_KEY=
STRIPE_TEST_OUTCOME_MARKER=winning_evidence
OPENAI_API_KEY=
REBUTTAL_MODEL=gpt-6-astra
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_CHANNEL=#rebuttal
CALLE_API_KEY=
CALLE_BASE_URL=https://api.heycall-e.com
DEMO_CUSTOMER_EMAIL=
DEMO_CUSTOMER_PHONE=
PHOTON_ENABLED=1
```

## Things that bit us

- Stripe disputes **submit by default**. The client always stages with `submit=false` first.
- Stripe's CE3.0 validator rejects a `device_fingerprint` under 20 characters. Real checkout fingerprints are longer; seed data must be too.
- The Slack bot cannot create channels with `chat:write` scopes; create `#rebuttal` by hand or let it fall back to `#general`.
- Google test users: the address that signs in must be on the Audience list, or every consent attempt is blocked.
- A Slack approval that never comes is a HOLD after ten minutes. Nothing is filed. The dispute stays open and can be rerun.
