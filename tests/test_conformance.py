import hashlib
import json
import runpy
import subprocess
from pathlib import Path

import pytest

from seldon_sdk.contract import render
from seldon_sdk.files import digest, read_json


def test_server_owned_corpus_matches_export_and_rendering():
    root = Path(__file__).resolve().parents[1]
    generated = runpy.run_path(str(root / "scripts/conformance_cases.py"))["cases"]()
    corpus = read_json(root / "tests/fixtures/conformance.json")["cases"]
    assert len(corpus) == len(generated) >= 30
    for actual, case in zip(generated, corpus, strict=True):
        assert actual["source"] == case["source"]
        source = actual["source"]
        assert digest(source["contract"]) == case["expected_contract_digest"]
        assert (
            render(source["contract"], source["example_inputs"])
            == case["expected_rendered"]["messages"]
        )


def test_vendored_corpus_has_committed_provenance_and_exact_hash():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "conformance/SOURCE").read_text())
    assert len(manifest["seldon_revision"]) == 40
    assert (
        manifest["sha256"]
        == hashlib.sha256((root / "tests/fixtures/conformance.json").read_bytes()).hexdigest()
    )
    assert len(manifest["exporter_sha256"]) == 64


def test_invalid_contract_vectors_fail_at_the_local_declaration_boundary():
    from seldon_sdk.contract import bounded_schema, build, template
    from seldon_sdk.errors import SeldonContractError

    root = Path(__file__).resolve().parents[1]
    generator = runpy.run_path(str(root / "scripts/conformance_cases.py"))
    generated = generator["invalid_cases"]()
    corpus = read_json(root / "tests/fixtures/conformance.json")["invalid_cases"]
    assert len(corpus) == len(generated) >= 8
    for actual, case in zip(generated, corpus, strict=True):
        assert actual["source"] == case["source"]
        check = case["sdk_validation"]
        with pytest.raises(SeldonContractError, match="^" + check["error"] + "$"):
            if check["kind"] == "template":
                template(check["value"], {"x"})
            elif check["kind"] == "schema":
                bounded_schema(check["value"])
            else:

                def operation(x: str) -> str: ...

                build(operation, model="example/model", prompt="{x}")


def test_public_repository_contains_no_private_content_markers():
    root = Path(__file__).resolve().parents[1]
    denylist = root / "tests/public_content_denylist.txt"
    markers = [
        line for line in denylist.read_text().splitlines() if line and not line.startswith("#")
    ]
    files = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
        )
        .decode()
        .split("\0")
    )
    for name in files:
        path = root / name
        if not name or path == denylist or not path.is_file():
            continue
        content = path.read_bytes().lower()
        for marker in markers:
            assert marker.encode().lower() not in content, f"private content marker found in {name}"
