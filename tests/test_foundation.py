from uuid import uuid4

import pytest

from seldon_sdk.errors import SeldonContractError
from seldon_sdk.files import Association, canonical, read_json, resolve_function, validate_source


def source():
    return {"model": "example/model", "messages": [{"role": "user", "content": "hello"}]}


def test_source_validation_preserves_omitted_settings():
    original = source()
    assert validate_source(original) == original
    assert "temperature" not in original
    assert "max_tokens" not in original


def test_unknown_fields_and_nonfinite_json_refused(tmp_path):
    with pytest.raises(SeldonContractError):
        validate_source({**source(), "surprise": True})
    path = tmp_path / "input.json"
    path.write_text('{"x": NaN}')
    with pytest.raises(SeldonContractError):
        read_json(path)


def test_locator_requires_authoritative_identity():
    identity = str(uuid4())
    assert resolve_function(identity) == identity
    assert resolve_function("seldon/function/" + identity) == identity
    with pytest.raises(SeldonContractError):
        resolve_function("seldon/function/" + identity + "@" + str(uuid4()))
    with pytest.raises(SeldonContractError):
        resolve_function("my unknown model")


def test_association_preserves_uncertain_create_and_refuses_drift(tmp_path):
    association = Association(tmp_path / "operation.json")
    association.save({"source_digest": "a" * 64, "pending_create": True})
    assert association.read()["pending_create"] is True
    with pytest.raises(SeldonContractError):
        association.require_source("b" * 64)
    assert "hello" not in association.path.read_text()


def test_canonical_is_unicode_and_stable():
    assert canonical({"b": None, "a": "é"}) == '{"a":"é","b":null}'


def test_examples_preserve_explicit_provenance_and_unknown_omission(tmp_path):
    from seldon_sdk.files import atomic_json, read_examples

    rows = [
        {
            "input": {"text": "synthetic"},
            "expected": {"label": "sample"},
            "input_origin": "synthetic",
            "label_origin": "reference",
        },
        {"input": {"text": "uploaded"}, "output": {"label": "other"}},
    ]
    path = tmp_path / "examples.json"
    atomic_json(path, rows)
    assert read_examples(path) == rows
    rows[0]["label_origin"] = "guessed"
    atomic_json(path, rows)
    with pytest.raises(SeldonContractError, match="label_origin"):
        read_examples(path)
