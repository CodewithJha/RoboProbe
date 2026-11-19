# Contributing to RoboProbe

Thanks for your interest! RoboProbe is maintained by Priyanshu Jha (@CodewithJha).

1. **Discuss first** for anything non-trivial: open an issue; larger changes need an RFC (`docs/templates/rfc-template.md`).
2. **Read the docs**: `docs/00-index.md`, coding standards `docs/16`, design principles `docs/34`, process `docs/32`.
3. **Branch** from `main`: `feat/T-NNN-short-name`, `fix/…`, `docs/…`.
4. **Commit** with Conventional Commits (`feat(selection): add straddle acquisition`), referencing task/requirement IDs in the body.
5. **Test**: `make lint typecheck test` must pass; add tests for every change (`docs/18`).
6. **Config**: no hard-coded tunables — add typed settings and document them in `docs/27`.
7. **Docs**: update affected docs, traceability (`docs/28`) and `CHANGELOG.md` (`Unreleased`).
8. **PR**: fill in the template; keep PRs small (≤ 400 changed lines excluding generated files).
9. **Review**: follow `docs/32` §5; be kind and specific.

By contributing you agree that your contributions are licensed under the MIT License.
Security issues: see [SECURITY.md](SECURITY.md) — do not open public issues for vulnerabilities.
