"""Hierarchical, platform-independent seed derivation (docs/21 §3, ADR-0014).

Every random stream in RoboProbe descends from one campaign seed through a path of stable keys,
e.g. ``derive_seed(campaign_seed, RUN, ordinal, SENSOR)``. Derivation is a pure function of
``(root, path)``: it never uses Python's per-process salted ``hash()``, global RNG state or the
platform, so seeds are identical across processes, machines and operating systems.

The golden values pinned in ``tests/unit/core/test_seeding.py`` are part of the reproducibility
contract; changing them is a breaking change (docs/33 §6).

Layer: Kernel (L1).

Implements: FR-REP-002, NFR-REP-001
"""

from __future__ import annotations

import hashlib
from typing import Final

import numpy as np

__all__ = [
    "ANALYSIS",
    "LOCALIZATION",
    "PERCEPTION",
    "REP",
    "RUN",
    "SEED_BITS",
    "SEED_MAX",
    "SENSOR",
    "SIMULATOR",
    "STRATEGY",
    "derive_seed",
    "make_rng",
    "random_campaign_seed",
    "stable_hash",
]

# --- Canonical stream keys (identifiers, not tunables) -----------------------------------------
STRATEGY: Final = "strategy"
"""Top-level stream consumed by the selection strategy."""
RUN: Final = "run"
"""Top-level per-run stream; path continues with the run ordinal (and repeat index)."""
ANALYSIS: Final = "analysis"
"""Top-level stream for stochastic analysis steps (clustering, bootstrap)."""
REP: Final = "rep"
"""Experiment replicate stream: ``campaign_seed = derive_seed(experiment_seed, REP, k)``."""
SENSOR: Final = "sensor"
"""Run sub-stream for sensor noise and dropout models."""
PERCEPTION: Final = "perception"
"""Run sub-stream for perception degradation models."""
LOCALIZATION: Final = "localization"
"""Run sub-stream for the kinematic2d localisation model."""
SIMULATOR: Final = "simulator"
"""Run sub-stream forwarded to the simulator (Gazebo ``--seed``, ROS node parameters)."""

# --- Seed domain ---------------------------------------------------------------------------------
SEED_BITS: Final = 63
"""Seeds are non-negative 63-bit integers so they fit a signed 64-bit DB column."""
SEED_MAX: Final = (1 << SEED_BITS) - 1
"""Largest valid seed; also the mask applied to derived 64-bit state."""
_HASH_BYTES: Final = 4
"""Bytes of the SHA-256 digest kept by :func:`stable_hash` (one 32-bit spawn-key word)."""


def stable_hash(part: str | int) -> int:
    """Map a path component to a 32-bit integer, identically on every process and platform.

    The component is canonicalised before hashing so that ``3`` and ``"3"`` differ, and ``str``
    or ``int`` subclasses (e.g. ``StrEnum``/``IntEnum`` members) hash like their plain value.

    Args:
        part: A path component: a stream key or an index such as a run ordinal.

    Returns:
        The first 4 bytes of ``SHA-256(repr(canonical part))`` as a big-endian unsigned integer.
    """
    canonical = repr(int(part)) if isinstance(part, int) else repr(str(part))
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return int.from_bytes(digest[:_HASH_BYTES], byteorder="big")


def derive_seed(root: int, *path: str | int) -> int:
    """Derive a child seed from ``root`` along ``path`` (docs/21 §3).

    Args:
        root: Non-negative root seed, typically the campaign or experiment seed.
        *path: Stream keys and indices, e.g. ``(RUN, ordinal, SENSOR)``. An empty path derives the
            root stream itself.

    Returns:
        A seed in ``[0, SEED_MAX]``.

    Raises:
        ValueError: If ``root`` is negative (raised by :class:`numpy.random.SeedSequence`).
    """
    spawn_key = tuple(stable_hash(part) for part in path)
    state = np.random.SeedSequence(root, spawn_key=spawn_key).generate_state(1, np.uint64)
    return int(state[0]) & SEED_MAX


def make_rng(root: int, *path: str | int) -> np.random.Generator:
    """Build an independent PCG64 generator for the stream at ``(root, *path)``.

    Args:
        root: Non-negative root seed.
        *path: Stream keys and indices, as for :func:`derive_seed`.

    Returns:
        A fresh :class:`numpy.random.Generator`; equal arguments give identical streams.
    """
    return np.random.Generator(np.random.PCG64(derive_seed(root, *path)))


def random_campaign_seed(rng: np.random.Generator) -> int:
    """Draw a fresh campaign seed when the user did not supply one.

    Args:
        rng: Injected entropy source (``np.random.default_rng()`` at the composition root).

    Returns:
        A uniformly distributed seed in ``[0, SEED_MAX]``.
    """
    return int(rng.integers(0, SEED_MAX, endpoint=True, dtype=np.uint64))
