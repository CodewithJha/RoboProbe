"""Repository-root discovery used by the containerised CLI (T-047)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.cli.space import REPO_ROOT, discover_repo_root

pytestmark = pytest.mark.unit


def test_repo_root_sees_shipped_scenario_spaces() -> None:
    assert (REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml").is_file()


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
