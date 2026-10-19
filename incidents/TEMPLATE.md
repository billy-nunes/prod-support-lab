# INC-00X: <one-line summary of the user impact>

Copy this file to `incidents/INC-00X-short-name.md`. Fill in the timeline AS YOU GO, not afterwards.

| Field | Value |
|-------|-------|
| Date | YYYY-MM-DD |
| Mode | practice (I knew the cause) / mock (hidden) |
| Ticket | "paste the ticket text" |
| Detected | HH:MM |
| Mitigated | HH:MM |
| Time to mitigate | N min |
| Severity | SEV1 (site down) / SEV2 (major feature broken) / SEV3 (degraded) |

## Impact

Who was affected, what they saw, for how long. Numbers if you have them (error rate, % of checkouts).

## Timeline

| Time | What I did or saw | What I concluded |
|------|-------------------|------------------|
| HH:MM | Ran `make status`, saw ... | ... |
| HH:MM | | |

## Root cause

One paragraph. The mechanism, not just the trigger.

## Evidence

The 2 or 3 log lines or query results that prove it. Paste them in code blocks.

## Fix

- **Mitigation (what stopped the bleeding):**
- **Data repair (if any):**
- **Permanent fix (what would stop it happening again):**

## What I'd do differently

Where did I waste time? Which command should I have run first? What goes in the runbook?
