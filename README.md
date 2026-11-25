# Seldon Python

Development preview of `seldon-sdk`: one CLI for preparing an existing AI
operation, comparing explicit alternatives and adopting a revision. A typed Python
Function decorator is optional. This is a separate project from SeldonIO.

## Install

```sh
python -m pip install 'seldon-sdk[login]==0.1.0.dev1'
```

Python 3.10+ is supported. Core dependencies are httpx and Pydantic 2.11+.
The lower bound was measured with twenty synthetic schema shapes against the
latest Pydantic; earlier 2.x versions change generated contract digests.
`keyring` is optional. Only macOS Keychain, Windows Credential Locker and Linux
Secret Service backends are accepted. A login without an available secure backend
is memory-only; its result explicitly reports `persisted: false`.

SDK preview [`0.1.0.dev1`](https://pypi.org/project/seldon-sdk/0.1.0.dev1/) is
published on PyPI after the matching hosted-server deployment. The earlier
`0.1.0.dev0` preview remains available. Live WorkOS device
login, macOS Keychain storage, token rotation and session logout were exercised
before package release.
Server SDK capabilities are independently feature flagged. The optional runtime
preview is published separately.

## Existing client workflow

Prepare one captured request or explicit `kind: template` JSON source. Missing
request settings remain missing. Offline validation does not import application
modules, contact a service, read inference credentials or access a keychain.
The server remains authoritative for schema/evaluator/provider eligibility.

```sh
seldon import --source operation.json --offline
seldon login
seldon import --source operation.json
seldon examples import FUNCTION_UUID --file examples.jsonl --replace
seldon optimize FUNCTION_UUID --cap 2.00 --yes --wait
seldon report FUNCTION_UUID --run RUN_UUID
seldon publish FUNCTION_UUID --revision REVISION_UUID
seldon activate FUNCTION_UUID --revision REVISION_UUID
```

`--yes` authorizes the specified run cap, including all held and settled work;
it is never inferred from a login or prior success. The CLI saves a command UUID
before creating a run and reconciles it through the authoritative returned run
identifier. Waiting can be interrupted without cancelling a run. Resume with the
same association; use `cancel FUNCTION_UUID --run RUN_UUID` to cancel explicitly.
`--new-run` explicitly creates another budget scope. An active Function recheck can
identify its baseline with `--source-run RUN_UUID`.

Publication and activation require an interactive human confirmation of the exact
revision. Neither is a side effect of optimization. They retain server owner/admin,
warning and eligibility checks. Test the consuming application against a published
revision before changing its production alias. These commands do not deploy code.

Management uses a WorkOS user session only. Configure the approved public-client
identifier as `SELDON_WORKOS_CLIENT_ID`; `SELDON_API_KEY` never grants management
access. `--base-url` selects an HTTPS origin (HTTP localhost is allowed for tests).
Credentials are bound to origin and profile. Refresh tokens live in the secure
keychain; access tokens remain in memory. `logout` clears local credentials and
opens the provider session-logout URL; its output distinguishes pending browser
confirmation from confirmed local deletion. `logout --all-profiles` clears recorded
profiles. No client secret is needed.

`.seldon/operation.json` is a non-secret local association. It stores identifiers,
digests and local paths, never prompts, examples or credentials. Gitignore it. A
create request with an unknown outcome is not retried: inspect `seldon status`,
then reconcile by explicitly supplying `import --function FUNCTION_UUID`. Source
or imported evidence edits invalidate a saved recommendation. Historical reports
use the saved or explicitly selected run, not whichever run is newest.

## Evaluation evidence

`examples import` validates every row before submission and requires `--replace`.
Before a run exists it updates only draft evaluation through
`PATCH /v1/seldon/functions/{id}/draft-evaluation`, preserving the SDK contract,
source digest and active alias. The server checks the expected draft revision,
owner/admin role, input/output schemas and duplicate rows. Repeating unchanged
content does not create a new revision. After preparation the existing versioned
run evaluation command is used instead.

A single exported `kind: sdk` source can also include the server's optional
`evaluation` definition (instructions, supported checks/metric and examples).
Evaluation is outside the declared behavior digest. Re-syncing an unchanged
declaration preserves separately imported evaluation evidence. These changes
require the matching server update. The hosted Seldon service deployed that update
before `0.1.0.dev1` publication; self-hosted servers must also include SDK evaluation
registration and the draft-evaluation endpoint.

## Typed Python functions

```python
from pydantic import BaseModel
import seldon_sdk as seldon


class Classification(BaseModel):
    label: str


@seldon.function(
    model="your/reference-model", prompt="Classify {text}", example={"text": "A synthetic sample"}
)
def classify(text: str) -> Classification: ...


result = classify("Sample")
```

Function bodies are never executed. Inputs are validated before a request. Explicit
annotations build a frozen contract and digest. Defaults are included in inputs.
Placeholders support `{name}` only: no format specifiers, conversions, attribute
lookups or repeated names in one message. Strings render directly; all other inputs
render as canonical JSON (`true`, `null`, compact arrays/objects), which can differ
from Python `str.format`. Recursive schemas and unsupported regex keywords fail at
decoration. Output must be an object or array. Function-key renames preserve the
behavior digest; the structured-output schema name is always `output`.

```sh
seldon export your_package.operations --out sources.json
seldon lock set your_package.operations:classify FUNCTION_UUID --module your_package.operations
seldon check your_package.operations
# With SDK management capabilities enabled:
seldon sync your_package.operations --json
```

Export imports only explicitly named modules, with ordinary socket connects blocked;
Python imports can still have filesystem effects. It writes a list of source
objects, one per decorated function, sorted by key. Paste an individual object into
the dashboard Import tab. Missing examples report an item error and exit 1.
Commit `seldon.lock.json`; it contains IDs, contract digests and per-field digests,
not prompt contents. `SELDON_LOCKFILE` overrides upward lookup from the declaration.
`check` reports field pointers when a local contract changes. Template-mode drift
can instead use `check --function FUNCTION_UUID --template-file prompt.txt
--syntax python_format`; this fetches segment digests without uploading text.

Serving requires `SELDON_API_KEY` or explicit `api_key=`. Function execution uses
one idempotency key for up to three bounded transport/capacity attempts. Reference
fallback defaults on for documented unavailable paths; set `fallback="never"` to
raise. Authentication, funding and input errors never trigger fallback. Contract
drift defaults to the current local reference request; `on_drift="raise"` rejects.
Invalid Function output raises by default (`on_invalid_output="reference"` is an
explicit override). `reference_base_url` on another host requires a separate
`reference_api_key`. No credentials are forwarded on redirects.

Sync declarations reuse a client per thread; async declarations reuse one per event
loop. Call `seldon.close()` / `await seldon.aclose()` at shutdown. Calling a sync
Function inside an active event loop raises; declare it `async def` there.
`call_with_info` returns `(result, metadata)` and `on_call=` receives the same safe
metadata, once per logical call including input/configuration failures and local
execution. Contract errors expose `param`; output-validation errors expose
`execution_id`; server errors preserve `correlation_id` when supplied. Hook
failures are logged without affecting the call. `SELDON_MODE=reference` explicitly selects reference execution.

```python
from seldon_sdk.testing import stub

with stub(classify, returns={"label": "sample"}) as calls:
    assert classify("input").label == "sample"
assert calls == [{"text": "input"}]
```

## Local execution

Local execution requires an eligible deployment and the separately released
`seldon-runtime` package. Follow the CPU and model-extra instructions in the
[public runtime repository](https://github.com/Deep-Insight-Labs/seldon-runtime).
The [0.1.1.dev0 runtime preview](https://pypi.org/project/seldon-runtime/0.1.1.dev0/)
is available for Python 3.11 and later.

```sh
seldon function pull FUNCTION_UUID --out bundle.json
seldon function verify FUNCTION_UUID
seldon function run FUNCTION_UUID --input inputs.json --fallback raise --no-telemetry
```

Pull validates and saves bundle JSON without loading model weights. Verify runs the
runtime conformance cohort and reports its size, agreement and latency; it is not
whole-workload or business evaluation. Run keeps automatic verification enabled.
Only activated eligible revisions can load. Bundles refresh with the active alias;
immutable local pinning is not promised. `--fallback seldon` can call a hosted
service; `raise` keeps failures local. Counts-only telemetry is optional.
Typed declarations use `local=True`, `local_fallback="seldon"|"raise"` and
`telemetry=False`. Async handles retain a Runner per event loop; call
`await classify.aclose()`. Sync calls load and close a Runner per invocation and
reuse the runtime's disk caches. Eligibility and verification belong to the runtime.

## Discovery and skill

`seldon scan path --json` conservatively finds Python call sites through AST only.
It does not import or upload scanned code and makes no volume claim. `--suggest`
prioritizes existing-client imports; `--format sdk` suggests a typed declaration
only when a fixed template is found. Results need review at the real adapter seam.
`seldon skill print` prints the packaged narrow selected-operation skill.

## Development and evidence

```sh
python -m pip install '.[dev]'
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m mypy --strict src/seldon_sdk scripts/typecheck_example.py
python -m build
python scripts/verify_wheel.py dist/*.whl
```

Unit tests replace HTTP through `httpx.MockTransport`, keychain through the `Login`
store seam and local execution through `Runner.load`. `scripts/verify_wheel.py`
creates a fresh environment and tests the installed console script from an unrelated
working directory. Cross-repository real-route/persistence tests live with the
server. No passing SDK unit test establishes production activation or provider
qualification. See `WORK_LOG.md` for actual evidence and outstanding acceptance.

For integrate-first adoption, inspect `seldon reference-readiness FUNCTION_UUID`
then explicitly confirm `seldon serve-reference FUNCTION_UUID`. Readiness is scoped
to that Function; unknown evidence recommends comparing first. This action serves
the reference without starting optimization and ordinary inference remains billed.
A known deadline risk additionally requires `--acknowledge-deadline-risk`.
When the server requires consent to use managed funding for a selected revision,
`publish` / `activate --approve-managed-fallback` carries that consent in the
interactive confirmation. It is never inferred from general access or optimization.

`status` without a locator reads every key in the nearest `seldon.lock.json` (or
`SELDON_LOCKFILE`) and shows active/pending/stale digest state plus seven-day usage.
With no lockfile it lists remote Functions. `activate <function> --alternative N`
selects the 1-based item from the associated run's authoritative report; it prints
the returned immutable revision before the same owner confirmation as `--revision`.

### Release setup

The approved public repository is `Deep-Insight-Labs/seldon-python`. Releases use
`.github/workflows/release.yml` and the existing Python/Pydantic CI matrix. A
`v<version>` tag must exactly match `pyproject.toml`; a branch dispatch builds and
checks artifacts only. Preview `0.1.0.dev1` is published on PyPI;
[release CI](https://github.com/Deep-Insight-Labs/seldon-python/actions/runs/45559766815)
passed TestPyPI installation before uploading the original distributions to PyPI.

Both registries are configured for trusted publishing. For a new publisher
configuration, register project `seldon-sdk` on **both** registries:

| Registry | GitHub owner      | Repository    | Workflow    | Environment |
| -------- | ----------------- | ------------- | ----------- | ----------- |
| TestPyPI | Deep-Insight-Labs | seldon-python | release.yml | testpypi    |
| PyPI     | Deep-Insight-Labs | seldon-python | release.yml | pypi        |

Create matching GitHub environments and set
`SELDON_SDK_TESTPYPI_PUBLISH_ENABLED=true` only after TestPyPI registration.
The first tag publishes there, downloads that exact wheel from TestPyPI, and runs
fresh-environment artifact checks with dependencies from PyPI. Production upload
also requires `SELDON_SDK_PUBLISH_ENABLED=true` and a successful TestPyPI install
in the same workflow. It uploads the original checked distributions. Registry
versions are immutable; do not replace an uploaded release or silently skip an
existing artifact. Keep both variables unset until the release is authorized and
the issued-token, refresh-rotation and remote-logout qualification described above
is recorded. These external checks have not been established by local unit tests.

No registry token belongs in this repository: publication uses GitHub OIDC.
`pip install 'seldon-sdk[local]'` additionally requires a separately published
`seldon-runtime>=0.1.1.dev0`; the base SDK has no runtime dependency.
