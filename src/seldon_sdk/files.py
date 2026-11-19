"""Bounded JSON preparation and non-secret local operation associations."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from uuid import UUID

from .errors import SeldonContractError

MAX_FILE_BYTES = 5 * 1024 * 1024
ROLES = {"system", "developer", "user", "assistant"}
REQUEST_FIELDS = {
    "model",
    "messages",
    "response_format",
    "temperature",
    "max_tokens",
    "max_completion_tokens",
    "stream",
    "n",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _invalid_constant(_value):
    raise SeldonContractError("nonfinite_json")


def read_json(path):
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise SeldonContractError("file_too_large")
        return json.loads(raw, parse_constant=_invalid_constant)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SeldonContractError("invalid_json_file") from None


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(canonical(data) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def bounded_json(value):
    count = 0

    def visit(item, depth):
        nonlocal count
        count += 1
        if depth > 32 or count > 20000:
            raise SeldonContractError("json_complexity_limit")
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise SeldonContractError("invalid_json_keys")
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)

    visit(value, 0)
    try:
        if len(canonical(value).encode()) > MAX_FILE_BYTES:
            raise SeldonContractError("file_too_large")
    except (ValueError, TypeError):
        raise SeldonContractError("invalid_json") from None


def _request(call):
    if not isinstance(call, dict) or set(call) - REQUEST_FIELDS - {"id"}:
        raise SeldonContractError("unsupported_request_option")
    if not isinstance(call.get("model"), str) or not call["model"]:
        raise SeldonContractError("model_required")
    messages = call.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
        raise SeldonContractError("invalid_messages")
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise SeldonContractError("invalid_message")
        if message["role"] not in ROLES or not isinstance(message["content"], str):
            raise SeldonContractError("invalid_message")
        if len(message["content"]) > 262144:
            raise SeldonContractError("message_too_large")
    for name, neutral in (
        ("stream", False),
        ("n", 1),
        ("top_p", 1),
        ("frequency_penalty", 0),
        ("presence_penalty", 0),
    ):
        if name in call and (
            call[name] != neutral or isinstance(call[name], bool) != isinstance(neutral, bool)
        ):
            raise SeldonContractError("unsupported_request_option")
    for name in ("max_tokens", "max_completion_tokens"):
        if (
            name in call
            and call[name] is not None
            and (type(call[name]) is not int or call[name] <= 0)
        ):
            raise SeldonContractError("invalid_output_limit")
    if "max_tokens" in call and "max_completion_tokens" in call:
        if call["max_tokens"] != call["max_completion_tokens"]:
            raise SeldonContractError("conflicting_output_limits")
    if "temperature" in call and call["temperature"] is not None:
        value = call["temperature"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 2:
            raise SeldonContractError("invalid_temperature")


def validate_source(source):
    """Validate the public source envelope without defaulting or rewriting its contents.

    The server remains authoritative for evaluator, provider and runtime eligibility.
    """
    bounded_json(source)
    if isinstance(source, list):
        calls = source
    elif isinstance(source, dict) and "calls" in source:
        allowed = {
            "version",
            "calls",
            "inputs",
            "input_schema",
            "bindings",
            "output_schema",
            "evaluator",
            "rubric",
            "wire_mode",
            "evaluation",
            "evaluation_pending",
            "template_syntax",
            "samples",
            "assumptions",
            "preparation",
            "output_token_policy",
            "reference_binding",
        }
        if set(source) - allowed:
            raise SeldonContractError("unsupported_source_option")
        calls = source["calls"]
    elif isinstance(source, dict) and source.get("kind") == "template":
        allowed = {
            "kind",
            "model",
            "messages",
            "syntax",
            "example_inputs",
            "output_schema",
            "response_format",
            "temperature",
            "max_tokens",
            "samples",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "evaluation",
        }
        if set(source) - allowed or source.get("syntax") not in {
            "python_format",
            "jinja_variables",
        }:
            raise SeldonContractError("invalid_template_source")
        _request({key: value for key, value in source.items() if key in REQUEST_FIELDS})
        return source
    elif isinstance(source, dict):
        _request(source)
        return source
    else:
        raise SeldonContractError("invalid_source")
    if not isinstance(calls, list) or not 1 <= len(calls) <= 3:
        raise SeldonContractError("workflow_call_limit")
    for call in calls:
        _request(call)
    return source


def resolve_function(locator, lockfile=None):
    if not isinstance(locator, str):
        raise SeldonContractError("function_identity_required")
    if locator.startswith("seldon/function/"):
        locator = locator[len("seldon/function/") :]
    try:
        return str(UUID(locator))
    except (ValueError, TypeError):
        from .lockfile import locate

        path = Path(lockfile) if lockfile else locate(None)
        if path.exists():
            value = read_json(path)
            if isinstance(value, dict) and value.get("version") == "seldon-lock-v1":
                entries = value.get("functions", {})
                entry = entries.get(locator) if isinstance(entries, dict) else None
                if isinstance(entry, dict):
                    try:
                        return str(UUID(entry.get("function_id", "")))
                    except (ValueError, TypeError, AttributeError):
                        pass
        raise SeldonContractError("function_identity_required") from None


class Association:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return {}
        value = read_json(self.path)
        if not isinstance(value, dict) or value.get("version") != "seldon-operation-v1":
            raise SeldonContractError("invalid_association")
        return value

    def save(self, values):
        allowed = {
            "source_file",
            "source_digest",
            "function_id",
            "workspace_id",
            "revision",
            "run_id",
            "revision_id",
            "pending_create",
            "command_id",
            "cap_usd",
            "base_url",
            "evidence_digest",
            "evidence_file",
            "evaluation_command_id",
            "evaluation_revision",
        }
        if set(values) - allowed:
            raise SeldonContractError("invalid_association_field")
        atomic_json(self.path, {"version": "seldon-operation-v1", **values})

    def update(self, **values):
        old = self.read()
        old.pop("version", None)
        self.save({**old, **values})

    def require_source(self, source_digest):
        state = self.read()
        if state.get("source_digest") not in (None, source_digest):
            raise SeldonContractError("source_changed_reimport_required")
        return state


def safe_code(value, default="service_error"):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", value)
        else default
    )


def read_examples(path):
    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise SeldonContractError("file_too_large")
            examples = [
                json.loads(line, parse_constant=_invalid_constant)
                for line in path.read_text().splitlines()
                if line.strip()
            ]
        except (OSError, ValueError):
            raise SeldonContractError("invalid_examples_file") from None
    else:
        examples = read_json(path)
    if not isinstance(examples, list) or len(examples) > 400:
        raise SeldonContractError("evaluation_examples_limit")
    bounded_json(examples)
    seen = set()
    for index, example in enumerate(examples):
        allowed = {
            "input",
            "output",
            "expected",
            "assertions",
            "group",
            "weight",
            "role",
            "value",
            "input_origin",
            "label_origin",
        }
        if (
            not isinstance(example, dict)
            or set(example) - allowed
            or not isinstance(example.get("input"), dict)
        ):
            raise SeldonContractError("invalid_example_row_" + str(index))
        if example.get("input_origin", "uploaded") not in {"synthetic", "uploaded", "recorded"}:
            raise SeldonContractError("invalid_example_input_origin")
        if example.get("label_origin", "unknown") not in {"human", "reference", "judge", "unknown"}:
            raise SeldonContractError("invalid_example_label_origin")
        if example.get("role") not in {None, "training", "development", "confirmation"}:
            raise SeldonContractError("invalid_example_role")
        for name in ("weight", "value"):
            number = example.get(name)
            if number is not None and (
                isinstance(number, bool)
                or not isinstance(number, (int, float))
                or number < 0
                or (name == "weight" and number == 0)
            ):
                raise SeldonContractError("invalid_example_" + name)
        assertions = example.get("assertions", [])
        if (
            not isinstance(assertions, list)
            or len(assertions) > 6
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 2048
                for item in assertions
            )
        ):
            raise SeldonContractError("invalid_example_assertions")
        identity = digest(example["input"])
        if identity in seen:
            raise SeldonContractError("duplicate_example_row_" + str(index))
        seen.add(identity)
    return examples
