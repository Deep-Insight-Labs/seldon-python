# Functions adoption SDK implementation work log

## 2026-11-19 — separate local repository

Created this Apache-2.0 local repository on `feat/functions-adoption` as the shared
SDK/CLI owner. No remote repository, package registry publication, deployment or
paid provider request was performed. Public fixtures and instructions were written
for this repository; private Vector prompts and source code are not included.

Implemented the selected-operation CLI, optional typed runtime, local Runner
adapter and narrow packaged skill. Full SDK delivery remains a development preview:
release/production activation and the external acceptance below are independent.

### Evidence

- Core unit suite: 37 passing tests at this checkpoint. HTTP responses are replaced
  at httpx MockTransport; credential storage uses Login's store interface; typed
  local tests replace Runner.load. All actual async calls are awaited.
- Pydantic minimum: twenty synthetic schema shapes compared against 2.14.3.
  Every minor 2.0 through 2.10 failed digest equality; 2.11.0 passed. Python 3.11
  with 2.11.0 passed the then-current 34-test suite. Python 3.10.19/2.11.0 and
  Python 3.13.15/latest passed the installed-wheel 34-test suite. Later final
  verification is appended below, rather than retroactively expanding those claims.
- Cross-repo canonical fixtures: thirty SDK-owned synthetic cases were evaluated by
  Seldon's actual `sdk_contract.import_sdk` and `executor.render_request` exporter.
  SDK-generated sources/digests/rendered messages agree with that corpus. The
  owning server regeneration test passes. Includes repeated parameters across
  messages, escaped JSON, Unicode, dates, null, booleans, numbers and containers.
- Fresh wheel: `python -m build` produced sdist+wheel; `scripts/verify_wheel.py`
  installed that wheel in a new venv, exercised the console shim, offline import
  and typed stub from an unrelated directory. Lazy package import loads neither
  server/runtime, httpx nor Pydantic and completed below the 150ms bound for that
  process. This is a smoke observation, not a multi-process p95 benchmark.
- Public sync/async annotations pass `mypy --strict scripts/typecheck_example.py`.
  This is consumer typing evidence, not a claim that all internal implementation
  functions have strict annotations.
- Seldon integration test `tests/sdk_compat/test_functions_cli_artifact.py`: fresh
  installed Python 3.13 CLI subprocesses → real uvicorn HTTP → migrated Postgres
  on port5499 → Redis6499 → durable worker/provider fixture. Passed registration,
  idempotent sync, pending drift check, explicit paid-run consent, authoritative
  run reconciliation, report, publication/pinned serve, activation, success,
  authentication failure/recovery, saved-run resume and cleanup. One observed run
  passed in 41.18s. WorkOS issuance is replaced by the existing development
  service-JWT seam; actual role/lifecycle/API-key checks remain active.
- The separate private Vector worktree preserves its existing PydanticAI parser.
  Its adapter/worker tests passed20; the Seldon cross-repo actual application
  subprocess → published pinned Function/runtime test passed7.00s with a shared
  measured-revision factory and deterministic provider. No public SDK test or
  fixture contains its prompts. Those results prove application wiring, not
  financial-document correctness or savings.
- Ruff lint/format and the packaged skill's structural validator are checked before
  commit. Skill-creator guidance was used to keep scope and approvals explicit.

### Contracts and degradation

| Dependency                   | Interface and seam                                       | Failure behavior                                                                              |
| ---------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Seldon management            | sync httpx; injected Login/http                          | bounded error, no automatic mutation retry; uncertain create requires explicit reconciliation |
| WorkOS device/refresh        | sync httpx, store/sleep/clock seams                      | bounded polling; no API-key fallback; rotate refresh token before downstream verification     |
| OS credentials               | sync keyring allowlisted backend or injected store       | memory-only when unavailable at discovery, explicit error when configured storage fails       |
| Function/reference execution | sync thread client or async loop client; injected client | bounded retry; explicit fallback matrix; auth/funding/input errors never fall back            |
| Local Runner                 | async public load/call/status/aclose                     | runtime owns eligibility/conformance/refresh; no unverified typed execution                   |

Source and evidence files stay local until an explicit import. Local associations
hold identifiers/digests/paths only. Auth profiles bind credentials to profile+HTTPS
origin; no redirects carry them to another host. Report reads pin the run id when
associated. Unknown provider capacity and missing local verification are never
reported as successful evidence.

### Remaining external qualification and known scope limits

Live issued-token WorkOS login/refresh/revocation is not established by mocked HTTP
or the development JWT seam. Browser logout reports pending/unavailable rather than
claiming remote revocation. Public repository/name ownership, registry publication,
trusted-publisher configuration, release attestation and production flags are not
changed. Linux/Windows secure keychains and CPU model install/runtime behavior need
their own platform evidence. Real local weights were exercised by the runtime owner,
not by this SDK's unit local adapter test. Full local app fallback/refresh telemetry
qualification remains runtime-owned.

