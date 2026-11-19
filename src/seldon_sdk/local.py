"""Typed adapter over the public Runner; it owns eligibility and local fallback."""

import asyncio
import time
import weakref

from .errors import SeldonConfigError, SeldonError, SeldonOutputValidationError
from .files import safe_code
from .runtime import CallInfo, options_for, resolve_identity


async def invoke_local(fn, inputs):
    started = time.monotonic()
    options = options_for(fn)
    identity, reason = resolve_identity(fn)
    if reason:
        raise SeldonConfigError("registered_function_required_for_local_execution")
    try:
        from seldon_runtime.runner import Runner
    except ImportError:
        raise SeldonConfigError("install_seldon_runtime_gliner_extra") from None
    loop = asyncio.get_running_loop()
    if not hasattr(fn, "local_runners"):
        fn.local_runners = weakref.WeakKeyDictionary()
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
    info = CallInfo(path="local", function_id=identity)
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
        info.latency_ms = (time.monotonic() - started) * 1000
        hook = options.get("on_call")
        if hook:
            try:
                hook(info)
            except Exception:
                import logging

                logging.getLogger(__name__).warning("call_metadata_hook_failed")


async def close_local(fn):
    runner = getattr(fn, "local_runners", {}).pop(asyncio.get_running_loop(), None)
    if runner is not None:
        await runner.aclose()
