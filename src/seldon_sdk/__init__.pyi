from collections.abc import Awaitable, Callable
from typing import Any, Generic, ParamSpec, TypeVar, overload

from .runtime import CallInfo as CallInfo

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")

__version__: str

class Function(Generic[P, R]):
    key: str
    id: str | None
    digest: str
    contract: dict[str, Any]
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...
    def export(self) -> dict[str, Any]: ...
    # The sync generic also admits Awaitable; the specialized overload preserves awaited metadata.
    @overload
    def call_with_info(  # type: ignore[overload-overlap]
        self: Function[P, Awaitable[T]], *args: P.args, **kwargs: P.kwargs
    ) -> Awaitable[tuple[T, CallInfo]]: ...
    @overload
    def call_with_info(
        self: Function[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> tuple[T, CallInfo]: ...
    async def aclose(self) -> None: ...

def function(**settings: Any) -> Callable[[Callable[P, R]], Function[P, R]]: ...
def configure(**settings: Any) -> None: ...
def close() -> None: ...
async def aclose() -> None: ...
