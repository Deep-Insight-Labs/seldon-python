from pydantic import BaseModel

import seldon_sdk as seldon


class Classification(BaseModel):
    label: str
    confidence: float


@seldon.function(
    model="example/model",
    prompt="Classify {document}",
    name="example:classify",
    example={"document": "A synthetic sample"},
)
def classify(document: str) -> Classification: ...
