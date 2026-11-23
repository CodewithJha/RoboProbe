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

## Release-candidate checklist

Record the release-candidate tag, image digests, platform, and a link to the
run or timed log. Use a clean machine and follow the README. Start the five-minute
clock after the images are pulled and stop it when the first campaign is created.

- [ ] API readiness succeeds and Workbench shows the expected workers.
- [ ] The 50-run demo completes. Run the campaign analysis from the deployment
  checklist and verify that Casebook shows at least one case.
- [ ] A Gazebo nominal scenario passes the warehouse acceptance oracle.
- [ ] Idle logs are JSON without errors and artifact storage has free space
  above `storage.min_free_gb`.
- [ ] The report opens and downloads. Record the dashboard, campaign,
  first-failure, and report times.

A release-candidate run and the first-time user evidence are pending.
[Deployment checklist](../29-deployment-guide.md#10-post-deployment-verification-checklist)
