"""Unit and property tests for :mod:`roboprobe.core.seeding` (docs/21 §3, ADR-0014).

The golden tables below are part of the reproducibility contract (docs/33 §6): a failing golden
test means previously recorded campaigns can no longer be replayed bit-identically. Never update
the values to make a test pass; bump the result-comparability version instead.
"""

from __future__ import annotations

import enum
import json
import os
import subprocess
import sys

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from roboprobe.core import seeding
from roboprobe.core.seeding import (
    ANALYSIS,
    LOCALIZATION,
    PERCEPTION,
    REP,
    RUN,
    SEED_MAX,
    SENSOR,
    SIMULATOR,
    STRATEGY,
    derive_seed,
    make_rng,
    random_campaign_seed,
    stable_hash,
)

pytestmark = pytest.mark.unit

GOLDEN_SEEDS: list[tuple[int, tuple[str | int, ...], int]] = [
    (0, (), 6569863346532939966),
    (0, ("strategy",), 3714907126623775481),
    (42, ("run", 0), 6657448210282831315),
    (42, ("run", 1), 326514687914082212),
    (42, ("run", 0, "sensor"), 8216174235176360836),
    (42, ("run", "0"), 7238091361614901045),
    (123456789, ("rep", 3), 352841044370555947),
    (SEED_MAX, ("analysis", 100), 7855531120722969300),
    (7, ("run", 5, 2, "simulator"), 5912394739960247245),
]

GOLDEN_HASHES: list[tuple[str | int, int]] = [("run", 2812295795), (0, 1609362278)]

path_parts = st.one_of(st.text(max_size=16), st.integers(min_value=-(2**70), max_value=2**70))
roots = st.integers(min_value=0, max_value=SEED_MAX)


class _Stream(enum.StrEnum):
    RUN = "run"


class _Index(enum.IntEnum):
    ZERO = 0


@pytest.mark.parametrize(("root", "path", "expected"), GOLDEN_SEEDS)
def test_derive_seed_matches_golden_values(
    root: int, path: tuple[str | int, ...], expected: int
) -> None:
    assert derive_seed(root, *path) == expected


@pytest.mark.parametrize(("part", "expected"), GOLDEN_HASHES)
def test_stable_hash_matches_golden_values(part: str | int, expected: int) -> None:
    assert stable_hash(part) == expected


def test_golden_values_identical_in_a_fresh_interpreter() -> None:
    """Python's salted ``hash()`` would differ per process; ours must not."""
    script = (
        "import json, sys; from roboprobe.core.seeding import derive_seed; "
        "cases = json.loads(sys.stdin.read()); "
        "print(json.dumps([derive_seed(r, *p) for r, p, _ in cases]))"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and inline script, no user input
        [sys.executable, "-c", script],
        input=json.dumps(GOLDEN_SEEDS),
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "random"},
    )
    assert json.loads(result.stdout) == [expected for _, _, expected in GOLDEN_SEEDS]


def test_int_and_str_components_are_distinct() -> None:
    assert stable_hash(0) != stable_hash("0")
    assert derive_seed(42, RUN, 0) != derive_seed(42, RUN, "0")


def test_enum_members_hash_like_their_values() -> None:
    assert stable_hash(_Stream.RUN) == stable_hash("run")
    assert stable_hash(_Index.ZERO) == stable_hash(0)


def test_path_order_matters() -> None:
    assert derive_seed(1, RUN, SENSOR) != derive_seed(1, SENSOR, RUN)


def test_stream_keys_are_unique() -> None:
    keys = [STRATEGY, RUN, ANALYSIS, REP, SENSOR, PERCEPTION, LOCALIZATION, SIMULATOR]
    assert len({stable_hash(key) for key in keys}) == len(keys)


def test_negative_root_is_rejected() -> None:
    with pytest.raises(ValueError):
        derive_seed(-1, RUN)


@pytest.mark.property
@given(root=roots, path=st.lists(path_parts, max_size=5))
def test_derive_seed_is_deterministic_and_63_bit(root: int, path: list[str | int]) -> None:
    seed = derive_seed(root, *path)
    assert seed == derive_seed(root, *path)
    assert 0 <= seed <= SEED_MAX


@pytest.mark.property
@given(part=path_parts)
def test_stable_hash_fits_32_bits(part: str | int) -> None:
    assert 0 <= stable_hash(part) < 2**32


def test_no_collisions_over_many_random_paths() -> None:
    """100 000 distinct paths must map to 100 000 distinct seeds (acceptance criterion)."""
    n_paths = 100_000
    rng = np.random.default_rng(0)
    ordinals = rng.choice(10 * n_paths, size=n_paths, replace=False)
    keys = rng.choice([STRATEGY, RUN, ANALYSIS, REP], size=n_paths)
    seeds = {
        derive_seed(7, str(key), int(ordinal)) for key, ordinal in zip(keys, ordinals, strict=True)
    }
    assert len(seeds) == n_paths


def test_make_rng_streams_are_reproducible_and_independent() -> None:
    first = make_rng(42, RUN, 0, SENSOR).random(8)
    again = make_rng(42, RUN, 0, SENSOR).random(8)
    other = make_rng(42, RUN, 0, PERCEPTION).random(8)
    np.testing.assert_array_equal(first, again)
    assert not np.array_equal(first, other)


def test_make_rng_uses_the_derived_seed() -> None:
    expected = np.random.Generator(np.random.PCG64(derive_seed(3, RUN, 1))).integers(0, 1000, 5)
    np.testing.assert_array_equal(make_rng(3, RUN, 1).integers(0, 1000, 5), expected)


@pytest.mark.property
@given(entropy=st.integers(min_value=0, max_value=2**128))
def test_random_campaign_seed_is_63_bit_and_driven_by_rng(entropy: int) -> None:
    seed = random_campaign_seed(np.random.default_rng(entropy))
    assert isinstance(seed, int)
    assert 0 <= seed <= SEED_MAX
    assert seed == random_campaign_seed(np.random.default_rng(entropy))


def test_public_api_is_exported() -> None:
    assert set(seeding.__all__) <= set(dir(seeding))
