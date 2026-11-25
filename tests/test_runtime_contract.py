"""Logical calls preserve safe diagnostics through success and every failure boundary."""

import asyncio
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import httpx
import pytest
from pydantic import BaseModel, field_validator

import seldon_sdk as seldon
from seldon_sdk.errors import (
    SeldonAuthError,
    SeldonConfigError,
    SeldonContractError,
    SeldonError,
    SeldonInputError,
    SeldonOutputValidationError,
    SeldonSpendError,
)

IDENTITY = "00000000-0000-4000-8000-000000000001"


class Answer(BaseModel):
    label: str

    @field_validator("label")
    @classmethod
    def reject_sentinel(cls, value):
        if value == "private-output":
            raise ValueError("private-output")
        return value


def declaration(client, hook, *, asynchronous=False, **options):
    def sync(value: str) -> Answer: ...

    async def asynchronous_call(value: str) -> Answer: ...

    return seldon.function(
        model="example/model",
        prompt="Label {value}",
        id=IDENTITY,
        api_key="private-key",
        on_call=hook,
        **{"async_http_client" if asynchronous else "http_client": client},
        **options,
    )(asynchronous_call if asynchronous else sync)


def reply(content='{"label":"ok"}'):
    return httpx.Response(
        200,
        headers={"X-Seldon-Contract-Check": "match"},
        json={
            "choices": [{"message": {"content": content}}],
            "seldon": {"revision_id": "revision", "execution_id": "execution"},
        },
    )


@pytest.mark.parametrize("case", ["input", "config", "output", "contract", "success"])
def test_hook_once_and_errors_keep_safe_metadata(case, caplog):
    caplog.set_level(logging.DEBUG)
    calls, sent = [], []

    def handler(request):
        sent.append(request)
        if case == "contract":
            return httpx.Response(
                400,
                json={
                    "error": "invalid_function_request",
                    "param": "messages[0]",
                    "correlation_id": "correlation",
                    "message": "private-output",
                },
            )
        return reply('{"label":"private-output"}' if case == "output" else '{"label":"ok"}')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fn = declaration(client, calls.append)
        if case == "config":
            fn.options["api_key"] = None
        expected = {
            "input": SeldonInputError,
            "config": SeldonConfigError,
            "output": SeldonOutputValidationError,
            "contract": SeldonContractError,
        }
        if case in expected:
            with pytest.raises(expected[case]) as caught:
                fn(3 if case == "input" else "private-input")
            if case == "output":
                assert caught.value.execution_id == "execution"
            if case == "contract":
                assert caught.value.param == "messages[0]"
                assert caught.value.correlation_id == "correlation"
            assert "private-" not in str(caught.value)
        else:
            result, info = fn.call_with_info("private-input")
            assert result.label == "ok" and calls == [info]
        assert len(calls) == 1
        assert calls[0].latency_ms >= 0
        assert len(sent) == (0 if case in {"input", "config"} else 1)
        assert all(
            sentinel not in str(calls) + caplog.text
            for sentinel in ("private-input", "private-output", "private-key")
        )


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "status,code,error",
    [
        (401, "invalid_api_key", SeldonAuthError),
        (403, "forbidden", SeldonAuthError),
        (402, "insufficient_credit", SeldonSpendError),
        (429, "api_key_rate_limit", SeldonError),
        (400, "invalid_function_request", SeldonContractError),
    ],
)
def test_auth_spend_and_input_failures_never_fall_back(asynchronous, status, code, error):
    sent, hooks = [], []

    def handler(request):
        sent.append(request)
        return httpx.Response(status, json={"error": code})

    client_type = httpx.AsyncClient if asynchronous else httpx.Client
    client = client_type(transport=httpx.MockTransport(handler))
    fn = declaration(client, hooks.append, asynchronous=asynchronous)
    with pytest.raises(error):
        if asynchronous:
            asyncio.run(fn("input"))
        else:
            fn("input")
    assert len(sent) == len(hooks) == 1