The scanner is intentionally conservative and offers migration guidance; it does
not emit an automatically valid decorator for arbitrary code or infer volume.
Full framework/version matrices, performance p95 suites, concurrent circuit stress,
real-network device-login outcomes and extended/nightly readiness are not claimed
from the focused checks. Existing-client offline validation preserves raw envelopes
and performs bounded structural checks; server contracts remain authoritative for
complete provider/evaluator eligibility.

### Final verification additions

The installed-wheel Python 3.10.19/Pydantic2.11.0 and
Python3.13.15/Pydantic2.14.3 suites both passed37 tests after conformance and public
typing additions. The clean fresh-environment artifact smoke passed again.
Subsequent explicit managed-fallback approval coverage brings the local suite to38;
both publish and activation forward that flag only after interactive confirmation.
The server integration run including source-first reference-readiness/serve-reference
and conformance regeneration passed2 tests in40.47s. Thus both journey orderings
have an actual route/installed-CLI boundary rehearsal. Production feature flags
remain untouched. The Vector application worktree commits are `fe2b77ee` and
`7b533349`; its local main remains unchanged.

Final wheel rebuilt after the approval and bounded-file-read changes: both fresh
installed environments (Python3.10.19/Pydantic2.11.0 and
Python3.13.15/Pydantic2.14.3) pass all38 tests. Local Ruff and public strict typing
checks pass. No editable SDK installation is used by those two artifact suites.

## 2026-11-19 — final preparation/report hardening

The AC audit found that command key locators did not consult the shared lockfile.
They now resolve the nearest/SELDON_LOCKFILE mapping without module imports and
reject malformed self-references without recursion. Reports preserve selected run,
contract digest, diagnostics and serving state; source import returns the actual
server digest and reuses unchanged identity. Offline preview includes destination.
Three added regression tests bring the suite to41 passing. Public strict consumer
typing, Ruff/format, build, twine and fresh Python3.10 base-wheel console/offline/
typed-stub checks pass. Artifact assertions now check license files and prohibit
fixture/test payload in the wheel. CI runs those packaging checks.

The Seldon QA work log lists remaining compound ACs explicitly: public publication,
issued WorkOS login/logout, complete invalid corpus/provenance, internal strict
typing and exhaustive performance/retry/concurrency/scanner matrices. Human-timed
baseline and provider quality/savings remain unmeasured. Actual owning-application
local Runner success/fallback/raise is not covered by the hosted Vector rehearsal.

The final plan audit also implemented lockfile-wide `status` (per-key active,
pending or stale digest plus read-only usage) and 1-based `activate --alternative`
selection from the associated server report. Both retain explicit-ID support,
interactive owner confirmation and server role checks. Two regressions bring the
suite to43 passing, including zero requests for noninteractive alternative
activation. These are implemented command paths, not deferred conveniences.

## 2026-11-20 — release preparation, no publication

Prepared `release.yml`: exact `v<version>` tag validation, the existing full
Python/Pydantic CI matrix as a reusable dependency, build/twine/fresh-wheel checks,
TestPyPI OIDC upload, exact TestPyPI wheel download and fresh installation, then
separately guarded PyPI OIDC upload. Branch dispatches build only. Versions remain
unchanged. README records exact pending-publisher fields and environment/variable
setup; issued-session authentication qualification remains separate.

Local evidence: 43 tests pass; actionlint accepts both workflows; sdist/wheel pass
twine and `scripts/verify_wheel.py` in a fresh environment. Forty tracked files and
Git history were reviewed for common private-key/GitHub/PyPI/AWS credential patterns
and credential filenames: no matches. Source/fixtures are SDK-authored synthetic
content; internal application prompts/schemas/code are absent. This bounded check
is not a claim that automated secret detection proves arbitrary text safe.

Both `seldon-sdk` and `seldon-runtime` returned HTTP404 from PyPI and TestPyPI JSON
APIs at inspection. This does not guarantee registry name claimability. The local
SDK has no remote; no external repository, environment, publisher or package was
created. The GitHub account can administer the existing Seldon repository and the
organization permits public repository creation. No local PyPI credential file or
publishing environment variables were found. Package-owner registry setup is still
needed before publication; the checked artifacts alone do not establish release.

## 2026-11-20 — Live WorkOS device-session qualification

The installed SDK completed the public WorkOS device authorization flow with a
Seldon workspace account. The real management API accepted its issued access
token. The SDK persisted the refresh token using macOS Keychain. A fresh Login
object loaded the saved profile and token, then stored a different rotated refresh
token. SDK logout deleted the keychain entry and requested the documented WorkOS
session logout URL. WorkOS returned HTTP 302 and a later refresh with the rotated
token was rejected with HTTP 400. The temporary profile was removed. No credential
or user claims were logged. Linux and Windows keychain integrations retain their
separate platform qualification scope.

