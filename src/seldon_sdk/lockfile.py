"""Explicit identity mapping; local files never contain API credentials."""

import os
import re
from pathlib import Path

from .errors import SeldonConfigError
from .files import atomic_json, read_json, resolve_function


def locate(module_file):
    override = os.environ.get("SELDON_LOCKFILE")
    if override:
        return Path(override)
    start = Path(module_file).resolve().parent if module_file else Path.cwd()
    for parent in (start, *start.parents):
        candidate = parent / "seldon.lock.json"
        if candidate.exists():
            return candidate
    return start / "seldon.lock.json"


def read(path):
    try:
        value = read_json(path)
        if value.get("version") != "seldon-lock-v1" or not isinstance(value.get("functions"), dict):
            raise ValueError
        for item in value["functions"].values():
            resolve_function(item["function_id"])
            if not isinstance(item["contract_digest"], str) or not re.fullmatch(
                r"[0-9a-f]{64}", item["contract_digest"]
            ):
                raise ValueError
        return value
    except Exception:
        raise SeldonConfigError("invalid_lockfile") from None


def set_entry(path, key, entry):
    value = read(path) if Path(path).exists() else {"version": "seldon-lock-v1", "functions": {}}
    value["functions"][key] = entry
    atomic_json(path, value)
