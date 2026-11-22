"""Regression tests for the normalized Compose runtime policy."""

from __future__ import annotations

import json
import subprocess
import unittest
from typing import Any
from unittest.mock import patch

from _load import load_script

policy = load_script("check_compose_policy")
policy_errors, main = policy.policy_errors, policy.main


def _service() -> dict[str, Any]:
    return {
        "user": "10001:10001",
        "read_only": True,
        "tmpfs": ["/tmp:mode=1777"],  # noqa: S108 - fixture for a service mount
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "cpus": 2,
        "mem_limit": "1073741824",
        "pids_limit": 512,
        "restart": "unless-stopped",
        "healthcheck": {"test": ["CMD", "probe"]},
    }


class ComposePolicyTest(unittest.TestCase):
    """Exercise the same normalized fields Docker Compose emits."""

    def test_checks_a_non_root_service(self) -> None:
        """Accept the standard runtime controls."""
        self.assertEqual(policy_errors({"services": {"web": _service()}}, "app"), [])

    def test_rejects_removed_controls(self) -> None:
        """Identify each missing or weakened control."""
        for key, invalid in (
            ("user", "0:0"),
            ("read_only", False),
            ("tmpfs", ["/var/cache"]),
            ("cap_drop", []),
            ("cap_add", ["CHOWN"]),
            ("security_opt", []),
            ("cpus", 0),
            ("cpus", None),
            ("cpus", "unlimited"),
            ("mem_limit", "inf"),
            ("pids_limit", -1),
            ("privileged", True),
            ("network_mode", "host"),
            ("restart", "no"),
            ("healthcheck", {"test": ["NONE"]}),
            ("volumes", [{"source": "/var/run/docker.sock", "target": "/run/docker.sock"}]),
        ):
            with self.subTest(key=key):
                errors = policy_errors({"services": {"web": {**_service(), key: invalid}}}, "app")
                self.assertEqual(len(errors), 1)
                self.assertTrue(errors[0].startswith("app/web: "))

    def test_checks_database_bindings_and_redacts_credentials(self) -> None:
        """Allow loopback proxy access and omit secret values from diagnostics."""
        proxy = {**_service(), "ports": [{"host_ip": "127.0.0.1"}]}
        self.assertEqual(policy_errors({"services": {"postgres-port": proxy}}, "dev"), [])
        proxy["ports"] = [{"host_ip": "0.0.0.0"}]  # noqa: S104 - fixture for a rejected bind
        self.assertIn("loopback", policy_errors({"services": {"postgres-port": proxy}}, "dev")[0])
        api = {
            **_service(),
            "environment": {"ROBOPROBE_API__TOKEN": "fixture-secret"},
            "secrets": [{"source": "api_token"}, {"source": "db_password"}],
        }
        errors = policy_errors({"services": {"api": api}}, "app")
        self.assertEqual(len(errors), 1)
        self.assertNotIn("fixture-secret", errors[0])

    def test_requires_successful_one_shot_migration(self) -> None:
        """Require migration success before dependent services start."""
        migrate = {
            **_service(),
            "command": ["db", "upgrade"],
            "restart": "no",
            "secrets": [{"source": "db_password"}],
        }
        del migrate["healthcheck"]
        web = {**_service(), "depends_on": {"migrate": {"condition": "service_started"}}}
        errors = policy_errors({"services": {"migrate": migrate, "web": web}}, "app")
        self.assertEqual(errors, ["app/migrate: require the one-shot successful migration"])

    def test_renders_gazebo_with_its_core_dependency(self) -> None:
        """Render the optional worker with the profile that supplies migration and storage."""
        service = {**_service(), "secrets": [{"source": "db_password"}]}
        model = json.dumps({"services": {"worker-gazebo": service}})
        with (
            patch.object(
                policy,
                "_compose",
                side_effect=["app\ncore\ndev\ngazebo\nobservability", *([model] * 5)],
            ) as compose,
            patch("builtins.print"),
        ):
            self.assertEqual(main([]), 0)
        self.assertIn(
            ["--profile", "core", "--profile", "gazebo"],
            [call.args[0][2:6] for call in compose.call_args_list],
        )
        compose.side_effect = ["app\ncore\ndev\nobservability", *([model] * 4)]
        with patch.object(policy, "_compose", compose), patch("builtins.print") as output:
            self.assertEqual(main([]), 1)
        self.assertEqual(output.call_args.args, ("missing Compose profile: gazebo",))

    def test_render_failure_does_not_echo_compose_output(self) -> None:
        """Keep model interpolation output out of logs even when Docker rejects it."""
        error = subprocess.CalledProcessError(1, "docker compose", stderr="fixture-secret")
        with (
            patch.object(policy, "_compose", side_effect=error),
            patch("builtins.print") as output,
        ):
            self.assertEqual(main([]), 1)
        self.assertNotIn("fixture-secret", repr(output.call_args))
