"""Typed adapter over the public Runner; it owns eligibility and local fallback."""

import asyncio
import importlib
from typing import TYPE_CHECKING, Any

from .errors import SeldonConfigError, SeldonError, SeldonOutputValidationError
from .files import safe_code
from .runtime import CallInfo, options_for, resolve_identity

if TYPE_CHECKING:
    from .decorator import Function


async def invoke_local(
    fn: "Function", inputs: dict[str, Any], *, info: CallInfo
) -> tuple[Any, CallInfo]:
    options = options_for(fn)
    identity, reason = resolve_identity(fn)
    if reason:
        raise SeldonConfigError("registered_function_required_for_local_execution")
    try:
        Runner = importlib.import_module("seldon_runtime.runner").Runner
    except ImportError:
        raise SeldonConfigError("install_seldon_runtime_gliner_extra") from None
    loop = asyncio.get_running_loop()
    runner = fn.local_runners.get(loop)
    if runner is None:
        # load() includes eligibility, integrity and conformance checks. Never opt out here.
        runner = await Runner.load(
            identity,
            options["api_key"],
            base_url=options["base_url"].removesuffix("/v1"),
            fallback=fn.options.get("local_fallback", "seldon"),
            telemetry=fn.options.get("telemetry", True),
        )
        fn.local_runners[loop] = runner
    info.function_id = identity
    try:
        result = await runner(inputs)
        info.revision_id = runner.status()["revision_id"]
        info.server_fallback_used = result["fallback_used"]
        info.reason = result["fallback_reason"]
        try:
            output = fn.output.validate_python(result["output"], strict=True)
        except ValueError:
            raise SeldonOutputValidationError("invalid_local_output") from None
        return output, info
    except SeldonError:
        raise
    except Exception as exc:
        raise SeldonError(safe_code(str(exc), "local_execution_unavailable")) from None
    finally:
        if not fn.is_async:
            await runner.aclose()
            fn.local_runners.pop(loop, None)


async def close_local(fn: "Function") -> None:
    runner = getattr(fn, "local_runners", {}).pop(asyncio.get_running_loop(), None)
    if runner is not None:
        await runner.aclose()
