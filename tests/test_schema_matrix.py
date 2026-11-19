"""Cross-version canonical schemas: 20 synthetic shapes, no internal fixtures."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from seldon_sdk.contract import build
from seldon_sdk.files import digest, read_json


class Choice(str, Enum):
    yes = "yes"
    no = "no"


class Nested(BaseModel):
    value: str


SHAPES = [
    str,
    int,
    float,
    bool,
    date,
    datetime,
    Decimal,
    Choice,
    Literal["a", "b"],
    str | None,
    int | None,
    list[str],
    list[int],
    list[Nested],
    Nested,
    dict[str, str],
    dict[str, Any],
    str | int,
    tuple[str, int],
    list[date],
]


def snapshots():
    rows = []
    for index, shape in enumerate(SHAPES):
        output = create_model(
            "SyntheticOutput", value=(shape, Field(description="A synthetic value"))
        )

        def operation(text: str, enabled: bool = True): ...

        operation.__annotations__["return"] = output
        *_, contract, reasons = build(operation, model="example/model", prompt="{text} {enabled}")
        rows.append(
            {"index": index, "contract_digest": digest(contract), "strict_reasons": reasons}
        )
    return rows


def test_twenty_models_have_stable_contracts():
    assert snapshots() == read_json(Path(__file__).parent / "fixtures/schema_matrix.json")
