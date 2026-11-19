"""Install an actual wheel in a fresh environment and exercise public entrypoints."""

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

wheel = Path(sys.argv[1]).resolve()
with zipfile.ZipFile(wheel) as artifact:
    names = artifact.namelist()
    assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
    assert "seldon_sdk/py.typed" in names
    assert "seldon_sdk/skill/SKILL.md" in names
    assert all(name.startswith("seldon_sdk/") or ".dist-info/" in name for name in names)
for sdist in wheel.parent.glob("*.tar.gz"):
    with tarfile.open(sdist) as artifact:
        assert any(name.endswith("/LICENSE") for name in artifact.getnames())
with tempfile.TemporaryDirectory(prefix="seldon-sdk-artifact-") as temporary:
    root = Path(temporary)
    environment = root / "environment"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], check=True
    )
    clean = {
        key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "SELDON"))
    }
    source = root / "source.json"
    source.write_text(
        json.dumps(
            {
                "model": "example/model",
                "messages": [{"role": "user", "content": "Synthetic sample"}],
            }
        )
    )
    subprocess.run(
        [str(python), "-I", "-m", "seldon_sdk.cli", "import", "--source", str(source), "--offline"],
        cwd=root,
        env=clean,
        check=True,
    )
    script = """import importlib.resources,sys,time
start=time.perf_counter()
import seldon_sdk
assert time.perf_counter()-start < 0.150
assert 'seldon' not in sys.modules and 'seldon_runtime' not in sys.modules
assert 'httpx' not in sys.modules and 'pydantic' not in sys.modules
assert importlib.resources.files('seldon_sdk').joinpath('skill/SKILL.md').is_file()
from pydantic import BaseModel
from seldon_sdk.testing import stub
class Result(BaseModel):
    label:str
@seldon_sdk.function(model='example/model',prompt='Label {text}')
def classify(text:str)->Result: ...
with stub(classify,returns={'label':'sample'}):
    assert classify('synthetic').label=='sample'
"""
    subprocess.run([str(python), "-I", "-c", script], cwd=root, env=clean, check=True)
    console = environment / ("Scripts/seldon.exe" if os.name == "nt" else "bin/seldon")
    subprocess.run([str(console), "--version"], cwd=root, env=clean, check=True)
