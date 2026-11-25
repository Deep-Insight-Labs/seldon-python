"""SDK exports use the shared import path without losing evidence or changing defaults."""

import copy
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from seldon_sdk.cli import main
from seldon_sdk.errors import SeldonContractError
from seldon_sdk.files import validate_source


def source():
    result = json.loads((Path(__file__).parent / "fixtures/sdk_source.json").read_text())
    result["evaluation"] = {
        "instructions": "Check the supplied answer.",
        "metric": "exact_match",
        "checks": [{"kind": "schema"}],
        "examples": [
            {"input": result["example_inputs"], "expected": {"label": "x", "confidence": 1}}
        ],
    }
    return result


def test_sdk_source_preserves_export_contract_and_evidence():
    value = source()
    assert validate_source(value) is value
    assert "version" not in value["evaluation"]


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda value: value.update(digest="0" * 64), "contract_digest_mismatch"),
        (lambda value: value.update(secret="private"), "invalid_sdk_contract"),
        (lambda value: value.update(evaluation={"instructions": ""}), "invalid_evaluation"),
    ],
)
def test_invalid_sdk_source_fails_without_payload(mutation, code):
    value = source()
    mutation(value)
    with pytest.raises(SeldonContractError, match=code) as caught:
        validate_source(value)
    assert "private" not in str(caught.value)


def test_sdk_source_cli_offline_and_online_import(tmp_path, capsys):
    value = source()
    before = copy.deepcopy(value)
    path = tmp_path / "source.json"
    path.write_text(json.dumps(value))
    assert main(["import", "--source", str(path), "--offline"]) == 0
    assert value["contract"]["messages"][0]["content"] not in capsys.readouterr().out
    sent = []
    function = str(uuid4())
    workspace = str(uuid4())

    def handler(request):
        sent.append(json.loads(request.content))
        assert request.method == "POST" and request.url.path == "/v1/seldon/functions"
        return httpx.Response(
            201,
            json={
                "id": function,
                "workspace_id": workspace,
                "revision": 1,
                "selected_contract_digest": value["digest"],
            },
        )

    class Session:
        origin = "https://seldon.test"
        http = httpx.Client(transport=httpx.MockTransport(handler))

        def access_token(self):
            return "test"

    try:
        assert (
            main(
                [
                    "--association",
                    str(tmp_path / "association.json"),
                    "import",
                    "--source",
                    str(path),
                ],
                login=Session(),
            )
            == 0
        )
    finally:
        Session.http.close()
    assert sent == [{"name": "Selected operation", "source": before}]


def test_all_exported_conformance_sources_validate_without_python_template_reinterpretation():
    corpus = json.loads((Path(__file__).parent / "fixtures/conformance.json").read_text())
    for case in corpus["cases"]:
        source = case["source"]
        assert validate_source(source) is source
