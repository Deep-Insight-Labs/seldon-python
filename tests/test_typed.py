import json

import httpx
import pytest
from pydantic import BaseModel

import seldon_sdk as seldon
from seldon_sdk.errors import SeldonAuthError, SeldonContractError, SeldonInputError


class Answer(BaseModel):
    label: str


def test_contract_render_and_output():
    from seldon_sdk.contract import render

    @seldon.function(model="example/model", prompt="Label {value}", example={"value": True})
    def classify(value: bool) -> Answer: ...

    assert render(classify.contract, {"value": True}) == [{"role": "user", "content": "Label true"}]
    assert classify.export()["kind"] == "sdk"
    assert classify.contract["max_tokens"] == 2048


@pytest.mark.parametrize(
    "template", ["{value:.2f}", "{value!r}", "{value.x}", "{value} {value}", "{{value}}"]
)
def test_unsupported_templates_fail_at_decoration(template):
    with pytest.raises(SeldonContractError):

        @seldon.function(model="example/model", prompt=template)
        def classify(value: str) -> Answer: ...


def test_sync_function_wire_and_auth_fail_closed():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"label":"ok"}'}}],
                "seldon": {"revision_id": "revision"},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    @seldon.function(
        model="example/model",
        prompt="Label {value}",
        id="00000000-0000-4000-8000-000000000001",
        api_key="secret",
        http_client=client,
    )
    def classify(value: str) -> Answer: ...

    result, info = classify.call_with_info("sample")
    assert result == Answer(label="ok")
    body = json.loads(requests[0].content)
    assert body == {
        "model": "seldon/function/00000000-0000-4000-8000-000000000001",
        "messages": [{"role": "user", "content": '{"value":"sample"}'}],
    }
    assert requests[0].headers["x-seldon-contract-digest"] == classify.digest
    assert info.revision_id == "revision"
    with pytest.raises(SeldonInputError):
        classify(3)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_async_retry_identity_and_reference_policy():
    requests = []

    async def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        if body["model"].startswith("seldon/function/"):
            return httpx.Response(
                429, json={"error": "execution_capacity"}, headers={"Retry-After": "0"}
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"label":"reference"}'}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:

        @seldon.function(
            model="example/model",
            prompt="Label {value}",
            id="00000000-0000-4000-8000-000000000001",
            api_key="secret",
            async_http_client=client,
        )
        async def classify(value: str) -> Answer: ...

        result, info = await classify.call_with_info("sample")
        assert result.label == "reference"
        assert info.attempts == 3
        assert len({request.headers["idempotency-key"] for request in requests[:3]}) == 1
        assert len(requests) == 4


def test_auth_failure_never_falls_back():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, json={"error": "invalid_api_key", "message": "secret"})

    @seldon.function(
        model="example/model",
        prompt="Label {value}",
        id="00000000-0000-4000-8000-000000000001",
        api_key="secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    def classify(value: str) -> Answer: ...

    with pytest.raises(SeldonAuthError):
        classify("sample")
    assert len(requests) == 1


def test_stub_validates_and_restores():
    from seldon_sdk.testing import stub

    @seldon.function(model="example/model", prompt="Label {value}")
    def classify(value: str) -> Answer: ...

    with stub(classify, returns={"label": "stub"}) as calls:
        assert classify("sample").label == "stub"
        assert calls == [{"value": "sample"}]


def test_circuit_breaker_half_open_probe_is_exclusive():
    from seldon_sdk.runtime import Breaker

    now = [0]
    breaker = Breaker(clock=lambda: now[0])
    assert breaker.allow() == "normal"
    for _ in range(10):
        breaker.record(True)
    assert breaker.allow() is False
    now[0] = 61
    assert breaker.allow() == "probe"
    assert breaker.allow() is False
    breaker.record(False, probe=True)
    assert breaker.allow() == "normal"
