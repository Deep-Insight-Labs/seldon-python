"""Generate only synthetic SDK-owned cases for the server conformance exporter."""

from copy import deepcopy
from datetime import date

from pydantic import BaseModel

from seldon_sdk.decorator import Function


class Answer(BaseModel):
    label: str


class SyntheticClassification(BaseModel):
    category: str
    subject: str | None
    entities: list[str]
    period: str | None
    observed_on: date | None
    origin: str | None
    topics: list[str]
    sensitivity: str
    confidence: float


def cases():
    values = [
        (str, "plain"),
        (str, "Unicode: café 東京"),
        (str, 'quote " and slash \\'),
        (str, "line1\nline2\tend"),
        (str, "{braces} {{inside}}"),
        (str, ""),
        (bool, True),
        (bool, False),
        (int, 0),
        (int, -123),
        (int, 9007199254740991),
        (float, 0.0),
        (float, -0.0),
        (float, 1e30),
        (float, 1e-12),
        (str | None, None),
        (str | None, "present"),
        (int | None, None),
        (list[str], ["one", "two"]),
        (list[str], []),
        (list[int], [1, 2, -3]),
        (dict[str, int], {"z": 2, "a": 1}),
        (list[bool], [True, False]),
        (dict[str, str], {"x": "Unicode 雪", "y": "\n"}),
        (date, date(2026, 1, 2)),
        (list[list[int]], [[1], [2, 3]]),
        (dict[str, list[str]], {"x": ["a", "b"]}),
        (float, 1.23456789),
        (float, 0.1),
        (list[str | None], [None, "x"]),
        (dict[str, bool], {"flag": True}),
    ]
    result = []
    for index, (annotation, value) in enumerate(values):

        def operation(x): ...

        operation.__annotations__ = {"x": annotation, "return": Answer}
        settings = {"system": "Fixed instructions"}
        if index % 7 == 0:
            settings["system"] = "Consider {x}"
        fn = Function(
            operation,
            model="example/model",
            prompt='JSON {{"fixed":1}} Value {x}',
            name=f"synthetic:case_{index}",
            example={"x": value},
            **settings,
        )
        result.append({"name": f"case_{index}", "source": fn.export()})

    def classify(filename: str, file_type: str, text_content: str) -> SyntheticClassification: ...

    classification = Function(
        classify,
        model="example/model",
        prompt="Label the sample named {filename}, kind {file_type}. Content: {text_content}",
        name="synthetic:classification",
        example={
            "filename": "sample.txt",
            "file_type": "text",
            "text_content": "Synthetic content",
        },
    )
    result.append({"name": "classification", "source": classification.export()})
    return result


def invalid_cases():
    """Malformed synthetic declarations exercise both owners at their real seams."""
    base = cases()[0]["source"]
    result = []

    def add(name, *, messages=None, schema=None, sdk_kind, sdk_value, sdk_error):
        from seldon_sdk.files import digest

        source = deepcopy(base)
        source["key"] = "synthetic:invalid_" + name
        contract = source["contract"]
        if messages is not None:
            contract["messages"] = [{"role": "user", "content": messages}]
        if schema is not None:
            contract["output_schema"] = schema
            contract["response_format"]["json_schema"]["schema"] = schema
        source["digest"] = digest(contract)
        result.append(
            {
                "name": name,
                "source": source,
                "sdk_validation": {"kind": sdk_kind, "value": sdk_value, "error": sdk_error},
            }
        )

    for name, message, code in (
        ("repeated_placeholder", "{x} {x}", "repeated_placeholder_unsupported"),
        ("placeholder_literal", "{{ticker}} {x}", "literal_braces_unsupported"),
        ("unknown_placeholder", "{unknown}", "unknown_placeholder"),
        ("oversized_message", "x" * 262145, "message_too_large"),
    ):
        add(name, messages=message, sdk_kind="template", sdk_value=message, sdk_error=code)
    for name, schema, code in (
        (
            "pattern_keyword",
            {"type": "object", "properties": {"label": {"type": "string", "pattern": "x"}}},
            "unsupported_schema_keyword",
        ),
        (
            "recursive_reference",
            {
                "type": "object",
                "$defs": {
                    "Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}
                },
                "properties": {"root": {"$ref": "#/$defs/Node"}},
            },
            "unsupported_schema_reference",
        ),
        (
            "schema_identifier",
            {"type": "object", "$id": "https://synthetic.invalid/schema"},
            "unsupported_schema_keyword",
        ),
        ("string_output", {"type": "string"}, "unsupported_output_type"),
    ):
        add(
            name,
            schema=schema,
            sdk_kind="schema" if name != "string_output" else "output",
            sdk_value=schema,
            sdk_error=code,
        )
    return result


if __name__ == "__main__":
    import json

    print(
        json.dumps(
            {"cases": cases(), "invalid_cases": invalid_cases()},
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
