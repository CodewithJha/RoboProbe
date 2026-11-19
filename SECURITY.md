# Security Policy

## Project status

RoboProbe is in the **design phase (pre-alpha)**: there is no released software yet. This policy applies to
the code as it is developed and to released versions afterwards. Threat model: [`docs/31-threat-model.md`](docs/31-threat-model.md).

## Supported versions

| Version | Supported |
|---------|-----------|
| `main` (pre-release) | ✅ |
| Latest minor release (once published) | ✅ |
| Older releases | ❌ |

## Reporting a vulnerability

Please **do not** open a public issue. Report privately via GitHub's
**[private vulnerability reporting](https://github.com/CodewithJha/RoboProbe/security/advisories/new)**
(Security tab → "Report a vulnerability"). Include affected version/commit, reproduction steps, impact, and
any suggested fix.

What to expect (best-effort, volunteer project):

- Acknowledgement within **7 days**.
- Assessment and plan within **14 days**.
- Fix and coordinated disclosure (GitHub Security Advisory, credit if you wish) as soon as practical.

## Security design defaults

API and web bind to `127.0.0.1` by default; a token is required when exposed beyond loopback; no secrets in
the repository; untrusted inputs handled with `yaml.safe_load`, a restricted expression evaluator and path
confinement; dependencies, secrets and container images are scanned in CI (see `docs/21` and `docs/20`).
