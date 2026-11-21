# Security test map

Threat ids are the STRIDE rows in [doc 31 §3](../31-threat-model.md#3-stride-analysis).
`scripts/check_security_map.py` fails when a `TM-xx` row has no `pass` or `N/A` entry.
Payload fixtures live in the tests and stay under 10 KB.

| Threat | Test | Status |
| --- | --- | --- |
| TM-01 | backend/tests/security/test_tm01_auth.py::test_missing_and_wrong_token | pass |
| TM-02 | backend/tests/security/test_tm02_yaml.py::test_billion_laughs_aliases_rejected | pass |
| TM-03 | backend/tests/security/test_tm03_constraints.py::test_injection_and_huge_exponent_rejected | pass |
| TM-04 | backend/tests/security/test_tm04_artifacts.py::test_relative_traversal_rejected | pass |
| TM-05 | backend/tests/security/test_tm05_xss.py::test_mode_label_is_escaped | pass |
| TM-06 | backend/tests/security/test_tm06_cors.py::test_disallowed_origin_has_no_allow_header | pass |
| TM-07 | backend/tests/security/test_tm07_container.py::test_backend_image_is_non_root | pass |
| TM-08 | backend/tests/security/test_tm08_launch.py::test_no_shell_true_in_product_code | pass |
| TM-09 | backend/tests/security/test_tm09_postgres.py::test_db_port_is_loopback_only | pass |
| TM-10 | backend/tests/security/test_tm10_supply_chain.py::test_lockfile_and_audit_job_exist | pass |
| TM-11 | backend/tests/security/test_tm11_ci.py::test_workflows_are_least_privilege | pass |
| TM-12 | backend/tests/security/test_tm12_integrity.py::test_put_records_content_hash | pass |
| TM-13 | backend/tests/security/test_tm13_limits.py::test_budget_above_cap_rejected | pass |
| TM-14 | backend/tests/security/test_tm14_bundle.py::test_malicious_member_rejected | pass |
| TM-15 | backend/tests/security/test_tm15_manifest.py::test_manifest_hashes_hostname | pass |
