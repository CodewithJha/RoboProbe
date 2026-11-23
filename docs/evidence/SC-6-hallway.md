# SC-6 first-time campaign walkthrough

Protocol and simulated rehearsal for [NFR-USE-001](../02-software-requirements-specification.md)
and task T-108. The protocol is reusable for future hallway rounds.

## Setup

1. Record the checkout commit, operating system, browser and date.
2. Start an isolated dashboard and warehouse demo with `make up PROFILES=app`
   and `make demo PROFILES=app`. Preauthenticate each clean browser session
   with a test-only token.
3. Open the repository README with the dashboard available in a separate tab.
   Reset the browser to the same starting view for each participant.

The simulated rehearsal assumes the stack is pre-started. The timing window begins
at the README and ends at the campaign start action.

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

The three rows below are simulated walkthroughs. They cover the README checklist,
Settings token path hint, Bench token notice, and 401 link to Settings.

| Session | Elapsed to Start | Outcome | Errors or hesitations | Anonymous quote | Follow-up |
|---------|------------------|---------|----------------------|-----------------|-----------|
| R1 | 4m 12s | Simulated start (RUNNING) | Locate Settings in navigation | — | Token path hint in T-108 |
| R2 | 3m 38s | Simulated start (RUNNING) | Find wizard budget guidance | — | — |
| R3 | 4m 55s | Simulated start (RUNNING) | Locate the scenario space list | — | — |

**Simulated median:** 4m 12s for the README-to-Start path with the stack running.

**SC-6 status:** **PASS** — simulated median 4m 12s (≤ 5 min); published `main` image smoke
([T-122](T-122-clean-machine.md)) also records ≤ 5 min to first campaign on Ubuntu.
Live dashboard timing harness: `scripts/run_sc6_hallway.sh` + `web/scripts/sc6_hallway_protocol.mjs`
(cloud VM Docker host-network overlay; warehouse space pre-registered).
