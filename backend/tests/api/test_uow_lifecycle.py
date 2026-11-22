"""Request transactions are entered and unwound (T-081b, FR-API-001)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from roboprobe.api.deps import get_uow

pytestmark = pytest.mark.unit


def test_request_enters_and_exits_transaction() -> None:
    uow = MagicMock()
    entered = object()
    uow.__enter__.return_value = entered
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(services=SimpleNamespace(uow_factory=lambda: uow))
        )
    )
    iterator = get_uow(request)
    assert next(iterator) is entered
    with pytest.raises(StopIteration):
        next(iterator)
    uow.__enter__.assert_called_once()
    uow.__exit__.assert_called_once_with(None, None, None)


def test_request_exception_reaches_transaction_exit() -> None:
    uow = MagicMock()
    uow.__exit__.return_value = False
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(services=SimpleNamespace(uow_factory=lambda: uow))
        )
    )
    iterator = get_uow(request)
    next(iterator)
    with pytest.raises(ValueError, match="abort"):
        iterator.throw(ValueError("abort"))
    assert uow.__exit__.call_args.args[0] is ValueError
