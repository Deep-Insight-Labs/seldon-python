"""Context-local typed stubs; application tests make no network requests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .decorator import Function

from pydantic import ValidationError

from .errors import SeldonOutputValidationError


@contextmanager
def stub(
    function: Function,
    *,
    returns: Any = None,
    side_effect: BaseException | Callable[..., Any] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    calls = []
    try:
        expected = function.output.validate_python(returns) if side_effect is None else None
    except ValidationError:
        raise SeldonOutputValidationError("invalid_stub_output") from None

    def invoke(inputs: dict[str, Any]) -> Any:
        calls.append(inputs)
        if isinstance(side_effect, BaseException):
            raise side_effect
        value = side_effect(**inputs) if callable(side_effect) else expected
        try:
            return function.output.validate_python(value)
        except ValidationError:
            raise SeldonOutputValidationError("invalid_stub_output") from None

    token = function.stub.set(invoke)
    try:
        yield calls
    finally:
        function.stub.reset(token)
