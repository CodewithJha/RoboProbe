# 28 — Traceability Matrix (PRD → SRS → Design → Tasks → Tests)

> Maintained by every PR that adds/changes a requirement (32 §3). From M3 on, a script
> (`scripts/trace_report.py`) scans test docstrings/markers (`@pytest.mark.req("FR-ORC-002")`) and
> produces `docs/evidence/traceability.html`; CI fails if a **Must** requirement has no linked test.

## 1. Forward traceability (product requirement → verification)

| PRD | SRS requirements | Design (docs §) | Tasks (22) | Verification (18) |
|-----|------------------|-----------------|-----------|-------------------|
| PR-01 Scenario space | FR-SCN-001…007 | 06 §2–5, 05 §3 | T-020…T-025 | unit/property `tests/unit/scenario`, schema fixtures |
| PR-02 Autonomous campaigns | FR-RUN-001…006, FR-SIM-001, FR-SIM-003 | 04 §4–6, 05 §5, 10, 11 §4, 14 §2–5 | T-012, T-033, T-035, T-040…T-047, T-091, T-092, T-093a/b, T-096 | integration runner, chaos, backend contract, [warehouse map alignment](evidence/T-092.md), Jazzy package and lidar launch tests, sim map alignment |
| PR-03 Intelligent selection | FR-SEL-002/003/005/006/007/008 | 07 §4–6 | T-055…T-061 | strategy contract, benchmark gates 18 §4.4, EXP-01 |
| PR-04 Baselines | FR-SEL-001 | 07 §3 | T-050, T-051 | strategy contract, design tests |
| PR-05 Failure detection | FR-ORC-001…006 | 08 | T-036…T-039 | golden traces, invariants |
| PR-06 Failure modes & explanation | FR-ANA-001…003, FR-ANA-006 | 09 §3–4, §8 | T-070…T-072, T-075 | synthetic clustering/SHAP tests |
| PR-07 Risk atlas | FR-RSK-001…003 | 09 §5 | T-055, T-076 | analytic risk tests |
| PR-08 Replay & regression | FR-REP-001/002, FR-SCN-008 | 21 §3–4, 06 §6, 14 §7 | T-026, T-043, T-044 | bit-identical replay, export round-trip |
| PR-09 Dashboard | FR-DSH-001…005, FR-DSH-008 | 13 | T-085…T-089, T-110, T-111 | Vitest, Playwright, axe |
| PR-10 Experiments & report | FR-EXP-001/002/003, FR-DSH-007 | 19, 09 §7, 05 §12 | T-078, T-079, T-100…T-105 | metric unit tests, analytical mode evidence, report render |
| PR-11 Built-in simulator | FR-SIM-001/002 | 10 §7, ADR-0003 | T-030…T-035, T-103 | determinism, speed, calibration |
| PR-12 Typed configuration | NFR-CFG-001…003 | 27, ADR-0015 | T-003 | precedence tests, config-docs drift check |
| PR-13 Deployability | NFR-DEP-001…003 | 17, 20, 29 | T-005, T-006, T-047, T-095 | compose smoke test, images workflow |
| PR-14 Interaction confirmation | FR-ANA-005 | 09 §6 | T-074 | synthetic interaction test |
| PR-15 LSE + rules | FR-SEL-004, FR-ANA-004 | 07 §7, 09 §4.3 | T-058, T-073 | boundary accuracy, planted thresholds |
| PR-16 Parallel/remote workers | FR-SIM-004, NFR-SCAL-001/002 | 04 §7, 10 §9, 29 §5 | T-097 | 2-parallel sim test, load test |
| PR-17 Config robustness comparison | FR-RSK-005 | 09 §5.4 | T-077 | unit test; EXP-05 |
| PR-18 Experiment UI | FR-DSH-006, FR-EXP-003 | 13 §3.7 | T-112 | e2e |
| PR-19 Plugin APIs | NFR-EXT-001…003 | 04 §8, 34 §3, ADR-0016 | T-035, T-046, T-050 | contract suites, import-linter |
| PR-20 Bundles | FR-STO-003 | 11 | T-014 | round-trip |
| PR-21 S-CEM | FR-SEL-009 | 07 §8 | T-062 | contract |
| PR-22 Observability profile | NFR-OBS-001/002 | 21 §5 | T-004, T-125, T-126 | metrics registry cross-check; tracing no-import test |

