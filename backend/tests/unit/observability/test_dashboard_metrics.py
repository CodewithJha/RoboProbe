"""Dashboard series stay inside the metrics registry (T-125)."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[4]


def test_dashboard_metrics_match_registry() -> None:
    script = _REPO / "scripts/check_observability.py"
    subprocess.run([sys.executable, str(script)], check=True)  # noqa: S603


def test_prometheus_auth_slot_is_conditional(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    captured = tmp_path / "args.txt"
    stub = bindir / "prometheus"
    stub.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$CAPTURE"\nexit 0\n',
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    token = tmp_path / "token"
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    env["TMPDIR"] = str(tmp_path)
    env["CAPTURE"] = str(captured)
    env["PROMETHEUS_CONFIG_SRC"] = str(_REPO / "docker/observability/prometheus.yml")
    env["API_TOKEN_FILE"] = str(token)
    script = _REPO / "docker/observability/render_and_run.sh"
    subprocess.run([str(script)], check=True, env=env)  # noqa: S603
    rendered = (tmp_path / "roboprobe-prometheus.yml").read_text(encoding="utf-8")
    assert "authorization:" not in rendered
    token.write_text("secret-token\n", encoding="utf-8")
    subprocess.run([str(script)], check=True, env=env)  # noqa: S603
    rendered = (tmp_path / "roboprobe-prometheus.yml").read_text(encoding="utf-8")
    assert "credentials_file:" in rendered
    assert "\n    # api-auth-slot\n" not in rendered
