"""Context-local typed stubs; application tests make no network requests."""

from contextlib import contextmanager

from pydantic import ValidationError

from .errors import SeldonOutputValidationError


@contextmanager
def stub(function, *, returns=None, side_effect=None):
    calls = []
    try:
        expected = function.output.validate_python(returns) if side_effect is None else None
    except ValidationError:
        raise SeldonOutputValidationError("invalid_stub_output") from None

    def invoke(inputs):
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
