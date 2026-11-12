---
name: kfm-workorder-closeout
description: Close out a KFM / Identiti work order so the invoice gets paid.
version: 0.1.0
license: MIT
---

# KFM / Identiti work order closeout

Use when a KFM / Identiti job is done on site and the owner asks what is needed to close it, invoice it, or why an invoice is stuck.

1. Look the job up with `ops_portal` (`job`, arg = the WO number). Note stage, NTE, invoice number and the last history lines.
2. A KFM invoice is only paid when ALL of these exist: IVR check-in and check-out on the service appointment (SA-xxxxxx), before and after photos, the work-completion / MOD sign-off sheet signed AND stamped by the store's Manager on Duty, and the invoice amount at or under the NTE (otherwise an NTE increase request first).
3. Tell the owner, in order, exactly which of those are still missing for this job, who it goes to (fminvoices@identiti.net for completion documents; the dispatching coordinator for NTE increases), and the invoice number to reference.
4. If the invoice is already sent and KFM is chasing documents, the next step is always the missing document, not a resend of the invoice.
5. Keep the answer to a short checklist the owner can act on from a phone.
