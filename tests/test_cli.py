import json
from uuid import uuid4

import httpx
import pytest

from seldon_sdk.cli import main


class Session:
    origin = "https://service.test"

    def __init__(self, handler):
        self.http = httpx.Client(transport=httpx.MockTransport(handler))

    def access_token(self):
        return "secret-access"


def request_source(tmp_path):
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps(
            {"model": "example/model", "messages": [{"role": "user", "content": "private prompt"}]}
        )
    )
    return path


def test_offline_import_is_zero_network_and_preserves_payload(tmp_path, capsys):
    path = request_source(tmp_path)
    session = Session(lambda _: pytest.fail("network forbidden"))
    assert main(["import", "--source", str(path), "--offline"], login=session) == 0
    output = capsys.readouterr().out
    assert "validated_offline" in output
    assert "private prompt" not in output


def test_create_timeout_preserves_uncertain_association_and_refuses_retry(tmp_path, capsys):
    path = request_source(tmp_path)
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret-access", request=request)

    session = Session(handler)
    args = ["--association", str(tmp_path / "operation.json"), "import", "--source", str(path)]
    assert main(args, login=session) == 2
    assert main(args, login=session) == 2
    assert len(calls) == 1
    output = capsys.readouterr()
    assert "secret-access" not in output.err
    assert "uncertain_create_reconcile_function_list" in output.err


def test_noninteractive_activation_makes_zero_requests(tmp_path, capsys):
    session = Session(lambda _: pytest.fail("network forbidden"))
    assert (
        main(
            ["activate", str(uuid4()), "--revision", str(uuid4())], login=session, interactive=False
        )
        == 2
    )
    assert "interactive_owner_confirmation_required" in capsys.readouterr().err


def test_status_omits_source_and_examples(tmp_path, capsys):
    identity = str(uuid4())

    def handler(request):
        if request.url.path.endswith("/usage"):
            return httpx.Response(200, json={"days": []})
        return httpx.Response(
            200,
            json={
                "id": identity,
                "revision": 2,
                "status": "draft",
                "source": {"private": "sentinel"},
            },
        )

    assert main(["status", identity], login=Session(handler)) == 0
    assert "sentinel" not in capsys.readouterr().out


def test_paid_comparison_requires_explicit_authorization(tmp_path, capsys):
    identity = str(uuid4())
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json={"id": identity, "revision": 2, "workspace_id": str(uuid4()), "runs": []}
        )

    assert main(["optimize", identity, "--cap", "1"], login=Session(handler)) == 3
    assert all(request.method == "GET" for request in requests)


def test_packaged_skill_commands_exist(capsys):
    assert main(["skill", "print"]) == 0
    text = capsys.readouterr().out
    assert "After the user approves" in text
    assert "seldon import" in text
    assert "whole repository" in text


def test_managed_fallback_approval_is_explicit_and_confirmed(tmp_path):
    from types import SimpleNamespace

    from seldon_sdk.management import Management

    function = "00000000-0000-4000-8000-000000000001"
    revision = "00000000-0000-4000-8000-000000000002"
    sent = []

    def request(method, path, body=None, **kwargs):
        if method == "GET":
            return {
                "id": function,
                "workspace_id": "workspace",
                "revisions": [{"id": revision}],
                "active_revision": None,
            }
        sent.append(body)
        return {"id": function}

    api = Management(
        SimpleNamespace(origin="https://api.example", http=None, access_token=lambda: "session"),
        association=tmp_path / "state.json",
    )
    api.request = request
    for publish in (False, True):
        result, code = api.activate(
            function,
            revision,
            publish=publish,
            interactive=True,
            managed_fallback_approved=True,
            confirm=lambda value: value["managed_fallback_approved"],
        )
        assert code == 0 and result["id"] == function
        assert sent[-1]["managed_fallback_approved"] is True
