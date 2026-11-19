"""Explicit typed declarations, bounded schemas and canonical rendering."""

import inspect
import re
import string
from typing import get_type_hints

from pydantic import ConfigDict, TypeAdapter, create_model

from .errors import SeldonContractError
from .files import ROLES, canonical

TOKEN = re.compile(r"\{\{[A-Za-z]\w*\}\}|(?<!\{)\{([A-Za-z]\w*)\}(?!\})")


def template(text, parameters):
    if not isinstance(text, str) or len(text.encode()) > 262144:
        raise SeldonContractError("message_too_large")
    pieces, used, literal_parts = [], [], []
    try:
        parts = list(string.Formatter().parse(text))
    except ValueError:
        raise SeldonContractError("template_syntax_unsupported") from None
    for literal, field, fmt, conversion in parts:
        pieces.append(literal)
        literal_parts.append(literal)
        if field is None:
            continue
        if not re.fullmatch(r"[A-Za-z]\w*", field) or fmt or conversion:
            raise SeldonContractError("template_syntax_unsupported")
        if field not in parameters:
            raise SeldonContractError("unknown_placeholder")
        if field in used:
            raise SeldonContractError("repeated_placeholder_unsupported")
        used.append(field)
        pieces.append("{" + field + "}")
    if TOKEN.search("".join(literal_parts)):
        raise SeldonContractError("literal_braces_unsupported")
    return "".join(pieces), used


def bounded_schema(schema):
    nodes = 0

    def walk(value, depth=0, refs=()):
        nonlocal nodes
        nodes += 1
        if depth > 24 or nodes > 2048:
            raise SeldonContractError("schema_complexity_limit")
        if isinstance(value, dict):
            if set(value) & {"pattern", "patternProperties", "$dynamicRef", "$recursiveRef", "$id"}:
                raise SeldonContractError("unsupported_schema_keyword")
            if "$ref" in value:
                ref = value["$ref"]
                if not isinstance(ref, str) or not ref.startswith("#/") or ref in refs:
                    raise SeldonContractError("unsupported_schema_reference")
                target = schema
                try:
                    for key in ref[2:].split("/"):
                        target = target[key.replace("~1", "/").replace("~0", "~")]
                except (KeyError, TypeError):
                    raise SeldonContractError("invalid_schema_reference") from None
                walk(target, depth + 1, refs + (ref,))
            for key, child in value.items():
                if key != "$ref":
                    walk(child, depth + 1, refs)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1, refs)

    walk(schema)
    return schema


def normalized_output(schema):
    bounded_schema(schema)

    def normalize(value):
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {
            key: normalize(item) for key, item in value.items() if key not in {"title", "default"}
        }
        if "properties" in result:
            result["required"] = list(result["properties"])
            result["additionalProperties"] = False
        choices = result.get("anyOf")
        if isinstance(choices, list) and len(choices) == 2:
            nonnull = next((item for item in choices if item.get("type") != "null"), None)
            if {"type": "null"} in choices and nonnull and isinstance(nonnull.get("type"), str):
                result.pop("anyOf")
                result.update(nonnull)
                result["type"] = [nonnull["type"], "null"]
        return result

    return normalize(schema)


def strict_schema(schema):
    reasons = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "object" and value.get("additionalProperties") is not False:
                reasons.append("open_object")
            if not value:
                reasons.append("unconstrained_value")
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(schema)
    return not reasons, sorted(set(reasons))


def build(fn, *, model, prompt=None, system=None, messages=None, temperature=0, max_tokens=2048):
    if not isinstance(model, str) or not model:
        raise SeldonContractError("missing_model")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (float, int))
        or not 0 <= temperature <= 2
    ):
        raise SeldonContractError("invalid_temperature")
    if type(max_tokens) is not int or max_tokens < 1:
        raise SeldonContractError("invalid_max_tokens")
    signature = inspect.signature(fn)
    hints = get_type_hints(fn)
    fields = {}
    for name, parameter in signature.parameters.items():
        if name in {"self", "cls"} or parameter.kind in {
            parameter.POSITIONAL_ONLY,
            parameter.VAR_POSITIONAL,
            parameter.VAR_KEYWORD,
        }:
            raise SeldonContractError("unsupported_signature")
        if name not in hints:
            raise SeldonContractError("input_annotation_required")
        fields[name] = (
            hints[name],
            ... if parameter.default is parameter.empty else parameter.default,
        )
    if "return" not in hints:
        raise SeldonContractError("output_annotation_required")
    inputs = create_model("Inputs", __config__=ConfigDict(extra="forbid"), **fields)
    output = TypeAdapter(hints["return"])
    input_schema = bounded_schema(inputs.model_json_schema())
    output_schema = normalized_output(output.json_schema())
    if output_schema.get("type") not in {"object", "array"}:
        raise SeldonContractError("unsupported_output_type")
    if messages is not None and (prompt is not None or system is not None):
        raise SeldonContractError("conflicting_templates")
    selected = (
        messages
        if messages is not None
        else ([("system", system)] if system else []) + [("user", prompt)]
    )
    if not isinstance(selected, (list, tuple)) or not 1 <= len(selected) <= 32:
        raise SeldonContractError("message_limit")
    prepared, used = [], set()
    for message in selected:
        if not isinstance(message, (list, tuple)) or len(message) != 2 or message[0] not in ROLES:
            raise SeldonContractError("unsupported_message_role")
        content, names = template(message[1], fields)
        used.update(names)
        prepared.append({"role": message[0], "content": content})
    if set(fields) != used:
        raise SeldonContractError("unused_parameter")
    strict, reasons = strict_schema(output_schema)
    contract = {
        "version": "seldon-sdk-contract-v1",
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": prepared,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "output", "strict": strict, "schema": output_schema},
        },
    }
    if len(canonical(contract).encode()) > 262144:
        raise SeldonContractError("request_too_large")
    return signature, inputs, output, contract, reasons


def render(contract, inputs):
    def replace(match):
        value = inputs[match.group(1)]
        return value if isinstance(value, str) else canonical(value)

    return [
        {"role": item["role"], "content": TOKEN.sub(replace, item["content"])}
        for item in contract["messages"]
    ]
