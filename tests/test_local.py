import sys
import types

import pytest
from pydantic import BaseModel

import seldon_sdk as seldon


class Result(BaseModel):
    label: str


@pytest.mark.asyncio
async def test_local_handle_delegates_eligibility_and_closes(monkeypatch):
    events = []

    class Runner:
        @classmethod
        async def load(cls, identity, key, **kwargs):
            events.append(("load", identity, kwargs))
            assert not kwargs.get("allow_unverified")
            return cls()

        async def __call__(self, inputs):
            events.append(("call", inputs))
            return {"output": {"label": "local"}, "fallback_used": False, "fallback_reason": None}

        def status(self):
            return {"revision_id": "revision_one"}

        async def aclose(self):
            events.append(("close",))

    monkeypatch.setitem(sys.modules, "seldon_runtime.runner", types.SimpleNamespace(Runner=Runner))

    @seldon.function(
        model="example/model",
        prompt="Label {text}",
        local=True,
        id="00000000-0000-4000-8000-000000000001",
        api_key="secret",
        local_fallback="raise",
    )
    async def classify(text: str) -> Result: ...

    assert (await classify("one")).label == "local"
    assert (await classify("two")).label == "local"
    await classify.aclose()
    assert [event[0] for event in events] == ["load", "call", "call", "close"]
    assert events[0][2]["fallback"] == "raise"