@pytest.mark.parametrize(
    "status,code,reason",
    [
        (404, "function_not_found", "function_not_found"),
        (404, "revision_not_available", "revision_not_available"),
        (409, "function_disabled", "function_disabled"),
        (409, "execution_disabled", "execution_disabled"),
        (409, "contract_digest_mismatch", "contract_digest_mismatch"),
        (502, "execution_failed", "server_execution_failed"),
        (504, "execution_deadline_exceeded", "server_deadline_exceeded"),
    ],
)
@pytest.mark.parametrize("fallback", ["reference", "never"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_fallback_matrix(status, code, reason, fallback, asynchronous):
    sent, hooks = [], []

    def handler(request):
        sent.append(request)
        if json.loads(request.content)["model"].startswith("seldon/function/"):
            return httpx.Response(status, json={"error": code})
        return reply('{"label":"reference"}')

    client_type = httpx.AsyncClient if asynchronous else httpx.Client
    client = client_type(transport=httpx.MockTransport(handler))
    try:
        fn = declaration(client, hooks.append, fallback=fallback, asynchronous=asynchronous)
        if fallback == "never":
            with pytest.raises(SeldonError):
                asyncio.run(fn("input")) if asynchronous else fn("input")
            assert len(sent) == 1
        else:
            result, info = (
                asyncio.run(fn.call_with_info("input"))
                if asynchronous
                else fn.call_with_info("input")
            )
            assert result.label == "reference" and info.reason == reason
            assert len(sent) == 2
        assert len(hooks) == 1
    finally:
        asyncio.run(client.aclose()) if asynchronous else client.close()


@pytest.mark.parametrize("failure", ["capacity", "in_progress", "connect", "timeout"])
@pytest.mark.asyncio
async def test_retries_share_identity_and_honor_bounded_delay(failure, monkeypatch):
    sent, pauses = [], []

    async def sleep(seconds):
        pauses.append(seconds)

    monkeypatch.setattr("seldon_sdk.runtime.asyncio.sleep", sleep)

    def handler(request):
        sent.append(request)
        if not json.loads(request.content)["model"].startswith("seldon/function/"):
            return reply()
        if failure == "connect":
            raise httpx.ConnectError("private-key", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-input", request=request)
        return httpx.Response(
            429 if failure == "capacity" else 409,
            json={
                "error": "execution_capacity" if failure == "capacity" else "execution_in_progress"
            },
            headers={"Retry-After": "900"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        hooks = []
        fn = declaration(client, hooks.append, asynchronous=True)
        _, info = await fn.call_with_info("input")
    assert info.attempts == 3 and len(sent) == 4 and len(hooks) == 1
    keys = {request.headers["Idempotency-Key"] for request in sent[:3]}
    assert len(keys) == 1 and UUID(keys.pop()).version == 4
    assert len(pauses) == 2 and all(0 <= pause <= 5 for pause in pauses)


def test_pool_reuse_threads_and_repeated_event_loops(monkeypatch):
    from seldon_sdk import runtime

    created = []
    real_client, real_async_client = httpx.Client, httpx.AsyncClient

    def client_factory(**kwargs):
        value = real_client(transport=httpx.MockTransport(lambda request: reply()), **kwargs)
        created.append(value)
        return value

    def async_factory(**kwargs):
        value = real_async_client(transport=httpx.MockTransport(lambda request: reply()), **kwargs)
        created.append(value)
        return value

    monkeypatch.setattr(runtime.httpx, "Client", client_factory)
    monkeypatch.setattr(runtime.httpx, "AsyncClient", async_factory)
    runtime.close()
    fn = declaration(None, lambda info: None)
    barrier = threading.Barrier(20)
    with ThreadPoolExecutor(max_workers=20) as pool:

        def call(_):
            barrier.wait(timeout=5)
            try:
                assert fn("one").label == fn("two").label == "ok"
            finally:
                runtime.close()

        list(pool.map(call, range(20)))
    created.clear()
    async_fn = declaration(None, lambda info: None, asynchronous=True)

    async def batch():
        assert len(await asyncio.gather(*(async_fn("input") for _ in range(100)))) == 100
        await runtime.aclose()

    asyncio.run(batch())
    asyncio.run(batch())
    assert len(created) == 2


@pytest.mark.asyncio
async def test_local_load_failure_and_stub_each_notify_once(monkeypatch):
    import sys
    import types

    from seldon_sdk.testing import stub

    class Runner:
        @classmethod
        async def load(cls, *args, **kwargs):
            raise SeldonConfigError("local_dependency_unavailable")

    monkeypatch.setitem(sys.modules, "seldon_runtime.runner", types.SimpleNamespace(Runner=Runner))
    hooks = []
    fn = declaration(None, hooks.append, asynchronous=True, local=True)
    with pytest.raises(SeldonConfigError):
        await fn("input")
    assert len(hooks) == 1 and hooks[0].path == "local"
    assert hooks[0].reason == "local_dependency_unavailable"
    with stub(fn, returns={"label": "stub"}):
        assert (await fn("input")).label == "stub"
    assert len(hooks) == 2 and hooks[1].path == "stub"


def test_hook_exceptions_do_not_change_result_or_leak_message(caplog):
    def broken(info):
        raise ValueError("private-input private-output private-key")

    with httpx.Client(transport=httpx.MockTransport(lambda request: reply())) as client:
        fn = declaration(client, broken)
        assert fn("private-input").label == "ok"
    assert "call_metadata_hook_failed" in caplog.text and "private-" not in caplog.text


def test_breaker_window_probe_concurrency_and_key_isolation():
    from seldon_sdk.runtime import Breaker

    now = [0.0]
    breaker = Breaker(clock=lambda: now[0])
    other = Breaker(clock=lambda: now[0])
    for _ in range(9):
        breaker.record(True)
    assert breaker.allow() == "normal"
    breaker.record(True)
    assert [breaker.allow() for _ in range(50)] == [False] * 50
    assert other.allow() == "normal"
    now[0] = 61
    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(lambda _: breaker.allow(), range(10)))
    assert outcomes.count("probe") == 1 and outcomes.count(False) == 9
    breaker.record(True, probe=True)
    assert breaker.allow() is False
    now[0] = 122
    assert breaker.allow() == "probe"
    breaker.record(False, probe=True)
    assert breaker.allow() == "normal"
    aged = Breaker(clock=lambda: now[0])
    for _ in range(10):
        aged.record(True)
        now[0] += 40
    assert aged.allow() == "normal"


@pytest.mark.parametrize("kind", ["validator", "invalid_json", "invalid_envelope"])
def test_invalid_function_output_has_one_explicit_reference_fallback(kind):
    sent, hooks = [], []

    def handler(request):
        sent.append(request)
        if len(sent) > 1:
            return reply('{"label":"reference"}')
        if kind == "invalid_json":
            return httpx.Response(200, content="not json")
        if kind == "invalid_envelope":
            return httpx.Response(200, json=[])
        return reply('{"label":"private-output"}')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fn = declaration(client, hooks.append, on_invalid_output="reference")
        result, info = fn.call_with_info("input")
    assert result.label == "reference" and info.reason == "invalid_function_output"
    assert len(sent) == 2 and len(hooks) == 1


def test_drift_raise_preserves_contract_error_metadata_without_fallback():
    sent, hooks = [], []

    def handler(request):
        sent.append(request)
        return httpx.Response(
            409,
            json={
                "error": "contract_digest_mismatch",
                "param": "X-Seldon-Contract-Digest",
                "correlation_id": "correlation",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fn = declaration(client, hooks.append, on_drift="raise")
        with pytest.raises(SeldonContractError) as caught:
            fn("input")
    assert caught.value.code == "contract_digest_mismatch"
    assert caught.value.param == "X-Seldon-Contract-Digest"
    assert caught.value.correlation_id == "correlation"
    assert len(sent) == len(hooks) == 1
