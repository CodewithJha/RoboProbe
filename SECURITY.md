# Security Policy

RoboProbe is a local, single-user research tool (threat model: `docs/31-threat-model.md`).

## Supported versions
The latest minor release on `main` receives security fixes.

## Reporting a vulnerability
Please use GitHub's **private vulnerability reporting** ("Security" tab → "Report a vulnerability") on
`CodewithJha/RoboProbe`. Do not open a public issue. Expect an acknowledgement within 7 days.

## Hardening defaults
API and web bind to `127.0.0.1`; an API token is required when binding elsewhere; no secrets are stored in the
repository; dependencies and images are scanned in CI.
