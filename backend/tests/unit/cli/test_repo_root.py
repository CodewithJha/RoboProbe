"""Repository-root discovery used by the containerised CLI (T-047)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.cli.space import REPO_ROOT, discover_repo_root
from roboprobe.scenario.repo_root import resolve_repo_path

pytestmark = pytest.mark.unit


def test_repo_root_sees_shipped_scenario_spaces() -> None:
    assert (REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml").is_file()


def test_resolve_repo_path_uses_repo_root_for_relative_config() -> None:
    rel = Path("configs/backends/kinematic2d_v1.yaml")
    resolved = resolve_repo_path(rel)
    assert resolved == (REPO_ROOT / rel).resolve()
    assert resolved.is_file()


def test_resolve_repo_path_prefers_existing_absolute(tmp_path: Path) -> None:
    direct = tmp_path / "model.yaml"
    direct.write_text("{}", encoding="utf-8")
    assert resolve_repo_path(direct) == direct.resolve()


def test_discover_falls_back_to_cwd_when_package_is_not_in_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "app"
    (app / "configs" / "scenario_spaces").mkdir(parents=True)
    nested = tmp_path / "site-packages" / "roboprobe" / "cli" / "space.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("", encoding="utf-8")
    monkeypatch.chdir(app)
    assert discover_repo_root(nested) == app.resolve()
