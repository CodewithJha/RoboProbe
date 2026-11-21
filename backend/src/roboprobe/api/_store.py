"""Lazy access to store records (keeps ``roboprobe.api`` free of direct store imports).

Implements: T-081
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["new_uuid", "records"]


def records() -> Any:
    """Return ``roboprobe.store.records``."""
    return importlib.import_module("roboprobe.store.records")


def new_uuid() -> Any:
    """Return a new UUID from ``roboprobe.store.ids``."""
    return importlib.import_module("roboprobe.store.ids").new_uuid()
