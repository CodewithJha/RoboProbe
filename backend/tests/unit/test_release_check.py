"""Release tag consistency (T-124) and pinned release workflows (T-119, T-124)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "release_check.py"
_SHA = re.compile(r"@[0-9a-f]{40}")


def _checker():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("release_check", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(root: Path, *, py: str, web: str, changelog: str, ros: str | None = None) -> None:
    (root / "backend").mkdir()
    (root / "backend/pyproject.toml").write_text(
        f'[project]\nname = "roboprobe"\nversion = "{py}"\n',
        encoding="utf-8",
    )
    (root / "web").mkdir()
    (root / "web/package.json").write_text(
        f'{{"name": "roboprobe", "version": "{web}"}}\n',
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    if ros is not None:
        pkg = root / "ros_ws/src/roboprobe_ros"
        pkg.mkdir(parents=True)
        (pkg / "package.xml").write_text(
            f"<package><version>{ros}</version></package>\n",
            encoding="utf-8",
        )


def test_matching_tag_and_prerelease(tmp_path: Path) -> None:
    checker = _checker()
    changelog = "## [0.10.0] - 2026-11-21\n\n- notes\n\n## [0.9.0] - 2026-01-01\n\n- old\n"
    _tree(tmp_path, py="0.10.0", web="0.10.0", changelog=changelog, ros="0.10.0")
    assert checker.problems(tmp_path, "v0.10.0") == []
    assert checker.problems(tmp_path, "v0.10.0-rc.1") == []
    notes = checker.changelog_section(changelog, "0.10.0")
    assert notes is not None
    assert "notes" in notes
    assert "old" not in notes


def test_version_mismatch_and_bad_tag(tmp_path: Path) -> None:
    checker = _checker()
    _tree(
        tmp_path,
        py="0.0.1",
        web="0.0.0",
        changelog="## [Unreleased]\n\n- wip\n",
    )
    found = checker.problems(tmp_path, "v0.0.1")
    assert any("package.json" in line for line in found)
    assert any("CHANGELOG" in line for line in found)
    assert checker.problems(tmp_path, "1.0.0") == ["tag '1.0.0' is not vX.Y.Z or vX.Y.Z-<pre>"]


def test_release_workflows_pin_actions() -> None:
    for name in ("release.yml", "images.yml"):
        text = (_REPO / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "permissions:" in text
        for line in text.splitlines():
            if "uses:" not in line or "uses: ./" in line:
                continue
            assert _SHA.search(line), line
    release = (_REPO / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "release_check.py" in release
    assert "images.yml" in release
    images = (_REPO / ".github/workflows/images.yml").read_text(encoding="utf-8")
    assert "docker/backend.Dockerfile" in images
    assert "push: false" in images or "pull_request" in images
