"""Unit tests for :mod:`roboprobe.core.errors` (docs/34 §5, docs/12 §1.1)."""

from __future__ import annotations

import pickle

import pytest

from roboprobe.core import errors as errors_module
from roboprobe.core.errors import (
    API_ERROR_CODES,
    BackendError,
    ConfigError,
    ConflictError,
    EpisodeLaunchError,
    EpisodeTimeoutError,
    ErrorCode,
    ModelFitError,
    NotFoundError,
    OracleError,
    PluginError,
    QueueError,
    RoboProbeError,
    StoreError,
    StrategyError,
    ValidationError,
    is_transient,
)

pytestmark = pytest.mark.unit

ALL_ERRORS = [
    RoboProbeError, ConfigError, ValidationError, NotFoundError, ConflictError, BackendError,
    EpisodeLaunchError, EpisodeTimeoutError, OracleError, StrategyError, ModelFitError,
    StoreError, QueueError, PluginError,
]  # fmt: skip


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (ConfigError, RoboProbeError),
        (ValidationError, RoboProbeError),
        (NotFoundError, RoboProbeError),
        (ConflictError, RoboProbeError),
        (BackendError, RoboProbeError),
        (EpisodeLaunchError, BackendError),
        (EpisodeTimeoutError, BackendError),
        (OracleError, RoboProbeError),
        (StrategyError, RoboProbeError),
        (ModelFitError, StrategyError),
        (StoreError, RoboProbeError),
        (QueueError, StoreError),
        (PluginError, RoboProbeError),
        (RoboProbeError, Exception),
    ],
)
def test_hierarchy_matches_doc_34(child: type[Exception], parent: type[Exception]) -> None:
    assert child.__mro__[1] is parent


def test_api_envelope_codes_exist() -> None:
    documented = {
        "VALIDATION_ERROR", "NOT_FOUND", "CAMPAIGN_INVALID_TRANSITION", "SPACE_INVALID",
        "BACKEND_UNSUPPORTED_PARAM", "NO_WORKERS", "PRECONDITION_FAILED", "UNAUTHORIZED",
        "INTERNAL",
    }  # fmt: skip
    assert {c.value for c in API_ERROR_CODES} == documented
    assert documented <= {c.value for c in ErrorCode}


def test_every_error_has_a_distinct_default_code() -> None:
    codes = [cls.default_code for cls in ALL_ERRORS]
    assert len(set(codes)) == len(codes)
    assert ValidationError("x").code is ErrorCode.VALIDATION_ERROR
    assert NotFoundError("x").code is ErrorCode.NOT_FOUND
    assert RoboProbeError("x").code is ErrorCode.INTERNAL


def test_code_override_message_and_str() -> None:
    err = ConflictError(
        "Campaign 0193 is COMPLETED; cannot pause.",
        code=ErrorCode.CAMPAIGN_INVALID_TRANSITION,
        context={"from": "COMPLETED", "command": "pause"},
    )
    assert err.code is ErrorCode.CAMPAIGN_INVALID_TRANSITION
    assert err.message == "Campaign 0193 is COMPLETED; cannot pause."
    assert str(err) == "CAMPAIGN_INVALID_TRANSITION: Campaign 0193 is COMPLETED; cannot pause."
    assert "ConflictError(" in repr(err)
    assert "'command': 'pause'" in repr(err)


def test_code_accepts_string_value() -> None:
    assert ValidationError("bad", code="SPACE_INVALID").code is ErrorCode.SPACE_INVALID  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="NOPE"):
        ValidationError("bad", code="NOPE")  # type: ignore[arg-type]


def test_context_is_copied_and_read_only() -> None:
    source = {"run_id": "r1"}
    err = BackendError("boom", context=source)
    source["run_id"] = "changed"
    assert err.context == {"run_id": "r1"}
    with pytest.raises(TypeError):
        err.context["x"] = 1  # type: ignore[index]
    assert RoboProbeError("no context").context == {}


@pytest.mark.parametrize("cls", ALL_ERRORS)
def test_errors_pickle_round_trip(cls: type[RoboProbeError]) -> None:
    err = cls("msg", context={"k": [1, 2], "n": None}, transient=True)
    clone = pickle.loads(pickle.dumps(err))  # noqa: S301 - round-tripping our own object
    assert type(clone) is cls
    assert (clone.code, clone.message, dict(clone.context), clone.transient) == (
        err.code, err.message, dict(err.context), True,
    )  # fmt: skip
    assert str(clone) == str(err)


def test_is_transient() -> None:
    assert is_transient(EpisodeLaunchError("gz did not start"))
    assert not is_transient(EpisodeLaunchError("bad world", transient=False))
    assert is_transient(StoreError("serialization failure", transient=True))
    assert not is_transient(StoreError("constraint violated"))
    assert not is_transient(ValidationError("bad"))
    assert not is_transient(TimeoutError("foreign"))


def test_module_exports() -> None:
    assert set(errors_module.__all__) == {cls.__name__ for cls in ALL_ERRORS} | {
        "API_ERROR_CODES", "ErrorCode", "is_transient",
    }  # fmt: skip
