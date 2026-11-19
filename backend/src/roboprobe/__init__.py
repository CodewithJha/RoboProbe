"""RoboProbe: intelligent, simulation-based robustness testing for autonomous mobile robots.

Layer: package root (no logic). Sub-packages follow the layering in docs/16 §2.
"""

from importlib.metadata import version

__version__: str = version("roboprobe")
"""Installed distribution version (single source of truth: ``backend/pyproject.toml``)."""
