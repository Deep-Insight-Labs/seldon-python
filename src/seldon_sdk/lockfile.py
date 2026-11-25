"""Explicit identity mapping; local files never contain API credentials."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from .errors import SeldonConfigError
from .files import atomic_json, read_json


def locate(module_file: str | Path | None) -> Path:
    override = os.environ.get("SELDON_LOCKFILE")
    if override:
        return Path(override)
    start = Path(module_file).resolve().parent if module_file else Path.cwd()
    for parent in (start, *start.parents):
        candidate = parent / "seldon.lock.json"
        if candidate.exists():
            return candidate
    return start / "seldon.lock.json"


def read(path: str | Path) -> dict[str, Any]:
    try:
        value = read_json(path)
        if (
            not isinstance(value, dict)
            or value.get("version") != "seldon-lock-v1"
            or not isinstance(value.get("functions"), dict)
            or set(value) - {"version", "functions", "workspace_id"}
        ):
            raise ValueError
        if "workspace_id" in value:
            UUID(value["workspace_id"])
        for key, item in value["functions"].items():
            if (
                not isinstance(key, str)
                or not isinstance(item, dict)
                or set(item) - {"function_id", "contract_digest", "registered_at", "parts"}
            ):
                raise ValueError
            UUID(item["function_id"])
            if not isinstance(item["contract_digest"], str) or not re.fullmatch(
                r"[0-9a-f]{64}", item["contract_digest"]
            ):
                raise ValueError
            if "registered_at" in item:
                registration = datetime.fromisoformat(item["registered_at"].replace("Z", "+00:00"))
                if registration.utcoffset() is None:
                    raise ValueError
            if "parts" in item and (
                not isinstance(item["parts"], dict)
                or any(
                    not isinstance(part, str)
                    or not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    for part, digest in item["parts"].items()
                )
            ):
                raise ValueError
        return cast(dict[str, Any], value)
    except Exception:
        raise SeldonConfigError("invalid_lockfile") from None


def set_entry(path: str | Path, key: str, entry: dict[str, Any]) -> None:
    value: dict[str, Any] = (
        read(path) if Path(path).exists() else {"version": "seldon-lock-v1", "functions": {}}
    )
    previous = value["functions"].get(key, {})
    registered_at = entry.get("registered_at")
    if registered_at is None:
        same_registration = all(
            previous.get(field) == entry.get(field) for field in ("function_id", "contract_digest")
        )
        registered_at = previous.get("registered_at") if same_registration else None
    value["functions"][key] = {
        **entry,
        "registered_at": registered_at or datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(path, value)
