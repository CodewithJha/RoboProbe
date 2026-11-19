# 30 — Operations Runbook

> For whoever runs RoboProbe (usually the owner). Each entry: **symptom → diagnosis → action → prevention**.
> Related: [21 Observability](21-security-reproducibility-observability.md) · [29 Deployment](29-deployment-guide.md)

## 1. Everyday commands
| Need | Command |
|------|---------|
| Status | `docker compose -f docker/compose.yaml ps` · `roboprobe campaign status <id> --watch` |
| Logs | `make logs` · `docker compose logs -f worker-gazebo` · filter: `… | jq 'select(.run_id=="…")'` |
| Resolved config | `roboprobe config show --sources` |
| Queue depth | `roboprobe queue stats` (or `/metrics` `roboprobe_queue_depth`) |
| Pause everything | `roboprobe campaign pause --all` |
| Drain a worker | `docker compose stop worker-gazebo` (SIGTERM ⇒ finishes current run, `drain_timeout_s`) |
| DB shell | `make db-shell` |

## 2. Incidents & procedures

### RB-01 Campaign auto-paused with `INFRA_UNHEALTHY`
Diagnosis: Run list filter `verdict=INVALID`; open `infra_error` and `episode.log` of 2–3 runs. Typical: Nav2 not active (startup timeout), RTF collapse, Gazebo crash.
Action: fix cause (see RB-02/03), then `:resume`. INVALID runs don't consume learning but do consume budget only if `runner.count_invalid_in_budget=true` (default false).
Prevention: keep `max_parallel_per_host` realistic.

### RB-02 Gazebo episodes slow (RTF < 0.5)
Diagnosis: `roboprobe_episode_rtf` histogram; `htop` on host; check software rendering.
Action: reduce Gazebo replicas; close GUI apps; set `physics.real_time_factor=1.0`; increase `startup_timeout_s` if startup is the bottleneck.

### RB-03 Nav2 never becomes ACTIVE
Diagnosis: `episode.log` lifecycle messages; verify `topics.yaml` and map path; run `make gz-debug RUN=<id>`.
Action: correct topic/param names (T-091 data), rebuild gazebo image.

### RB-04 Orphan `gz`/`ros2` processes, memory climbing
Diagnosis: worker health `UNHEALTHY`; `docker exec … pgrep -a gz`.
Action: `docker compose restart worker-gazebo` (container restart kills all); file a bug with the run id.

### RB-05 Runs stuck in CLAIMED/RUNNING
Diagnosis: Workbench shows worker OFFLINE; reaper interval/timeouts in config.
Action: wait `heartbeat_timeout_s` + `reaper_interval_s`; if orchestrator down, `docker compose up -d orchestrator`. Manual: `roboprobe runs requeue --stuck`.

### RB-06 Dashboard not updating live
Diagnosis: browser devtools EventSource status; API logs `sse.*`; Postgres `LISTEN` connection.
Action: reload (Last-Event-ID resumes); restart API; check proxy buffering (`X-Accel-Buffering: no` set in nginx conf).

### RB-07 Selector fallbacks (`GP_FALLBACK_REPEATED`)
Diagnosis: logs `selector.fallback` with exception; often NaNs from INVALID handling or extreme ρ values.
Action: campaign continues with Sobol; run `roboprobe analyze` to inspect data; file bug with strategy state (`strategy_states` row).

### RB-08 Disk low (`DISK_LOW`)
Action: `roboprobe gc`; lower `storage.retention.bags_days`; set `record_bag=never` temporarily; move `artifact_root` to larger disk (update env, rsync).

### RB-09 Database migration failed on upgrade
Action: `migrate` service exits non-zero; API stays down by design. Restore from the pre-upgrade backup or roll back the image tag (29 §8); report with the Alembic revision id.

### RB-10 Replays disagree with original (Gazebo)
Diagnosis: compare manifests (`roboprobe runs diff-manifest a b`); image digest or config drift?
Action: if same manifest, this is genuine non-determinism ⇒ record reproducibility rate (MET-06), consider more repeats per scenario.

## 3. Routine maintenance
| Frequency | Task |
|-----------|------|
| Before long experiments | `make db-backup`; check disk; `make demo` smoke test |
| Weekly | review Dependabot PRs; `roboprobe gc --dry-run` |
| Monthly | update pinned ROS/Gazebo digest after nightly sim passes; restore-test a backup |
| Per release | follow 33 release checklist |

## 4. Escalation
Single-owner project: incidents are logged as GitHub issues with label `ops` and severity (18 §7). Post-incident note for S1/S2 in `docs/evidence/incidents/` (what happened, impact, root cause, fix, prevention).
