---
name: morning-ops-briefing
description: Build the owner's 60-second morning operations briefing from the Ops Portal.
version: 0.1.0
license: MIT
---

# Morning operations briefing

Use when the owner asks for a briefing, "what's today", "catch me up", or when a scheduled task runs this skill.

1. Call `ops_portal` with `jobs_ball_me`, then `jobs_ball_them`, then `balance`, then `sync_status` (Stonepoint). Call `jobs_open` for Steelblue only if asked.
2. Build the briefing in this order, spoken-style, no bullets if it will be read aloud:
   - Jobs scheduled today or tomorrow (site, time if known).
   - What the owner owes (ball = me), oldest first, max five items.
   - Money: available balance, deposits in the last few days, anything older than 30 days unpaid or an invoice KFM is chasing documents on.
   - One-line flags: balance under $1,000, an unmatched deposit, a remittance with no deposit.
3. Keep it under 120 words for a phone call or text; under 250 words in chat. End with the single most important thing to do first.
