# T-122 clean-machine quick-start evidence

## Published main-image rehearsal

On 23 November 2026 IST, a fresh Ubuntu 24.04 GitHub runner pulled the published
`main` images and started an isolated Compose app without a source build. The
50-run warehouse demo completed with 37 recorded failures. Chromium rendered
the dashboard routes with the production security headers. Authenticated API
and event-stream checks passed.
[Published-image run](https://github.com/CodewithJha/RoboProbe/actions/runs/45083131691/job/137395565381)

The published-app smoke logs distinguish Compose readiness, campaign creation,
the first observed failure, Workbench registration, a visible Casebook entry,
and the browser's completed HTML report download. The smoke also checks free
space on the mounted artifact filesystem against `storage.min_free_gb` and
checks the API, orchestrator, and worker logs for JSON records without errors
during a 15-second idle window after the demo. Campaign and failure timings
are observed from the beginning of the app smoke after the pull step. They
include the automated checks ahead of the demo. Workbench and report timings
measure their own browser actions.

## Release-candidate checklist (doc 29 §10)

Record the release-candidate tag, image digests, platform, and a link to the
run or timed log. Use a clean machine and follow the README. Start the five-minute
clock after the images are pulled and stop it when the first campaign is created.

| Item | Status | Evidence |
|------|--------|----------|
| `/health/ready` 200; Workbench shows expected workers | **PASS** (main images) | CI published-app job (link above) |
| 50-run demo completes; analyze; Casebook ≥ 1 case | **PASS** (main images) | Same job — 37 failures, Casebook entry |
| Gazebo nominal `configs/scenarios/nominal.yaml` PASS | **PENDING** | Requires owner laptop / Gazebo profile; not run on CI runner |
| Idle logs JSON, no ERROR; disk > `storage.min_free_gb` | **PASS** (main images) | Smoke idle window + free-space check |
| Report opens and downloads; timing recorded | **PASS** (main images) | Smoke HTML report download |

### RC tag verification (SC-6 clock)

| Field | Value |
|-------|--------|
| Image tag exercised | `main` (pre-v1.0.0 merge) |
| Platform | `ubuntu-24.04` GitHub Actions |
| Time to first campaign | Observed in smoke metrics (job log); **≤ 5 min** for pull+start+demo path |
| v1.0.0 RC pull + checklist | **PENDING** — re-run README with `ROBOPROBE_IMAGE_TAG=v1.0.0` after release workflow (see [deployment checklist](../29-deployment-guide.md#10-post-deployment-verification-checklist)) |