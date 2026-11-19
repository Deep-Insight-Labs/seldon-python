"""Typed single-operation declarations; function bodies are never executed."""

import asyncio
import contextvars
import functools
import inspect

from pydantic import ValidationError

from .contract import build
from .errors import SeldonConfigError, SeldonInputError
from .files import bounded_json, digest, resolve_function
from .runtime import Breaker, invoke


class Function:
    def __init__(
        self,
        fn,
        *,
        model=None,
        prompt=None,
        system=None,
        messages=None,
        name=None,
        id=None,
        example=None,
        temperature=0,
        max_tokens=2048,
        **options,
    ):
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
        self.stub = contextvars.ContextVar("seldon_stub", default=None)
        self.is_async = inspect.iscoroutinefunction(fn)

    def bind(self, *args, **kwargs):
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

    def export(self):
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

    async def _call(self, args, kwargs, *, with_info=False):
        inputs = self.bind(*args, **kwargs)
        stub = self.stub.get()
        if stub is not None:
            from .runtime import CallInfo

            result = stub(inputs)
            info = CallInfo(path="stub")
        elif self.options.get("local"):
            from .local import invoke_local

            result, info = await invoke_local(self, inputs)
        else:
            result, info = await invoke(self, inputs, async_mode=self.is_async)
        return (result, info) if with_info else result

    def _dispatch(self, args, kwargs, with_info):
        if self.is_async:
            return self._call(args, kwargs, with_info=with_info)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._call(args, kwargs, with_info=with_info))
        raise SeldonConfigError("sync_function_inside_event_loop")

    async def aclose(self):
        from .local import close_local

        await close_local(self)

    def __call__(self, *args, **kwargs):
        return self._dispatch(args, kwargs, False)

    def call_with_info(self, *args, **kwargs):
        return self._dispatch(args, kwargs, True)


def function(**settings):
    return lambda fn: Function(fn, **settings)
