# 28 — Traceability Matrix (PRD → SRS → Design → Tasks → Tests)

> Maintain requirement evidence when a PR adds or changes verification (32 §3).
> The [release traceability checker](../scripts/check_traceability.py) validates the
> individual SRS references in §2.1.

## 1. Forward traceability (product requirement → verification)

| PRD | SRS requirements | Design (docs §) | Tasks (22) | Verification (18) |
|-----|------------------|-----------------|-----------|-------------------|
| PR-01 Scenario space | FR-SCN-001…007 | 06 §2–5, 05 §3 | T-020…T-025 | unit/property `tests/unit/scenario`, schema fixtures |
| PR-02 Autonomous campaigns | FR-RUN-001…006, FR-SIM-001, FR-SIM-003 | 04 §4–6, 05 §5, 10, 11 §4, 14 §2–5 | T-012, T-033, T-035, T-040…T-047, T-091, T-092, T-093a/b, T-094c, T-096 | integration runner, chaos, backend contract, [warehouse map alignment](evidence/T-092.md), Jazzy package, lidar and navigation tests, sim map alignment |
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

Gazebo episode recording (T-094b, #197, FR-RUN-004, FR-SIM-003, FR-SIM-005) is verified in
`ros_ws/src/roboprobe_ros/test/test_episode_recorder.py` with the ROS simulation clock,
shared Trace v1 fixtures, incomplete output, and real MCAP recording.

Gazebo worker packaging (T-095, #200, FR-SIM-003, NFR-DEP-001, NFR-REP-001) uses the
image workflow to build the pinned Jazzy and Harmonic stack and smoke-test the non-root
runtime. `tests/unit/runner/test_manifest.py` verifies the image version metadata is
included in each Gazebo manifest.

Trace transport verification (T-081e, #150; FR-DSH-005, FR-STO-002, NFR-SEC-003):
`tests/api/test_trace_artifacts.py` covers clearance minima, flag transitions, rate caps, column
selection, Parquet/attachment headers, unknown ids, and malicious stored paths (TM-04).

Creation durability and scale follow-up (#147–#149):
`tests/integration/store/test_atomic_creation.py` verifies rollback and transaction-scoped key locks;
`test_campaign_http_queries.py` verifies campaign/run HTTP filters, bounded query counts and the
200 ms p95 target at 10,000 runs. `tests/unit/runner/test_campaign_space_loader.py` covers stored
uploaded spaces and pins; factory tests verify effective selection snapshot restoration.

Gazebo materialization tests in `tests/unit/backends/gazebo/test_materialize.py` cover stable
generated files, the individual effects of P1–P8, XML document restrictions and ROS topic and
parameter contracts (T-096a, FR-SIM-003).

Gazebo worker lifecycle tests in `tests/unit/backends/gazebo/test_process.py` and
`tests/unit/backends/gazebo/test_backend.py` cover process-group cleanup and classification.
The simulator gate in `tests/sim/test_gazebo_backend.py` exercises loss of a running Gazebo
process during navigation (T-096b, FR-SIM-003, FR-RUN-005).

Gazebo bag policy and download (T-097b, #204, FR-SIM-005, FR-STO-002) are verified in
`backend/tests/sim/test_bag_policy.py` with a policy truth table and a real failed-run replay
whose MCAP is downloaded through the API and read by Jazzy rosbag2.

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

### 2.1 Evidence links for individual requirements

The rows below link each FR and NFR in [the specification](02-software-requirements-specification.md)
to named tests and completed implementation issues. A dash records a pending evidence link. Test
nodes use repository-relative paths followed by the test function or literal browser test title.
The checker verifies source declarations and current GitHub closure. Release measurements and
manual acceptance results are recorded separately.

Run the strict audit from the repository root with an authenticated GitHub CLI.

```bash
python3 scripts/check_traceability.py
```

For an offline audit, capture the GitHub snapshot first and then run the checker against it.

```bash
gh issue list --repo CodewithJha/RoboProbe --state closed --limit 1000 --json url,stateReason > /tmp/roboprobe-closed-issues.json
python3 scripts/check_traceability.py --closed-issues /tmp/roboprobe-closed-issues.json
```

<!-- BEGIN REQUIREMENT EVIDENCE -->

| Requirement | Test nodes | Completed GitHub issues |
|-------------|------------|-------------------------|
| FR-SCN-001 | `backend/tests/unit/cli/test_m3_commands.py::test_space_validate` | [#89](https://github.com/CodewithJha/RoboProbe/issues/89) |
| FR-SCN-002 | `backend/tests/unit/scenario/test_schemas.py::test_removing_a_required_field_fails_with_json_pointer` | [#32](https://github.com/CodewithJha/RoboProbe/issues/32) |
| FR-SCN-003 | `backend/tests/property/scenario/test_normalize_roundtrip.py::test_float_round_trip`, `backend/tests/property/scenario/test_normalize_roundtrip.py::test_int_round_trip_is_exact`, `backend/tests/property/scenario/test_normalize_roundtrip.py::test_categorical_round_trip_is_exact` | [#34](https://github.com/CodewithJha/RoboProbe/issues/34) |
| FR-SCN-004 | `backend/tests/unit/scenario/test_constraints.py::test_rejection_sampling_never_yields_a_violating_point`, `backend/tests/unit/scenario/test_constraints.py::test_rejection_sampling_gives_up_after_max_attempts` | [#35](https://github.com/CodewithJha/RoboProbe/issues/35) |
| FR-SCN-005 | `backend/tests/unit/backends/kinematic2d/test_backend.py::test_materialize_is_byte_identical`, `backend/tests/unit/backends/gazebo/test_materialize.py::test_materializes_golden_launch_files` | [#55](https://github.com/CodewithJha/RoboProbe/issues/55), [#201](https://github.com/CodewithJha/RoboProbe/issues/201) |
| FR-SCN-006 | `backend/tests/unit/scenario/test_hashing.py::test_golden_scenario_hashes`, `backend/tests/unit/scenario/test_hashing.py::test_any_value_change_changes_the_hash` | [#37](https://github.com/CodewithJha/RoboProbe/issues/37) |
| FR-SCN-007 | `backend/tests/unit/scenario/test_pins.py::test_pinned_values_never_vary_across_sampled_scenarios` | [#38](https://github.com/CodewithJha/RoboProbe/issues/38) |
| FR-SCN-008 | `backend/tests/integration/cli/test_run_scenario.py::test_export_then_run_round_trip` | [#39](https://github.com/CodewithJha/RoboProbe/issues/39), [#96](https://github.com/CodewithJha/RoboProbe/issues/96) |
| FR-SEL-001 | `backend/tests/contract/test_strategy_contract.py::test_proposals_in_bounds_feasible_and_sized` | [#100](https://github.com/CodewithJha/RoboProbe/issues/100) |
| FR-SEL-002 | `backend/tests/benchmark/test_bo_branin.py::test_bo_median_first_fail_on_branin` | [#115](https://github.com/CodewithJha/RoboProbe/issues/115) |
| FR-SEL-003 | `backend/tests/benchmark/test_probe_multimode.py::test_probe_finds_modes_and_beats_random_median` | [#119](https://github.com/CodewithJha/RoboProbe/issues/119) |
| FR-SEL-004 | `backend/tests/unit/selection/test_lse.py::test_s_lse_registered_and_warms_up` | [#116](https://github.com/CodewithJha/RoboProbe/issues/116) |
| FR-SEL-005 | `backend/tests/contract/test_strategy_contract.py::test_determinism_with_seed`, `backend/tests/unit/runner/test_campaign_loop.py::test_identical_seeds_identical_sequences` | [#100](https://github.com/CodewithJha/RoboProbe/issues/100) |
| FR-SEL-006 | `backend/tests/contract/test_strategy_contract.py::test_proposals_in_bounds_feasible_and_sized`, `backend/tests/contract/test_strategy_contract.py::test_no_duplicates_with_pending` | [#100](https://github.com/CodewithJha/RoboProbe/issues/100), [#114](https://github.com/CodewithJha/RoboProbe/issues/114) |
| FR-SEL-007 | `backend/tests/contract/test_strategy_contract.py::test_ignores_invalid_history` | [#100](https://github.com/CodewithJha/RoboProbe/issues/100) |
| FR-SEL-008 | `backend/tests/unit/runner/test_campaign_loop.py::test_enqueued_proposal_keeps_predictions`, `web/src/features/console/ConsolePage.test.tsx::virtualizes 10,000 entries and shows available rationale fields` | [#119](https://github.com/CodewithJha/RoboProbe/issues/119), [#172](https://github.com/CodewithJha/RoboProbe/issues/172) |
| FR-SEL-009 | `backend/tests/unit/selection/test_cem_plugin.py::test_s_cem_loaded_via_entry_point` | [#124](https://github.com/CodewithJha/RoboProbe/issues/124) |
| FR-RUN-001 | `backend/tests/integration/store/test_queue_exactly_once.py::test_four_claimers_hundred_runs` | [#64](https://github.com/CodewithJha/RoboProbe/issues/64) |
| FR-RUN-002 | `backend/tests/unit/runner/test_reaper.py::test_default_timeout_requeues`, `backend/tests/unit/runner/test_reaper.py::test_overridden_timeout_and_schedule` | [#82](https://github.com/CodewithJha/RoboProbe/issues/82) |
| FR-RUN-003 | `backend/tests/unit/backends/gazebo/test_process.py::test_cancel_or_timeout_cleans_the_entire_process_group` | [#80](https://github.com/CodewithJha/RoboProbe/issues/80), [#202](https://github.com/CodewithJha/RoboProbe/issues/202) |
| FR-RUN-004 | `backend/tests/contract/test_backend_contract.py::test_trace_schema_and_rate`, `ros_ws/src/roboprobe_ros/test/test_episode_recorder.py::test_simulation_trace_and_bag` | [#57](https://github.com/CodewithJha/RoboProbe/issues/57), [#197](https://github.com/CodewithJha/RoboProbe/issues/197) |
| FR-RUN-005 | `backend/tests/unit/runner/test_replay_service.py::test_enqueue_replays_fresh_seeds`, `backend/tests/unit/runner/test_manifest.py::test_derived_seeds_match_derive_seed` | [#17](https://github.com/CodewithJha/RoboProbe/issues/17), [#85](https://github.com/CodewithJha/RoboProbe/issues/85) |
| FR-RUN-006 | `backend/tests/contract/test_backend_contract.py::test_supported_params_honesty` | [#48](https://github.com/CodewithJha/RoboProbe/issues/48), [#57](https://github.com/CodewithJha/RoboProbe/issues/57) |
| FR-SIM-001 | `backend/tests/benchmark/test_perf.py::test_k2d_episode_against_baseline` | [#54](https://github.com/CodewithJha/RoboProbe/issues/54), [#121](https://github.com/CodewithJha/RoboProbe/issues/121) |
| FR-SIM-002 | `backend/tests/unit/backends/kinematic2d/test_calibration.py::test_canonical_modes_fail_and_nominal_passes` | [#78](https://github.com/CodewithJha/RoboProbe/issues/78) |
| FR-SIM-003 | `backend/tests/sim/test_gazebo_launch.py::test_materialised_episode_flushes_and_stops`, `backend/tests/unit/backends/gazebo/test_materialize.py::test_parameter_changes_are_isolated` | [#199](https://github.com/CodewithJha/RoboProbe/issues/199), [#201](https://github.com/CodewithJha/RoboProbe/issues/201) |
| FR-SIM-004 | — | — |
| FR-SIM-005 | `ros_ws/src/roboprobe_ros/test/test_episode_recorder.py::test_simulation_trace_and_bag`, `backend/tests/sim/test_bag_policy.py::test_replay_of_failed_gazebo_run_downloads_bag` | [#197](https://github.com/CodewithJha/RoboProbe/issues/197), [#204](https://github.com/CodewithJha/RoboProbe/issues/204) |
| FR-ORC-001 | `backend/tests/unit/oracles/test_oracle_contract.py::test_robustness_in_unit_interval` | [#68](https://github.com/CodewithJha/RoboProbe/issues/68), [#69](https://github.com/CodewithJha/RoboProbe/issues/69) |
| FR-ORC-002 | `backend/tests/unit/oracles/test_oracle_contract.py::test_robustness_in_unit_interval`, `backend/tests/unit/oracles/test_clearance.py::test_contact_uses_impact_speed` | [#70](https://github.com/CodewithJha/RoboProbe/issues/70) |
| FR-ORC-003 | `backend/tests/unit/oracles/test_verdict.py::test_fail_iff_rho_negative_on_goldens`, `backend/tests/unit/oracles/test_verdict.py::test_invalid_on_infra_error` | [#77](https://github.com/CodewithJha/RoboProbe/issues/77) |
| FR-ORC-004 | `backend/tests/unit/oracles/test_verdict.py::test_tie_break_order` | [#77](https://github.com/CodewithJha/RoboProbe/issues/77) |
| FR-ORC-005 | `backend/tests/integration/oracles/test_reevaluate.py::test_reevaluate_threshold_override_can_change` | [#70](https://github.com/CodewithJha/RoboProbe/issues/70), [#93](https://github.com/CodewithJha/RoboProbe/issues/93) |
| FR-ORC-006 | `backend/tests/unit/oracles/test_oracle_contract.py::test_pure_no_io`, `backend/tests/integration/oracles/test_reevaluate.py::test_reevaluate_unchanged_matches` | [#93](https://github.com/CodewithJha/RoboProbe/issues/93) |
| FR-ANA-001 | `backend/tests/unit/analysis/test_clustering.py::test_gaussian_blobs_ari` | [#127](https://github.com/CodewithJha/RoboProbe/issues/127) |
| FR-ANA-002 | `backend/tests/unit/analysis/test_modes.py::test_medoid_and_minimal_on_five_runs` | [#129](https://github.com/CodewithJha/RoboProbe/issues/129) |
| FR-ANA-003 | `backend/tests/unit/analysis/test_importance.py::test_planted_params_rank_top_and_interaction` | [#131](https://github.com/CodewithJha/RoboProbe/issues/131) |
| FR-ANA-004 | `backend/tests/unit/analysis/test_rules.py::test_planted_threshold_recovered` | [#132](https://github.com/CodewithJha/RoboProbe/issues/132) |
| FR-ANA-005 | `backend/tests/integration/runner/test_confirmations.py::test_confirmations_postgres_roundtrip` | [#134](https://github.com/CodewithJha/RoboProbe/issues/134) |
| FR-ANA-006 | `backend/tests/unit/runner/test_analysis_jobs.py::test_incremental_triggers_at_25_and_50`, `backend/tests/unit/runner/test_analysis_jobs.py::test_enqueue_returns_reserved_id_without_waiting_and_reuses_pending` | [#138](https://github.com/CodewithJha/RoboProbe/issues/138) |
| FR-RSK-001 | `backend/tests/unit/selection/test_surrogate.py::test_p_fail_formula_and_seed_determinism` | [#110](https://github.com/CodewithJha/RoboProbe/issues/110), [#135](https://github.com/CodewithJha/RoboProbe/issues/135) |
| FR-RSK-002 | `backend/tests/unit/risk/test_mapper.py::test_classify_codes` | [#135](https://github.com/CodewithJha/RoboProbe/issues/135) |
| FR-RSK-003 | `backend/tests/unit/risk/test_mapper.py::test_all_pair_slices_six_d_under_one_second` | [#135](https://github.com/CodewithJha/RoboProbe/issues/135) |
| FR-RSK-004 | `backend/tests/unit/risk/test_volume.py::test_estimate_reproducible_and_fractions_sum` | [#136](https://github.com/CodewithJha/RoboProbe/issues/136) |
| FR-RSK-005 | `backend/tests/unit/risk/test_volume.py::test_robustness_score_in_unit_interval` | [#136](https://github.com/CodewithJha/RoboProbe/issues/136) |
| FR-EXP-001 | `backend/tests/integration/experiments/test_experiment_runner.py::test_branin_experiment_completes_and_stores_comparison` | [#109](https://github.com/CodewithJha/RoboProbe/issues/109) |
| FR-EXP-002 | `backend/tests/unit/metrics/test_statistics.py::test_compare_holm_and_a12_against_reference`, `backend/tests/unit/metrics/test_statistics.py::test_bootstrap_ci_deterministic_and_degenerate` | [#106](https://github.com/CodewithJha/RoboProbe/issues/106) |
| FR-EXP-003 | `backend/tests/unit/reporting/test_figures.py::test_experiment_figures`, `web/src/features/trials/comparison/ComparisonPage.test.tsx::plots empirical samples, mode bands and right-censored survival for completed cells` | [#141](https://github.com/CodewithJha/RoboProbe/issues/141), [#181](https://github.com/CodewithJha/RoboProbe/issues/181) |
| FR-DSH-001 | `web/e2e/specs/create-campaign.spec.ts::wizard creates a k2d campaign and console streams runs` | [#170](https://github.com/CodewithJha/RoboProbe/issues/170), [#187](https://github.com/CodewithJha/RoboProbe/issues/187) |
| FR-DSH-002 | `web/src/features/console/ConsolePage.test.tsx::updates live counters and entries and shows a dismissible scoped alert`, `backend/tests/integration/api/test_event_hub.py::test_sse_latency_p95_under_two_seconds` | [#156](https://github.com/CodewithJha/RoboProbe/issues/156), [#171](https://github.com/CodewithJha/RoboProbe/issues/171) |
| FR-DSH-003 | `web/e2e/specs/investigate-case.spec.ts::casebook medoid → replay ×3 → export report` | [#176](https://github.com/CodewithJha/RoboProbe/issues/176), [#177](https://github.com/CodewithJha/RoboProbe/issues/177) |
| FR-DSH-004 | `web/src/features/atlas/AtlasPage.test.tsx::restores custom anchor values and shows the queued probe in Console after its live event` | [#178](https://github.com/CodewithJha/RoboProbe/issues/178), [#179](https://github.com/CodewithJha/RoboProbe/issues/179) |
| FR-DSH-005 | `web/src/features/runs/RunPage.test.tsx::links the timeline scrubber to all timeline cursors and the trajectory` | [#173](https://github.com/CodewithJha/RoboProbe/issues/173), [#174](https://github.com/CodewithJha/RoboProbe/issues/174), [#175](https://github.com/CodewithJha/RoboProbe/issues/175) |
| FR-DSH-006 | `web/e2e/specs/trials.spec.ts::experiment comparison lists every strategy`, `web/src/features/trials/comparison/ComparisonPage.test.tsx::plots empirical samples, mode bands and right-censored survival for completed cells` | [#180](https://github.com/CodewithJha/RoboProbe/issues/180), [#181](https://github.com/CodewithJha/RoboProbe/issues/181) |
| FR-DSH-007 | `web/src/features/trials/comparison/ComparisonPage.test.tsx::generates a report, polls until complete, and opens the report view` | [#140](https://github.com/CodewithJha/RoboProbe/issues/140), [#183](https://github.com/CodewithJha/RoboProbe/issues/183) |
| FR-DSH-008 | `web/src/components/accessibility.test.tsx::has no axe violations across the shared components (NFR-ACC-001)`, `web/src/styles/tokens.test.ts::checks every text colour against every surface` | [#162](https://github.com/CodewithJha/RoboProbe/issues/162), [#188](https://github.com/CodewithJha/RoboProbe/issues/188) |
| FR-API-001 | `backend/tests/unit/test_export_openapi.py::test_committed_snapshot_matches_app` | [#158](https://github.com/CodewithJha/RoboProbe/issues/158) |
| FR-API-002 | `backend/tests/integration/api/test_event_hub.py::test_campaign_filter_and_header_resume` | [#156](https://github.com/CodewithJha/RoboProbe/issues/156) |
| FR-API-003 | `backend/tests/api/test_errors.py::test_each_api_error_code` | [#143](https://github.com/CodewithJha/RoboProbe/issues/143) |
| FR-CLI-001 | `backend/tests/unit/cli/test_m3_commands.py::test_campaign_lifecycle`, `backend/tests/unit/cli/test_m3_commands.py::test_campaign_create_from_flags` | [#91](https://github.com/CodewithJha/RoboProbe/issues/91) |
| FR-STO-001 | `backend/tests/integration/store/test_migrations.py::test_upgrade_downgrade_upgrade`, `backend/tests/integration/store/test_migrations.py::test_autogenerate_is_empty` | [#60](https://github.com/CodewithJha/RoboProbe/issues/60) |
| FR-STO-002 | `backend/tests/unit/store/test_artifacts.py::test_put_deduplicates_identical_content`, `backend/tests/api/test_trace_artifacts.py::test_parquet_and_artifacts_stream_with_safe_headers` | [#66](https://github.com/CodewithJha/RoboProbe/issues/66), [#150](https://github.com/CodewithJha/RoboProbe/issues/150) |
| FR-STO-003 | `backend/tests/integration/store/test_bundle_roundtrip.py::test_bundle_roundtrip` | [#125](https://github.com/CodewithJha/RoboProbe/issues/125) |
| FR-REP-001 | `backend/tests/integration/runner/test_replay.py::test_k2d_replay_same_seed_agrees` | [#92](https://github.com/CodewithJha/RoboProbe/issues/92) |
| FR-REP-002 | `backend/tests/unit/runner/test_manifest.py::test_manifest_validates_against_schema_for_k2d` | [#88](https://github.com/CodewithJha/RoboProbe/issues/88) |
| NFR-PERF-001 | `backend/tests/benchmark/test_perf.py::test_k2d_episode_against_baseline` | [#121](https://github.com/CodewithJha/RoboProbe/issues/121) |
| NFR-PERF-002 | `backend/tests/benchmark/test_perf.py::test_propose_latency_against_baseline` | [#121](https://github.com/CodewithJha/RoboProbe/issues/121) |
| NFR-PERF-003 | — | [#58](https://github.com/CodewithJha/RoboProbe/issues/58) |
| NFR-PERF-004 | `backend/tests/integration/store/test_campaign_http_queries.py::test_campaign_list_10k_runs_uses_three_queries_and_meets_latency` | [#160](https://github.com/CodewithJha/RoboProbe/issues/160) |
| NFR-SCAL-001 | — | — |
| NFR-REL-001 | `backend/tests/integration/runner/test_chaos_worker_kill.py::test_sigkill_requeue_and_complete_by_peer` | [#83](https://github.com/CodewithJha/RoboProbe/issues/83) |
| NFR-REL-002 | `backend/tests/integration/runner/test_restart_resume.py::test_restart_resume_matches_uninterrupted` | [#86](https://github.com/CodewithJha/RoboProbe/issues/86) |
| NFR-REP-001 | `backend/tests/unit/backends/kinematic2d/test_episode.py::test_trace_hash_identical_for_equal_seed`, `backend/tests/integration/runner/test_replay.py::test_k2d_replay_same_seed_agrees` | [#54](https://github.com/CodewithJha/RoboProbe/issues/54), [#92](https://github.com/CodewithJha/RoboProbe/issues/92) |
| NFR-REP-002 | — | — |
| NFR-MNT-001 | — | [#28](https://github.com/CodewithJha/RoboProbe/issues/28) |
| NFR-MNT-002 | — | [#12](https://github.com/CodewithJha/RoboProbe/issues/12) |
| NFR-USE-001 | — | — |
| NFR-ACC-001 | `web/src/components/accessibility.test.tsx::has no axe violations across the shared components (NFR-ACC-001)`, `web/src/styles/tokens.test.ts::checks every text colour against every surface` | [#188](https://github.com/CodewithJha/RoboProbe/issues/188) |
| NFR-SEC-001 | `backend/tests/security/test_tm01_auth.py::test_missing_and_wrong_token`, `backend/tests/unit/core/test_settings_validation.py::test_non_loopback_host_requires_token` | [#144](https://github.com/CodewithJha/RoboProbe/issues/144) |
| NFR-SEC-002 | `backend/tests/security/test_tm10_supply_chain.py::test_lockfile_and_audit_job_exist` | [#30](https://github.com/CodewithJha/RoboProbe/issues/30) |
| NFR-PORT-001 | — | [#28](https://github.com/CodewithJha/RoboProbe/issues/28) |
| NFR-COST-001 | `scripts/tests/test_check_licenses.py::MainTest::test_gpl_dependency_fails` | [#30](https://github.com/CodewithJha/RoboProbe/issues/30) |
| NFR-OBS-001 | `backend/tests/unit/core/test_metrics_registry.py::test_every_documented_metric_is_registered_with_exact_type_and_labels`, `backend/tests/unit/core/test_logging.py::test_every_logged_event_is_in_the_catalogue` | [#23](https://github.com/CodewithJha/RoboProbe/issues/23), [#24](https://github.com/CodewithJha/RoboProbe/issues/24) |
| NFR-OBS-002 | `backend/tests/unit/observability/test_tracing.py::test_disabled_tracing_does_not_import_opentelemetry`, `backend/tests/unit/observability/test_tracing.py::test_enabled_tracing_records_documented_span_names` | [#214](https://github.com/CodewithJha/RoboProbe/issues/214), [#215](https://github.com/CodewithJha/RoboProbe/issues/215) |
| NFR-SCAL-002 | — | — |
| NFR-SEC-003 | `backend/tests/unit/scenario/test_constraints.py::test_disallowed_expressions_are_rejected_at_compile_time`, `backend/tests/unit/store/test_artifacts.py::test_symlink_escape_rejected` | [#35](https://github.com/CodewithJha/RoboProbe/issues/35), [#66](https://github.com/CodewithJha/RoboProbe/issues/66), [#125](https://github.com/CodewithJha/RoboProbe/issues/125), [#161](https://github.com/CodewithJha/RoboProbe/issues/161) |
| NFR-CFG-001 | `backend/tests/unit/core/test_settings_validation.py::test_unknown_nested_keys_are_rejected` | [#19](https://github.com/CodewithJha/RoboProbe/issues/19) |
| NFR-CFG-002 | `backend/tests/unit/core/test_settings_precedence.py::test_precedence_each_layer_removed_yields_next`, `backend/tests/unit/core/test_settings_validation.py::test_all_errors_are_reported_together` | [#19](https://github.com/CodewithJha/RoboProbe/issues/19) |
| NFR-CFG-003 | `backend/tests/unit/scripts/test_gen_config_docs.py::test_repository_files_are_up_to_date` | [#22](https://github.com/CodewithJha/RoboProbe/issues/22) |
| NFR-DEP-001 | `backend/tests/unit/deploy/test_compose_demo.py::test_compose_smoke_script_accepts_the_core_file` | [#27](https://github.com/CodewithJha/RoboProbe/issues/27), [#97](https://github.com/CodewithJha/RoboProbe/issues/97) |
| NFR-DEP-002 | `backend/tests/security/test_tm07_container.py::test_backend_image_is_non_root` | [#26](https://github.com/CodewithJha/RoboProbe/issues/26), [#185](https://github.com/CodewithJha/RoboProbe/issues/185) |
| NFR-DEP-003 | `backend/tests/unit/test_release_check.py::test_release_workflows_pin_actions` | [#189](https://github.com/CodewithJha/RoboProbe/issues/189), [#221](https://github.com/CodewithJha/RoboProbe/issues/221) |
| NFR-EXT-001 | `backend/tests/unit/backends/test_registry.py::test_registry_loads_monkeypatched_entry_point` | [#48](https://github.com/CodewithJha/RoboProbe/issues/48), [#94](https://github.com/CodewithJha/RoboProbe/issues/94) |
| NFR-EXT-002 | — | [#14](https://github.com/CodewithJha/RoboProbe/issues/14) |
| NFR-EXT-003 | `backend/tests/unit/backends/test_registry.py::test_version_mismatch_is_plugin_error`, `backend/tests/unit/oracles/test_oracle_contract.py::test_plugin_api_version` | [#48](https://github.com/CodewithJha/RoboProbe/issues/48) |

<!-- END REQUIREMENT EVIDENCE -->

Known release evidence gaps include:

- Parallel Gazebo isolation, Gazebo replay agreement, and the Gazebo performance target
  [#203](https://github.com/CodewithJha/RoboProbe/issues/203),
  [#212](https://github.com/CodewithJha/RoboProbe/issues/212), and
  [#331](https://github.com/CodewithJha/RoboProbe/issues/331).
- End-to-end worker scalability, cross-host verification, and first-use timing
  [#216](https://github.com/CodewithJha/RoboProbe/issues/216),
  [#217](https://github.com/CodewithJha/RoboProbe/issues/217),
  [#213](https://github.com/CodewithJha/RoboProbe/issues/213), and
  [#223](https://github.com/CodewithJha/RoboProbe/issues/223).
- Coverage, docstrings, layer enforcement, and Linux/macOS portability currently use direct CI
  gates. The matrix still needs individual verification nodes for those requirements, including
  WSL2 runtime evidence for portability.
- S-PROBE has an analytic comparison test. The kinematic2d and Gazebo acceptance experiments
  are tracked in [#208](https://github.com/CodewithJha/RoboProbe/issues/208) and
  [#210](https://github.com/CodewithJha/RoboProbe/issues/210).

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
