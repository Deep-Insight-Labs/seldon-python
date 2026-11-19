import runpy
from pathlib import Path

from seldon_sdk.contract import render
from seldon_sdk.files import digest, read_json


def test_server_owned_corpus_matches_export_and_rendering():
    root = Path(__file__).resolve().parents[1]
    generated = runpy.run_path(str(root / "scripts/conformance_cases.py"))["cases"]()
    corpus = read_json(root / "tests/fixtures/conformance.json")["cases"]
    assert len(corpus) == len(generated) == 30
    for actual, case in zip(generated, corpus, strict=True):
        assert actual["source"] == case["source"]
        source = actual["source"]
        assert digest(source["contract"]) == case["expected_contract_digest"]
        assert (
            render(source["contract"], source["example_inputs"])
            == case["expected_rendered"]["messages"]
        )
