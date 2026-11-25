"""Explicit module exports and content-free local/remote drift inspection."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from .management import Management

import importlib
import inspect
import socket
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from .contract import template
from .decorator import Function
from .errors import SeldonContractError
from .files import atomic_json, digest, read_json, resolve_function
from .lockfile import locate, read, set_entry


@contextmanager
def offline_imports() -> Iterator[None]:
    def blocked(*args: Any, **kwargs: Any) -> NoReturn:
        raise SeldonContractError("module_network_access_forbidden")

    with (
        patch.object(socket.socket, "connect", blocked),
        patch.object(socket.socket, "connect_ex", blocked),
        patch.object(socket, "create_connection", blocked),
    ):
        yield


def declarations(modules: Sequence[str]) -> dict[str, Function]:
    with offline_imports():
        # The explicit module belongs to the invoking application, even for a console shim.
        root = str(Path.cwd())
        added = root not in sys.path
        if added:
            sys.path.insert(0, root)
        try:
            return _declarations(modules)
        finally:
            if added:
                sys.path.remove(root)


def _declarations(modules: Sequence[str]) -> dict[str, Function]:
    found: dict[str, Function] = {}
    for name in modules:
        module = importlib.import_module(name)
        for candidate in vars(module).values():
            if isinstance(candidate, Function) and candidate.original.__module__ == name:
                if candidate.key in found and found[candidate.key] is not candidate:
                    raise SeldonContractError("duplicate_function_key")
                found[candidate.key] = candidate
    return dict(sorted(found.items()))


def exported(modules: Sequence[str], path: str | Path) -> tuple[dict[str, Any], int]:
    rows, sources = [], []
    for key, fn in declarations(modules).items():
        if fn.example is None:
            rows.append({"key": key, "error": "example_required"})
        else:
            sources.append(fn.export())
            rows.append({"key": key, "status": "exported"})
    atomic_json(path, sources)
    return {"items": rows, "source_file": str(path)}, int(any("error" in row for row in rows))


def lock_set(module: str, key: str, identity: str) -> dict[str, str]:
    identity = resolve_function(identity)
    functions = declarations([module])
    if key not in functions:
        raise SeldonContractError("unknown_function_key")
    fn = functions[key]
    path = locate(inspect.getsourcefile(fn.original))
    set_entry(
        path,
        key,
        {
            "function_id": identity,
            "contract_digest": fn.digest,
            "parts": contract_parts(fn.contract),
        },
    )
    return {"key": key, "function_id": identity, "lockfile": str(path)}


def contract_parts(contract: dict[str, Any]) -> dict[str, str]:
    parts = {}

    def walk(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                walk(value[key], pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, pointer + "/" + str(index))
        else:
            parts[pointer] = digest(value)

    walk(contract, "")
    return parts


def check_modules(
    modules: Sequence[str], *, api: Management | None = None, allow_pending: bool = False
) -> tuple[dict[str, Any], int]:
    rows = []
    for key, fn in declarations(modules).items():
        path = locate(inspect.getsourcefile(fn.original))
        entry = read(path)["functions"].get(key) if path.exists() else None
        row: dict[str, Any] = {"key": key, "status": "unregistered"}
        if entry:
            row["status"] = "unchanged" if entry["contract_digest"] == fn.digest else "stale_lock"
            parts = contract_parts(fn.contract)
            row["changed_parts"] = sorted(
                pointer
                for pointer in set(parts) | set(entry.get("parts", {}))
                if parts.get(pointer) != entry.get("parts", {}).get(pointer)
            )
            if api is not None and row["status"] == "unchanged":
                detail = api.detail(entry["function_id"])
                active = next(
                    (
                        r
                        for r in detail.get("revisions", [])
                        if str(r["id"]) == str(detail.get("active_revision"))
                    ),
                    None,
                )
                if active is None:
                    row["status"] = "pending"
                elif active.get("source_digest") != fn.digest:
                    row["status"] = "active_drift"
        rows.append(row)
    return {"items": rows}, int(
        any(
            row["status"] != "unchanged" and not (allow_pending and row["status"] == "pending")
            for row in rows
        )
    )


def sync_modules(modules: Sequence[str], api: Management) -> tuple[dict[str, Any], int]:
    from .management import FUNCTIONS

    # Authentication occurs before importing application code or sending any request.
    api.login.access_token()
    capabilities = api.request("GET", FUNCTIONS + "/sdk-capabilities")
    if "seldon-sdk-contract-v1" not in capabilities.get("contract_versions", []):
        raise SeldonContractError("sdk_contract_version_unsupported")
    functions = declarations(modules)
    sources = [fn.export() for fn in functions.values()]
    if not 1 <= len(sources) <= 50:
        raise SeldonContractError("sync_batch_too_large")
    result = api.request("POST", FUNCTIONS + "/sdk-sync", {"contracts": sources})
    for row in result["items"]:
        if not row.get("error") and row["key"] in functions:
            fn = functions[row["key"]]
            set_entry(
                locate(inspect.getsourcefile(fn.original)),
                fn.key,
                {
                    "function_id": resolve_function(row["function_id"]),
                    "contract_digest": fn.digest,
                    "parts": contract_parts(fn.contract),
                },
            )
    return result, int(any(row.get("error") for row in result["items"]))


def check_template(
    api: Management, function: str, path: str | Path, syntax: str
) -> tuple[dict[str, Any], int]:
    import re
    import string

    identity = resolve_function(function)
    remote = api.request("GET", "/v1/seldon/functions/" + identity + "/contract")
    data = read_json(path) if Path(path).suffix == ".json" else Path(path).read_text()
    messages = (
        data.get("messages") if isinstance(data, dict) else [{"role": "user", "content": data}]
    )
    if not isinstance(messages, list):
        raise SeldonContractError("invalid_template_source")
    changed = []
    if remote.get("template_syntax") != syntax:
        changed.append("syntax")
    for index, message in enumerate(messages):
        content = message["content"]
        if syntax == "python_format":
            parsed = list(string.Formatter().parse(content))
            variables = [field for _, field, _, _ in parsed if field is not None]
            template(content, variables)
            literals = [""]
            for literal, field, _, _ in parsed:
                literals[-1] += literal
                if field is not None:
                    literals.append("")
        else:
            tokens = list(re.finditer(r"{{\s*([A-Za-z]\w*)\s*}}", content))
            variables = [token[1] for token in tokens]
            literals, offset = [], 0
            for token in tokens:
                literals.append(content[offset : token.start()])
                offset = token.end()
            literals.append(content[offset:])
            if any(mark in "".join(literals) for mark in ("{{", "}}", "{%", "{#")):
                raise SeldonContractError("template_syntax_unsupported")
        expected = remote["messages"][index] if index < len(remote["messages"]) else {}
        if expected.get("role") != message["role"]:
            changed.append(f"messages/{index}/role")
        if expected.get("variables") != variables:
            changed.append(f"messages/{index}/variables")
        segments = [digest(literal) for literal in literals]
        for segment in range(max(len(segments), len(expected.get("segment_digests", [])))):
            if (
                segment >= len(segments)
                or segment >= len(expected.get("segment_digests", []))
                or segments[segment] != expected["segment_digests"][segment]
            ):
                changed.append(f"messages/{index}/segments/{segment}")
    if len(messages) != len(remote["messages"]):
        changed.append("messages/count")
    return {
        "function_id": identity,
        "status": "changed" if changed else "unchanged",
        "changed_parts": changed,
    }, int(bool(changed))
