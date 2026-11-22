#!/usr/bin/env python3
"""Check the rendered Compose runtime policy for every configured profile."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Sequence

_CORE_PROFILES = {"core", "app", "dev", "observability"}
_DATABASE_SERVICES = {"postgres", "migrate", "orchestrator", "worker-k2d", "worker-gazebo", "api"}
_SECRET_ENV = {
    "PGPASSWORD",
    "POSTGRES_PASSWORD",
    "ROBOPROBE_API__TOKEN",
    "GF_SECURITY_ADMIN_PASSWORD",
}
_DEFAULT_FILE = Path(__file__).resolve().parents[1] / "docker/compose.yaml"
_UID_GID_PARTS = 2


def _positive(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return False
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return False
    return math.isfinite(number) and number > 0


def _service_checks(name: str, service: dict[str, Any]) -> dict[str, bool]:
    owner = str(service.get("user", "")).split(":")
    health = service.get("healthcheck", {})
    test = health.get("test", [])
    secrets = {item["source"] for item in service.get("secrets", [])}
    tmpfs = {entry.split(":", 1)[0] for entry in service.get("tmpfs", [])}
    env = service.get("environment", {})
    dsn = env.get("ROBOPROBE_DATABASE__URL", "")
    return {
        "must use an explicit numeric non-root UID and GID": len(owner) == _UID_GID_PARTS
        and all(part.isdecimal() and int(part) > 0 for part in owner),
        "requires a read-only root and /tmp tmpfs": service.get("read_only") is True
        and "/tmp" in tmpfs,  # noqa: S108 - service mount destination
        "must drop every capability and grant none": "ALL" in service.get("cap_drop", [])
        and not service.get("cap_add"),
        "requires no-new-privileges": "no-new-privileges:true" in service.get("security_opt", []),
        "requires positive CPU, memory and PID limits": all(
            _positive(service.get(key)) for key in ("cpus", "mem_limit", "pids_limit")
        ),
        "requires container namespaces and no privileged access": not service.get("privileged")
        and not service.get("devices")
        and all(service.get(key) != "host" for key in ("network_mode", "pid", "ipc")),
        "requires managed restarts": service.get("restart")
        == ("no" if name == "migrate" else "unless-stopped"),
        "requires an enabled health probe": name == "migrate"
        or (len(test) > 1 and test[0] in {"CMD", "CMD-SHELL"} and not health.get("disable")),
        "database ports must bind to IPv4 loopback": name not in {"postgres", "postgres-port"}
        or all(port.get("host_ip") == "127.0.0.1" for port in service.get("ports", [])),
        "database credentials must use the shared secret": name not in _DATABASE_SERVICES
        or ("db_password" in secrets and urlsplit(dsn).password is None),
        "credentials must be mounted, never passed as environment values": not any(
            env.get(key) for key in _SECRET_ENV
        ),
        "requires the API token secret": name not in {"api", "prometheus"}
        or "api_token" in secrets,
        "requires the Grafana password secret": name != "grafana"
        or "grafana_admin_password" in secrets,
        "must not mount the Docker socket": not any(
            "/docker.sock" in str(volume.get(key, ""))
            for volume in service.get("volumes", [])
            for key in ("source", "target")
        ),
    }


def policy_errors(config: dict[str, Any], profile: str) -> list[str]:
    """Return policy violations without printing environment values."""
    services = config.get("services", {})
    errors = [
        f"{profile}/{name}: {message}"
        for name, service in services.items()
        for message, valid in _service_checks(name, service).items()
        if not valid
    ]
    if not services:
        errors.append(f"{profile}: no services were rendered")
    for name, source in config.get("secrets", {}).items():
        if not source.get("file"):
            errors.append(f"{profile}/{name}: secrets require file sources")
    if profile == "gazebo" and "worker-gazebo" not in services:
        errors.append(f"{profile}: missing worker-gazebo")
    if "migrate" in services and (
        services["migrate"].get("command") != ["db", "upgrade"]
        or any(
            dependency["migrate"].get("condition") != "service_completed_successfully"
            for service in services.values()
            if "migrate" in (dependency := service.get("depends_on", {}))
        )
    ):
        errors.append(f"{profile}/migrate: require the one-shot successful migration")
    return errors


def _compose(command: list[str]) -> str:
    executable = ["docker", "compose", *command]
    return subprocess.run(  # noqa: S603 - fixed Docker CLI and argument list
        executable, check=True, capture_output=True, text=True, timeout=30
    ).stdout


def main(argv: Sequence[str] | None = None) -> int:
    """Render active profiles and return nonzero for any runtime policy violation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-f", "--file", type=Path, default=_DEFAULT_FILE)
    args = parser.parse_args(argv)
    prefix = ["-f", str(args.file)]
    try:
        profiles = set(_compose([*prefix, "config", "--profiles"]).splitlines())
        errors = [
            f"missing Compose profile: {profile}" for profile in sorted(_CORE_PROFILES - profiles)
        ]
        for profile in sorted(profiles):
            flags = ["--profile", "core"] if profile == "gazebo" else []
            rendered = _compose(
                [*prefix, *flags, "--profile", profile, "config", "--format", "json"]
            )
            errors.extend(policy_errors(json.loads(rendered), profile))
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Docker Compose could not render the policy inputs.", file=sys.stderr)
        return 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Compose policy passed for " + ", ".join(sorted(profiles)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