The Apache-2.0 runtime preview 0.1.1.dev0 is published separately. The source SDK
remains 0.1.0.dev0 for its first package release, using the reviewed TestPyPI-first
workflow and checked immutable artifacts.

Release run 44717963207 passed all four Python/Pydantic jobs, built checked
artifacts, published to TestPyPI, verified a fresh installed candidate and
published the original files to PyPI. PyPI SHA-256 matched the downloaded build:

- Wheel `4d9fb0b16657ec983fa36db54240394721dba33a04dae394ab8b71dda4bda268`
- Source `acd0b52a32e7e0a848eee90dc536269d9c6e897d640574899d641c6752907e21`

Source revision `958ab5b`, tag `v0.1.0.dev0`. Package publication and backend
feature activation have separate evidence.

## 2026-11-25 — Required implementation gap closure on main

Required SDK code gaps are addressed locally. The management client uses an
explicit evaluation-only draft update instead of resubmitting SDK-owned source.
Exported SDK sources and optional evaluator definitions validate without changing
request defaults. Server registration preserves separately imported evidence on
unchanged sync. The matching server must deploy before a new CLI release uses
this endpoint; the published preview remains unchanged.

Error objects preserve safe location/execution/correlation metadata. A single
Function boundary calls the metadata hook once for input/configuration failures,
hosted/local execution and stubs. Invalid JSON/envelopes respect explicit output
fallback. Drift remains a contract error. Regression tests were red before fixes.
Source strict typing now passes and CI enforces it plus public consumer typing.
One narrowly scoped overlap annotation in the callable stub preserves async typing;
strict settings are unchanged. Lockfiles have a packaged schema and stable
registration timestamps while legacy entries remain readable.

The shared synthetic corpus has 32 valid and 8 invalid cases, with source revision
and corpus/exporter hashes under conformance/SOURCE. Public-content checks run in
pytest. Deliberate differences between local and server rejection codes remain
explicit. Broad scanning and suggested decorators remain optional deferred work.

Validation on macOS: owning SDK suite 114 passed; Ruff, formatting and strict
source/consumer mypy passed. A built wheel installed in fresh environments from an
unrelated working directory passed all 114 tests for each Python 3.10/3.13 and
Pydantic 2.11.0/2.14.4 combination. Build/twine and fresh base-only console/import/
stub artifact checks passed. The suite covers retries/idempotency, exclusive
breaker probes, 100 async calls across two loops, 20 simultaneous threads, private
payload omission and hook failures, plus repeated import/decoration budgets.
Server-owned actual HTTP/persistence tests also exercised both installed CLI
integration formats with representative synthetic examples, compiler jobs,
publish, activation, invocation and cleanup; these prove integration, not quality.
No package was published, no production state changed, and no live secure-store
qualification was rerun. Other-platform authentication remains separately unverified.

## 2026-11-25 — Prepare dev1 after running-stack QA

Prepared `0.1.0.dev1` with matching package/runtime version and the existing
TestPyPI-first release workflow. Publication waits for the matching backend
production deployment. Full SDK tests (114), strict typing, Ruff/format, build,
twine and fresh base-only wheel verification pass.

The dev1 wheel was installed into a fresh local QA client and exercised against
an independently running router, PostgreSQL, Redis and Celery consumers. Both
explicit-template and typed flows imported four representative synthetic cases,
replayed an unchanged evidence update, compared through real worker processes,
published a revision without moving the alias, activated and invoked it, then
deleted the Function and revoked the test key. Each fixture compilation settled
0.026860 with no holds. The typed callable returned contract-check match against
the selected revision. No external provider or production call occurred.

## 2026-11-25 — Published dev1 after server acceptance

The matching hosted server passed production deployment and smoke acceptance
before tag `v0.1.0.dev1` at `5d70371a6414110c03a25db7d8f33f81feaa7515` was pushed.
[Release CI 45559766815](https://github.com/Deep-Insight-Labs/seldon-python/actions/runs/45559766815)
passed all four Python/Pydantic matrix cells, built/checked artifacts, published to
TestPyPI, verified the exact downloaded wheel in a fresh environment, then
published the original distributions to PyPI.

Public PyPI files were downloaded independently and matched the CI distributions
byte for byte and their registry SHA-256 values:

- Wheel: `790e86f2c75dfbe8c98a3b0a005af5d0e5a052fabda71a49a4f3f5fcb0a9c991`.
- Source archive: `5e3e1f101e6135555cb104bff797b8f75335c790c96020a7a684b44e1cd10044`.

The downloaded wheel passed `scripts/verify_wheel.py` from a fresh environment:
console version, offline import, lazy imports, packaged skill/license/type marker
and typed stub execution. Its wheel digest also matches the wheel used for the
local running-stack rehearsal above. Publication establishes artifact availability;
no additional provider-quality, private-application or cross-platform secure-store
qualification is claimed.
