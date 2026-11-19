# ADR-0016: Plugin architecture via entry points + dependency injection at a composition root

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context
The concept's future scope (new simulators, adversarial generators, formal oracles, other stores) requires swapping parts without touching others.

## Decision
Define ports (Protocols/ABCs) for `SimulatorBackend`, `Strategy`, `Oracle`, `Analyzer`, `RunQueue`, `ArtifactStore`, repositories. Implementations register through Python entry-point groups (`roboprobe.backends`, `roboprobe.strategies`, `roboprobe.oracles`, `roboprobe.analyzers`, `roboprobe.stores`). Objects are wired explicitly in one **composition root** per process (`roboprobe.bootstrap`) via constructor injection — no global singletons, no service locator inside domain code. `import-linter` enforces layer boundaries.

## Alternatives considered
| Option | Assessment |
|--------|-----------|
| Hard-wired imports | Every swap touches core |
| DI framework (dependency-injector) | Extra magic; explicit factories suffice |
| Dynamic import by string in config only | No discoverability or validation |

## Consequences
- + Open/closed: add without modifying
- + Easy fakes in tests
- − Slight indirection

## Verification / compliance
Contract test suites per port; import-linter contracts in CI.
