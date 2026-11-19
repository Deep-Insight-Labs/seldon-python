"""Generate only synthetic SDK-owned cases for the server conformance exporter."""

from datetime import date

from pydantic import BaseModel

from seldon_sdk.decorator import Function


class Answer(BaseModel):
    label: str


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
    return result


if __name__ == "__main__":
    import json

    print(json.dumps(cases(), sort_keys=True, indent=2, ensure_ascii=False))
