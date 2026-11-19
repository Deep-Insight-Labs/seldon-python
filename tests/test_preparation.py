import json
import sys
from pathlib import Path

from seldon_sdk.cli import main
from seldon_sdk.files import digest
from seldon_sdk.preparation import check_template
from seldon_sdk.scanner import scan


def module(tmp_path, monkeypatch):
    source = Path(__file__).parent / "fixtures/operation.py"
    (tmp_path / "fixture_operation.py").write_text(source.read_text())
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SELDON_LOCKFILE", str(tmp_path / "seldon.lock.json"))
    sys.modules.pop("fixture_operation", None)
    return "fixture_operation"


def test_export_lock_offline_check(tmp_path, monkeypatch, capsys):
    name = module(tmp_path, monkeypatch)
    output = tmp_path / "export.json"
    assert main(["export", name, "--out", str(output)]) == 0
    assert len(json.loads(output.read_text())) == 1
    assert main(["check", name]) == 1
    assert (
        main(
            [
                "lock",
                "set",
                "example:classify",
                "00000000-0000-4000-8000-000000000001",
                "--module",
                name,
            ]
        )
        == 0
    )
    assert main(["check", name]) == 0
    assert "Classify" not in capsys.readouterr().out
    before = (tmp_path / "seldon.lock.json").read_bytes()
    assert main(["lock", "set", "example:classify", "bad", "--module", name]) == 2
    assert (tmp_path / "seldon.lock.json").read_bytes() == before


def test_module_socket_effect_is_blocked(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "network_effect.py").write_text(
        "import socket\nsocket.create_connection(('example.com',443))"
    )
    assert main(["export", "network_effect", "--out", str(tmp_path / "bad.json")]) == 2
    assert not (tmp_path / "bad.json").exists()


def test_template_check_only_fetches_digests(tmp_path):
    source = tmp_path / "template.txt"
    source.write_text("Classify {document}")

    class API:
        def request(self, method, path):
            assert method == "GET" and path.endswith("/contract")
            return {
                "template_syntax": "python_format",
                "messages": [
                    {
                        "role": "user",
                        "variables": ["document"],
                        "segment_digests": [digest("Classify "), digest("")],
                    }
                ],
            }

    identity = "00000000-0000-4000-8000-000000000001"
    assert check_template(API(), identity, source, "python_format")[1] == 0
    source.write_text("Label {document}")
    result, code = check_template(API(), identity, source, "python_format")
    assert code == 1 and result["changed_parts"] == ["messages/0/segments/0"]


def test_scan_does_not_import_and_identifies_reasons(tmp_path):
    (tmp_path / "sample.py").write_text("""from openai import OpenAI
from pydantic_ai import Agent
raise RuntimeError("must never import")
PROMPT = "Classify {text}"
client = OpenAI()
client.chat.completions.create(messages=[{"role": "user", "content": PROMPT.format(text="x")}])
client.chat.completions.create(stream=True)
Agent(output_type=str, tools=[object()])
""")
    rows = scan(tmp_path, suggest=True)["items"]
    assert len(rows) == 3
    assert rows[0]["eligibility"] == "eligible"
    assert "suggestion" in rows[0]
    assert rows[2]["reasons"] == ["streaming", "dynamic_prompt"]
    assert rows[1]["reasons"] == ["tool_use", "dynamic_prompt"]
