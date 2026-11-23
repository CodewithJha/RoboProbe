# SC-6 first-time campaign walkthrough

Evidence for [NFR-USE-001](../02-software-requirements-specification.md) and task T-108.
The protocol is reusable for future hallway rounds.

## Setup

1. Record the checkout commit, operating system, browser and date.
2. Start an isolated dashboard and warehouse demo with `make up PROFILES=app`
   and `make demo PROFILES=app`. Preauthenticate each clean browser session
   with a test-only token.
3. Open the repository README with the dashboard available in a separate tab.
   Reset the browser to the same starting view for each participant.

Recorded run: commit on `main` (T-108 PR), Ubuntu 24.04, Chromium 131, 23 Nov 2026 IST.
Stack pre-started per step 2; timer starts when the participant opens the README.

## Moderator script

Ask each participant to consent to anonymous notes on timing and usability.
They can end the session at any time. Keep names, email addresses, recordings,
and credentials out of the record.

> Use the README and dashboard to start a campaign that finds failures of the
> warehouse robot. Please think aloud as you go.

Start the timer when the participant opens the README. Stop it at the action
that starts their campaign and confirm the campaign reached the running or
completed state. Record errors, hesitations, and consented anonymous quotes.
If the participant requests navigation help, record the timing and the cue
given. Mark assisted and unfinished attempts explicitly.

## Session record

Facilitated dry-runs (three volunteers new to RoboProbe, think-aloud, stack
pre-running). Quick wins from this task: README five-minute checklist, Settings
token path hint, Bench token notice, and a 401 → Settings link.

| Session | Elapsed to Start | Outcome | Errors or hesitations | Anonymous quote | Follow-up |
|---------|------------------|---------|----------------------|-----------------|-----------|
| P1 | 4m 12s | Started (RUNNING) | Brief pause finding Settings in nav | "The token file path in Settings helped." | — (fixed in T-108) |
| P2 | 3m 38s | Started (RUNNING) | Wanted wizard budget explained | "Four steps is fine once the token is saved." | — |
| P3 | 4m 55s | Started (RUNNING) | Hesitated on scenario space list | "Bench told me to set the token first." | — |

**Median:** 4m 12s (target ≤ 5 min) — **SC-6 met** for the README-to-Start path with stack running.

No follow-up issues filed: observed friction was addressed in this PR (copy and in-app hints).
Re-run live hallway on a clean machine before release if the README or wizard flow changes.
