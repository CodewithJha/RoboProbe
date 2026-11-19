# ADR-0015: Typed, layered configuration; no hard-coded values

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context
Thresholds, paths, URLs, timeouts and algorithm hyper-parameters will be tuned during research; hard-coded literals scattered in code make experiments irreproducible and changes risky.

## Decision
All tunables are fields of typed `pydantic-settings` models (`RoboProbeSettings` tree, 27). Sources and precedence: CLI flags > environment variables (`ROBOPROBE_` prefix, `__` nested delimiter) > `.env` > `roboprobe.toml` (or file in `ROBOPROBE_CONFIG_FILE`) > defaults in the settings classes. Domain-level per-campaign configuration (oracle thresholds, strategy params) is validated by Pydantic models and snapshotted into the DB/manifest. Secrets use `SecretStr` and are only read from env/secret files. Code must not contain magic numbers except mathematical constants; ruff rule `PLR2004` enabled.

## Alternatives considered
| Option | Assessment |
|--------|-----------|
| Plain env vars | Untyped, no validation, no nesting |
| Hydra/OmegaConf | Powerful but heavy; second config system next to Pydantic |
| Constants modules | Still hard-coded; not overridable per campaign |

## Consequences
- + Every value discoverable, validated at startup, documented
- + Experiments reproducible from snapshot
- − Slight boilerplate

## Verification / compliance
`roboprobe config show` prints the resolved config with sources; CI generates 27's tables from the models and fails on drift (`scripts/gen_config_docs.py --check`).
