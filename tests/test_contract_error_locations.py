"""Contract errors identify locations without exposing templates or schema values."""

import pytest
from pydantic import BaseModel

from seldon_sdk import function
from seldon_sdk.contract import bounded_schema
from seldon_sdk.errors import SeldonContractError


@pytest.mark.parametrize("prompt", ["Private {text!r}", "Private {missing}"])
def test_message_errors_identify_the_message(prompt):
    class Answer(BaseModel):
        label: str

    with pytest.raises(SeldonContractError) as caught:

        @function(model="synthetic/model", prompt=prompt)
        def classify(text: str) -> Answer: ...

    assert caught.value.param == "messages[0]"
    assert "Private" not in str(caught.value)


def test_schema_errors_identify_json_pointer():
    with pytest.raises(SeldonContractError) as caught:
        bounded_schema(
            {"type": "object", "properties": {"a/b": {"type": "string", "pattern": "private"}}}
        )
    assert caught.value.param == "/properties/a~1b/pattern"
    assert "private" not in str(caught.value)
