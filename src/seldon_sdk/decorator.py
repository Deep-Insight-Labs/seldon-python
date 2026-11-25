"""Typed single-operation declarations; function bodies are never executed."""

import asyncio
import contextvars
import functools
import inspect
import time
import weakref
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .contract import build
from .errors import SeldonConfigError, SeldonError, SeldonInputError
from .files import bounded_json, digest, resolve_function
from .runtime import Breaker, CallInfo, invoke, notify_call


class Function:
    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        model: str | None = None,
        prompt: str | None = None,
        system: str | None = None,
        messages: list[tuple[str, str]] | None = None,
        name: str | None = None,
        id: str | None = None,
        example: dict[str, Any] | None = None,
        temperature: float = 0,
        max_tokens: int = 2048,
        **options: Any,
    ) -> None:
        functools.update_wrapper(self, fn)
        self.original = fn
        self.signature, self.inputs, self.output, self.contract, self.strict_reasons = build(
            fn,
            model=model,
            prompt=prompt,
            system=system,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.digest = digest(self.contract)
        self.key = name or fn.__module__ + ":" + fn.__qualname__
        self.id = resolve_function(id) if id else None
        self.example = example
        self.options = options
        self.breaker = Breaker()
        self.stub: contextvars.ContextVar[Callable[[dict[str, Any]], Any] | None] = (
            contextvars.ContextVar("seldon_stub", default=None)
        )
        self.local_runners: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any] = (
            weakref.WeakKeyDictionary()
        )
        self.is_async = inspect.iscoroutinefunction(fn)

    def bind(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            values = self.signature.bind(*args, **kwargs)
            values.apply_defaults()
            result = self.inputs.model_validate(values.arguments, strict=True).model_dump(
                mode="json"
            )
            bounded_json(result)
            return result
        except (TypeError, ValueError, ValidationError):
            raise SeldonInputError("invalid_function_inputs") from None

    def export(self) -> dict[str, Any]:
        if self.example is None:
            raise SeldonInputError("example_required")
        example = self.inputs.model_validate(self.example, strict=True).model_dump(mode="json")
        return {
            "kind": "sdk",
            "key": self.key,
            "contract": self.contract,
            "digest": self.digest,
            "example_inputs": example,
        }

    async def _call(
        self, args: tuple[Any, ...], kwargs: dict[str, Any], *, with_info: bool = False
    ) -> Any:
        started = time.monotonic()
        stub = self.stub.get()
        info = CallInfo(
            path="stub"
            if stub is not None
            else "local"
            if self.options.get("local")
            else "function",
            function_id=self.id,
        )
        try:
            inputs = self.bind(*args, **kwargs)
            if stub is not None:
                result = stub(inputs)
            elif self.options.get("local"):
                from .local import invoke_local

                result, info = await invoke_local(self, inputs, info=info)
            else:
                result, info = await invoke(self, inputs, async_mode=self.is_async, info=info)
            return (result, info) if with_info else result
        except SeldonError as error:
            info.reason = info.reason or error.code
            raise
        finally:
            notify_call(self, info, started)

    def _dispatch(self, args: tuple[Any, ...], kwargs: dict[str, Any], with_info: bool) -> Any:
        if self.is_async:
            return self._call(args, kwargs, with_info=with_info)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._call(args, kwargs, with_info=with_info))
        info = CallInfo(reason="sync_function_inside_event_loop", function_id=self.id)
        notify_call(self, info, time.monotonic())
        raise SeldonConfigError("sync_function_inside_event_loop")

    async def aclose(self) -> None:
        from .local import close_local

        await close_local(self)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._dispatch(args, kwargs, False)

    def call_with_info(self, *args: Any, **kwargs: Any) -> Any:
        return self._dispatch(args, kwargs, True)


def function(**settings: Any) -> Callable[[Callable[..., Any]], Function]:
    return lambda fn: Function(fn, **settings)