Gazebo depth verification (T-093c, #194, FR-SIM-003): the Jazzy test
`ros_ws/src/roboprobe_ros/test/test_perception_degrader.py` checks seeded depth loss and
radial noise, camera header preservation, depth-one QoS and processing within the camera period.

Catalogue API verification (T-081a, #146; FR-API-001, FR-SCN-001, UC-01/UC-10):
`backend/tests/api/test_spaces.py`, `test_sut_profiles.py` and `test_upload_body.py` cover
YAML/JSON uploads, semantic validation, JSON pointers, versioning, idempotency, profile conflicts,
configured task-root confinement, pagination limits and bounded streaming (TM-02/TM-13).

Campaign API verification (T-081b/c/d, #147–#149; FR-API-001, FR-CLI-001):
`tests/api/test_campaigns_crud.py` covers creation, idempotency, lifecycle states, pins, manual runs
and ETags; `test_uow_lifecycle.py` covers transaction entry/exit. Shared factory validation is in
`tests/unit/runner/test_campaign_factory.py`; SQL filter/keyset checks and PostgreSQL pagination
are in `tests/unit/store/test_run_queries.py` and `tests/integration/store/test_run_queries.py`.

Gazebo velocity relay verification (T-093d, #195, FR-SIM-003):
`ros_ws/src/roboprobe_ros/test/test_cmd_delay.py` launches installed Jazzy relays
against a fake simulation clock and verifies both velocity message types, FIFO ordering,
reported latency, zero-delay delivery and process shutdown.

Ground-truth geometry (T-094a, #196, FR-SIM-003 and FR-ORC-001) compares clearance
between the ROS monitor and kinematic2d on the same map, footprint and poses.

Trace transport verification (T-081e, #150; FR-DSH-005, FR-STO-002, NFR-SEC-003):
`tests/api/test_trace_artifacts.py` covers clearance minima, flag transitions, rate caps, column
selection, Parquet/attachment headers, unknown ids, and malicious stored paths (TM-04).

Creation durability and scale follow-up (#147–#149):
`tests/integration/store/test_atomic_creation.py` verifies rollback and transaction-scoped key locks;
`test_campaign_http_queries.py` verifies campaign/run HTTP filters, bounded query counts and the
200 ms p95 target at 10,000 runs. `tests/unit/runner/test_campaign_space_loader.py` covers stored
uploaded spaces and pins; factory tests verify effective selection snapshot restoration.

## 2. Non-functional requirements → verification

| NFR | Design | Verification | Gate |
|-----|--------|-------------|------|
| NFR-PERF-001/002 | 07 §6.4, 10 §7 | pytest-benchmark | PR |
| NFR-PERF-003 | 10 §8 | [T-090 spike](evidence/T-090-gazebo-spike.md) + nightly sim metrics | nightly |
| NFR-PERF-004 | 11 §3 indexes, 12 §7 | `backend/tests/perf/locustfile.py` (T-106) | nightly and load-harness PRs |
| NFR-SCAL-001/002 | 04 §7, 29 §5 | `scripts/load_campaign.py` (T-130), remote-worker manual test | release |
| NFR-REL-001/002 | 05 §5, 14 §5 | chaos tests | PR |
| NFR-REP-001/002 | 21 §2–4 | replay tests, EXP-06 | PR / release |
| NFR-MNT-001/002 | 16, 34 | coverage, ruff D rules, mypy, weekly mutmut (T-131) | PR |
| NFR-EXT-001…003 | 34 §3 | contract suites, import-linter | PR |
| NFR-CFG-001…003 | 27 | config tests, PLR2004, drift check | PR |
| NFR-DEP-001…003 | 17, 20, 29 | compose smoke, image build | PR / main |
| NFR-USE-001 | 13 | hallway test | release |
| NFR-ACC-001 | 13 §1.1, §7 | axe | nightly |
| NFR-SEC-001…003 | 21 §1, 31 | bind test, audits, gitleaks, Trivy | PR |
| NFR-PORT-001 | 17 §1 | CI OS matrix | PR |
| NFR-COST-001 | 15 | licence check | PR |
| NFR-OBS-001/002 | 21 §5 | log schema + metrics tests | PR |

## 3. Backward traceability rule

Every test, module and task must reference at least one requirement ID or ADR. Code without a
requirement is either (a) infrastructure covered by an ADR/NFR, or (b) scope creep to be removed or
proposed via RFC.

## 4. Use cases → requirements

| UC | Requirements |
|----|-------------|
| UC-01 | FR-SCN-001/002/006 |
| UC-02 | FR-RUN-*, FR-SEL-*, FR-ORC-*, FR-ANA-006 |
| UC-03 | FR-DSH-002, FR-API-002 |
| UC-04 | FR-ANA-001…005, FR-DSH-003 |
| UC-05 | FR-RSK-001…003, FR-DSH-004 |
| UC-06 | FR-REP-001 |
| UC-07 | FR-SCN-008 |
| UC-08 | FR-EXP-001…003, FR-DSH-006 |
| UC-09 | FR-DSH-007 |
| UC-10 | FR-RSK-005 |

Dashboard foundation verification (T-085b/c/d, #163–#165; FR-DSH-008, FR-DSH-002, NFR-DEP-001):
`web/src/app/router.test.tsx` covers every mount, missing routes, feature flags, errors and theme
persistence. `web/src/api/client.test.tsx` verifies authentication, ProblemError, If-Match and
infinite pagination against MSW. `config.test.ts`, `sse.test.ts` and `sseBridge.test.ts` verify
configuration, reconnect/resume, duplicate handling and every documented server event.
