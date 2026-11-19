# ADR-0004: Python 3.12, uv, single monorepo

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

ROS 2 Jazzy uses the system Python 3.12 of Ubuntu 24.04; BoTorch 0.18 / Ax 1.3 require Python ≥ 3.11. The project has backend, ROS package, web app and docs that change together.

## Decision

Python **3.12** for all Python code; **uv** for dependency management with a workspace (`backend/` package `roboprobe`, optional extras `[ml]`, `[worker]`, `[api]`, `[dev]`); a **single Git monorepo** containing `backend/`, `ros_ws/`, `web/`, `docker/`, `configs/`, `docs/`. Inside the ROS image the worker is installed into a venv created with `--system-site-packages` so `rclpy` is importable; the worker extra excludes PyTorch.

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| Poetry | Slower; workspaces weaker |
| conda | Heavy; conflicts with ROS apt Python |
| Multi-repo | Cross-cutting changes need coordinated PRs; agents lose context |
| Python 3.11 | Not the ROS Jazzy system version |

## Consequences

- + One Python version everywhere
- + Fast reproducible installs with `uv.lock`
- + Atomic cross-layer PRs
- − ROS image needs careful venv setup (documented in 17 §5)

## Verification / compliance

CI checks `requires-python = ">=3.12,<3.13"` and `uv lock --check`.
