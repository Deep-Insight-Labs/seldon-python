"""Static public typing smoke; decorated bodies are never executed."""

from pydantic import BaseModel

import seldon_sdk as seldon


class Answer(BaseModel):
    label: str


@seldon.function(model="example/model", prompt="Label {text}")
def classify(text: str) -> Answer:
    raise NotImplementedError


@seldon.function(model="example/model", prompt="Label {text}")
async def classify_async(text: str) -> Answer:
    raise NotImplementedError


def sync_usage() -> str:
    result: Answer = classify("sample")
    return result.label


async def async_usage() -> str:
    result: Answer = await classify_async("sample")
    info_result, info = await classify_async.call_with_info("sample")
    await classify_async.aclose()
    return result.label + info_result.label + info.path
