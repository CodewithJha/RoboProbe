"""Shared pytest configuration for the RoboProbe backend test suite (docs/18).

Fixtures that are useful across test layers live here; layer-specific fixtures live in the
``conftest.py`` of each test directory. Domain objects come from :mod:`tests.factories`.

Hypothesis profiles (select with ``HYPOTHESIS_PROFILE``; default ``dev``):

* ``dev``: Hypothesis defaults, fast local feedback.
* ``ci``: 200 examples per property, no deadline (shared runners have noisy timing).
* ``nightly``: 2000 examples per property, no deadline.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

HYPOTHESIS_PROFILE_ENV = "HYPOTHESIS_PROFILE"
DEFAULT_HYPOTHESIS_PROFILE = "dev"
CI_MAX_EXAMPLES = 200
NIGHTLY_MAX_EXAMPLES = 2000

settings.register_profile(DEFAULT_HYPOTHESIS_PROFILE)
settings.register_profile(
    "ci",
    max_examples=CI_MAX_EXAMPLES,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    max_examples=NIGHTLY_MAX_EXAMPLES,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get(HYPOTHESIS_PROFILE_ENV, DEFAULT_HYPOTHESIS_PROFILE))
