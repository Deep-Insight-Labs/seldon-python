"""Small repeated measurements of the plan's explicit local latency budgets."""

import json
import math
import subprocess
import sys
import time

from pydantic import BaseModel

from seldon_sdk.decorator import Function


class Result(BaseModel):
    label: str


def test_import_is_lazy_socket_free_and_within_fresh_process_budget(tmp_path):
    program = """
import json,sys,time

def audit(event,args):
    if event.startswith('socket.'):
        raise AssertionError('import opened a socket')
sys.addaudithook(audit)
start=time.perf_counter()
import seldon_sdk
elapsed=(time.perf_counter()-start)*1000
assert not {'seldon','seldon_runtime','httpx','pydantic'} & set(sys.modules)
print(json.dumps(elapsed))
"""
    durations = []
    for _ in range(20):
        result = subprocess.run(
            [sys.executable, "-I", "-c", program],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        durations.append(json.loads(result.stdout))
    p95 = sorted(durations)[math.ceil(len(durations) * 0.95) - 1]
    assert p95 <= 150, durations


def test_contract_decoration_p95_budget_over_one_hundred_declarations():
    def classify(text: str) -> Result: ...

    durations = []
    for _ in range(100):
        started = time.perf_counter()
        Function(classify, model="example/model", prompt="Label {text}")
        durations.append((time.perf_counter() - started) * 1000)
    p95 = sorted(durations)[94]
    assert p95 <= 20, durations
