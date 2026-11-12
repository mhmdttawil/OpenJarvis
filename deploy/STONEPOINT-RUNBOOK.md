# OpenJarvis for Stonepoint — cloud deploy runbook

What you get: one always-on Jarvis server on Render, running Claude, that you can
chat with from your laptop (browser GUI) and your phone (browser, or by texting it),
that can **text you and call you**, and that can read the Ops Portal (jobs, invoices,
payments, bank balance, expenses) when you ask it questions.

Cost: Render Starter ~$7/mo + Twilio number ~$1.15/mo + per-use (SMS ≈ $0.008, voice ≈ $0.014/min)
+ Anthropic usage (Sonnet; a typical day of ops questions is well under $1).

## 0. Accounts you need (10 minutes)
1. GitHub account (to hold your fork).
2. Render account — https://render.com (card required for the Starter plan).
3. Anthropic API key — https://console.anthropic.com → API Keys → Create key.
4. Twilio — https://twilio.com → buy ONE number that has both Voice and SMS. Recommended: a
   toll-free number (+1 8XX) and submit the free Toll-Free Verification form right away
   (business name, website, "owner notifications" use case, sample message). Until it is
   approved (usually 1-5 business days) outbound texts are blocked; voice works immediately.
   A local number works too but needs A2P 10DLC brand/campaign registration, which is slower.
   Note your Account SID, Auth Token, and the number in E.164 (+1XXXXXXXXXX).

## 1. Fork and patch the repo (5 minutes)
1. Fork https://github.com/open-jarvis/OpenJarvis to your GitHub.
2. Clone your fork and apply this bundle:
   ```bash
   git clone https://github.com/<you>/OpenJarvis.git && cd OpenJarvis
   git apply /path/to/openjarvis-deploy/fork.patch        # Dockerfile extras + tool registration + 2 new tool files
   cp /path/to/openjarvis-deploy/render.yaml render.yaml   # replaces the stock Blueprint
   git add -A && git commit -m "Stonepoint deploy: Claude engine, Twilio call/SMS tools, Ops Portal tool" && git push
   ```
   The patch adds `src/openjarvis/tools/phone_call.py` (tools `phone_call`, `send_sms`)
   and `src/openjarvis/tools/ops_portal.py` (tool `ops_portal`, read-only), registers them,
   and makes the Docker image install the `inference-cloud` (Anthropic SDK) and
   `channel-twilio` extras. Both tools were tested: the Ops Portal tool against the live table,
   the Twilio tools with a stubbed client.

## 2. Deploy on Render (5 minutes + ~10 min build)
1. https://dashboard.render.com/blueprint/new → pick your fork → Apply.
2. Render asks for the `sync: false` secrets. Paste: `ANTHROPIC_API_KEY`, `TWILIO_ACCOUNT_SID`,
   `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `JARVIS_OWNER_PHONE` (your cell, +1…),
   `OPS_SUPABASE_ANON_KEY` (Supabase → Project Settings → API → anon public),
   `OPS_API_KEY` (the portal write key stored in `sp_config` — the tool only reads).
3. Wait for the first deploy; `https://<service>.onrender.com/health` should return `{"status":"ok"}`.
4. In the Render dashboard copy the generated `OPENJARVIS_API_KEY` — this is the password
   for the GUI and API. Keep it in your password manager.

## 3. Laptop + phone chat
- Open `https://<service>.onrender.com/` in any browser (Mac, iPhone). Sign in with the
  `OPENJARVIS_API_KEY`. Add it to the iPhone home screen for an app-like icon.
- Both devices can be open at the same time; conversations live on the server's disk.

## 4. Texting with Jarvis (two-way SMS)
1. In Twilio → your number → Messaging → "A message comes in" → Webhook,
   URL `https://<service>.onrender.com/webhooks/twilio`, method POST. Save.
2. In the Jarvis GUI → Agents → create an agent (orchestrator, Claude) and add a
   channel binding of type `twilio` with your Account SID, Auth Token and Twilio number.
   (Same thing via API: `POST /api/agents/<id>/channels` with
   `{"channel_type":"twilio","config":{"account_sid":"…","auth_token":"…","phone_number":"+1…"}}`.)
3. Text your Twilio number from your cell: Jarvis acks ("Message received…") and replies.

## 4b. Calling Jarvis (talk to it on the phone)
1. Twilio Console → Functions & Assets → Services → Create Service `jarvis-voice`.
2. Add Function `/voice` (visibility Public), paste `deploy/twilio/voice-inbound.js`.
3. Dependencies: add `axios`. Environment Variables: `JARVIS_URL` = `https://<service>.onrender.com`,
   `JARVIS_API_KEY` = the OPENJARVIS_API_KEY from Render, `JARVIS_OWNER_PHONE` = your cell (+1…).
4. Deploy All, copy the Function URL (`https://jarvis-voice-XXXX.twil.io/voice`).
5. Your Twilio number → Voice → "A call comes in" → Function → jarvis-voice / voice. Save.
6. Paste that same URL into Render as `JARVIS_VOICE_URL` (so when Jarvis calls you, you can talk back).
Call your Twilio number: "Jarvis here. How can I help?" — ask anything; say "goodbye" to end.
Answers take 3-8 seconds (Claude + tool call); that is normal.

## 5. Jarvis calling / texting YOU
The agent now has two tools:
- `phone_call(message)` — rings `JARVIS_OWNER_PHONE` and reads the message aloud twice (Twilio Polly voice).
- `send_sms(message)` — texts `JARVIS_OWNER_PHONE`.
Both refuse any other number unless you set `JARVIS_ALLOW_ANY_NUMBER=1`.
Make sure the agent's tool list includes them (GUI → agent → tools, or in `config.toml`
`[tools] enabled = [..., "phone_call", "send_sms", "ops_portal"]`).
Test: in the GUI say *"Call me and tell me the Victoria's Secret job is confirmed for 10 AM."*

To have it call you on a schedule or on a condition, create a scheduled task on the
agent (GUI → agent → Tasks, or `[scheduler] enabled = true` in config) with a prompt like:
*"Every weekday 7:30 AM: use ops_portal jobs_ball_me and balance. If anything is due today
or the available balance is under $1,000, call me with a 30-second summary; otherwise text me."*

## 6. Ops Portal questions it can answer
"What's waiting on me?", "Did Myriad pay?", "What's the balance?", "Show me WO 302403",
"What did we spend on fuel this month?", "Open invoices?", "Anything for Steelblue?"
The `ops_portal` tool reads the same `sp_docs` table the portal and the nightly sync use.
It never writes; the sync routine in Claude keeps writing the table as before.

## 7. Keep in mind
- Render Starter sleeps never, but a redeploy restarts the process; the disk keeps state.
- Rotate the `OPENJARVIS_API_KEY` from the Render dashboard if it ever leaks.
- Security scanners in Jarvis are on by default (`[security] mode = "warn"`); leave them on.
- Upgrading: `git fetch upstream && git merge upstream/main` in your fork; the patch is small
  and re-applies easily if it conflicts (`fork.patch` is the whole diff).
