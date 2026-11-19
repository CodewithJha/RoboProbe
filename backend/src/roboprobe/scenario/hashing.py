"""Canonical JSON and content hashes (docs/05 §3, FR-SCN-006).

``canonical_json`` is the single serialisation behind every content hash in RoboProbe: space
versions, SUT-profile config hashes and scenario hashes. The rules make the bytes independent of
key order, process and platform:

* mappings: keys sorted (``str`` keys only; two keys may not stringify the same), compact
  separators, UTF-8 without ASCII escaping;
* floats: rounded to 12 significant digits (``format(x, ".12g")``), ``-0.0`` becomes ``0.0`` and
  NaN/inf are rejected, then written by Python's shortest round-trip ``repr``;
* ints stay ints (``1`` and ``1.0`` serialise differently, so callers normalise types first, as
  ``ScenarioSpace.make_scenario`` does); ``bool``, ``None`` and ``str`` are JSON natives;
* lists and tuples become JSON arrays; any other type is rejected rather than guessed.

``scenario_hash = sha256(canonical_json({"space_version": v, "values": values}))[:16]``.

Changing any rule changes every stored hash: treat this module as a versioned contract
(docs/33 §6) and never edit it to make a golden test pass.

Implements: FR-SCN-006
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Final

from roboprobe.core import errors

__all__ = [
    "FLOAT_SIGNIFICANT_DIGITS",
    "SCENARIO_HASH_HEX_CHARS",
    "canonical_json",
    "content_hash",
    "scenario_hash",
]

FLOAT_SIGNIFICANT_DIGITS: Final = 12
"""Significant digits kept for floats; absorbs last-bit noise between platforms."""
SCENARIO_HASH_HEX_CHARS: Final = 16
"""Length of a scenario hash (64 bits: collision-free for any realistic number of runs)."""


def canonical_json(obj: object) -> bytes:
    """Serialise ``obj`` to canonical JSON bytes (see the module rules).

    Raises:
        roboprobe.core.errors.ValidationError: For non-finite floats, unsupported types or keys
            that collide once converted to strings.
    """
    return json.dumps(
        _canonical(obj, "$"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_hash(obj: object, *, length: int | None = None) -> str:
    """Hex SHA-256 of :func:`canonical_json`, optionally truncated to ``length`` characters."""
    digest = hashlib.sha256(canonical_json(obj)).hexdigest()
    return digest if length is None else digest[:length]


def scenario_hash(space_version: str, values: Mapping[str, object]) -> str:
    """Hash identifying a scenario: its space version plus its parameter values.

    ``values`` should already be type-normalised (see ``ScenarioSpace.make_scenario``).
    """
    payload = {"space_version": space_version, "values": dict(values)}
    return content_hash(payload, length=SCENARIO_HASH_HEX_CHARS)


def _canonical(value: object, path: str) -> object:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _unsupported(path, f"non-finite float {value!r}")
        rounded = float(format(value, f".{FLOAT_SIGNIFICANT_DIGITS}g"))
        return 0.0 if rounded == 0 else rounded
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            if name in result:
                raise _unsupported(path, f"keys collide as {name!r}")
            result[name] = _canonical(item, f"{path}.{name}")
        return result
    if isinstance(value, list | tuple):
        return [_canonical(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise _unsupported(path, f"unsupported type {type(value).__name__}")


def _unsupported(path: str, reason: str) -> errors.ValidationError:
    msg = f"cannot canonicalise {path}: {reason}"
    return errors.ValidationError(msg, context={"path": path, "reason": reason})
