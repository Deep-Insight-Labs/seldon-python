"""Lock entries preserve registration metadata and remain stable across repeated sync."""

import json
from datetime import datetime
from importlib.resources import files
from uuid import uuid4

from seldon_sdk.lockfile import read, set_entry


def test_registration_time_is_stable_and_legacy_entries_remain_readable(tmp_path):
    path = tmp_path / "seldon.lock.json"
    entry = {"function_id": str(uuid4()), "contract_digest": "a" * 64}
    path.write_text(json.dumps({"version": "seldon-lock-v1", "functions": {"legacy": entry}}))
    assert read(path)["functions"]["legacy"] == entry
    set_entry(path, "new", entry)
    registered = read(path)["functions"]["new"]["registered_at"]
    assert datetime.fromisoformat(registered).utcoffset() is not None
    before = path.read_bytes()
    set_entry(path, "new", entry)
    assert path.read_bytes() == before
    schema = json.loads(files("seldon_sdk").joinpath("schemas/seldon-lock-v1.json").read_text())
    assert schema["properties"]["version"]["const"] == "seldon-lock-v1"
    assert (
        "registered_at" in schema["properties"]["functions"]["additionalProperties"]["properties"]
    )


def test_lockfile_rejects_invalid_metadata(tmp_path):
    import pytest

    from seldon_sdk.errors import SeldonConfigError

    path = tmp_path / "seldon.lock.json"
    entry = {"function_id": str(uuid4()), "contract_digest": "a" * 64}
    for extra in (
        {"registered_at": "2026-11-25"},
        {"parts": {"/model": "bad"}},
        {"token": "secret"},
    ):
        path.write_text(
            json.dumps({"version": "seldon-lock-v1", "functions": {"x": {**entry, **extra}}})
        )
        with pytest.raises(SeldonConfigError, match="invalid_lockfile"):
            read(path)
