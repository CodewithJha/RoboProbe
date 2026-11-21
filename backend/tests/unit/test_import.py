"""Smoke test: every sub-package from docs/16 §1 is importable and documents its layer."""

import importlib
import pkgutil

import pytest

import roboprobe

EXPECTED_SUBPACKAGES = (
    "analysis",
    "api",
    "backends",
    "bootstrap",
    "cli",
    "core",
    "experiments",
    "geometry",
    "metrics",
    "observability",
    "oracles",
    "perturbation",
    "reporting",
    "risk",
    "runner",
    "scenario",
    "selection",
    "store",
)


@pytest.mark.unit
@pytest.mark.parametrize("name", EXPECTED_SUBPACKAGES)
def test_subpackage_importable_and_documents_layer(name: str) -> None:
    module = importlib.import_module(f"roboprobe.{name}")
    assert module.__doc__ is not None
    assert "Layer:" in module.__doc__


@pytest.mark.unit
def test_package_tree_matches_docs() -> None:
    found = {m.name for m in pkgutil.iter_modules(roboprobe.__path__) if m.ispkg}
    assert found == set(EXPECTED_SUBPACKAGES)


@pytest.mark.unit
def test_version_is_exposed() -> None:
    assert roboprobe.__version__
