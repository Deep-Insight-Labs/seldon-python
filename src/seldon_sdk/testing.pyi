from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from . import Function

def stub(
    function: Function[..., Any],
    *,
    returns: Any = ...,
    side_effect: BaseException | Callable[..., Any] | None = ...,
) -> AbstractContextManager[list[dict[str, Any]]]: ...
